"""
SourceID SSO Authentication Routes.

This module adds a SourceID-specific OAuth 2.0 authorization code flow while
reusing the existing LiteLLM UI SSO post-login flow for user upsert, UI token
creation, and redirect handling.
"""

import os
import secrets
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import jwt
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from litellm._logging import verbose_proxy_logger
from litellm.litellm_core_utils.dot_notation_indexing import get_nested_value
from litellm.llms.custom_httpx.http_handler import (
    get_async_httpx_client,
    httpxSpecialProvider,
)
from litellm.proxy._types import CommonProxyErrors, LiteLLM_JWTAuth, ProxyErrorTypes, ProxyException
from litellm.proxy.auth.handle_jwt import JWTHandler
from litellm.proxy.common_utils.admin_ui_utils import (
    admin_ui_disabled,
    show_missing_vars_in_env,
)
from litellm.proxy.management_endpoints.types import CustomOpenID, get_litellm_user_role
from litellm.proxy.management_endpoints.ui_sso import (
    SSOAuthenticationHandler,
    normalize_email,
)

router = APIRouter()

SOURCEID_OAUTH_STATE_COOKIE_NAME = "litellm_sourceid_oauth_state"
SOURCEID_OAUTH_STATE_TTL_SECONDS = 600


class SourceIDSSOHandler:
    """Provider adapter for SourceID OAuth 2.0 UI sign-in."""

    @staticmethod
    def get_authorization_url(redirect_uri: str, state: str) -> str:
        sourceid_client_id = os.getenv("SOURCEID_CLIENT_ID")
        sourceid_authorization_endpoint = os.getenv(
            "SOURCEID_AUTHORIZATION_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/authorize",
        )
        sourceid_scope = os.getenv("SOURCEID_SCOPE", "openid profile email")

        if sourceid_client_id is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_ID not set. Set it in the environment.",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_ID",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        params: Dict[str, str] = {
            "response_type": "code",
            "client_id": sourceid_client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if sourceid_scope.strip():
            params["scope"] = sourceid_scope

        parsed_url = urlparse(sourceid_authorization_endpoint)
        query_string = urlencode(params)
        return urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                query_string,
                parsed_url.fragment,
            )
        )

    @staticmethod
    async def exchange_code_for_token(code: str, redirect_uri: str) -> Dict[str, Any]:
        sourceid_client_id = os.getenv("SOURCEID_CLIENT_ID")
        sourceid_client_secret = os.getenv("SOURCEID_CLIENT_SECRET")
        sourceid_token_endpoint = os.getenv(
            "SOURCEID_TOKEN_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/accessToken",
        )

        if sourceid_client_id is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_ID not set. Set it in the environment.",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_ID",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if sourceid_client_secret is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_SECRET not set. Set it in the environment.",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_SECRET",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        async_client = get_async_httpx_client(
            llm_provider=httpxSpecialProvider.SSO_HANDLER
        )
        try:
            response = await async_client.post(
                sourceid_token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": sourceid_client_id,
                    "client_secret": sourceid_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            verbose_proxy_logger.exception("SourceID token exchange failed: %s", e)
            raise ProxyException(
                message=f"Failed to exchange authorization code for token: {e}",
                type=ProxyErrorTypes.auth_error,
                param="token_exchange",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        sourceid_userinfo_endpoint = os.getenv(
            "SOURCEID_USERINFO_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/profile",
        )

        async_client = get_async_httpx_client(
            llm_provider=httpxSpecialProvider.SSO_HANDLER
        )
        try:
            response = await async_client.get(
                sourceid_userinfo_endpoint,
                params={"access_token": access_token},
            )
            response.raise_for_status()
            return response.json()
        except Exception as query_param_error:
            verbose_proxy_logger.debug(
                "SourceID user info request with query param failed: %s",
                query_param_error,
            )

        try:
            response = await async_client.get(
                sourceid_userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as bearer_error:
            verbose_proxy_logger.exception(
                "SourceID user info request failed: %s", bearer_error
            )
            raise ProxyException(
                message=f"Failed to get user information: {bearer_error}",
                type=ProxyErrorTypes.auth_error,
                param="userinfo",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    def _decode_access_token(access_token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(access_token, options={"verify_signature": False})
            if isinstance(payload, dict):
                return payload
        except Exception:
            verbose_proxy_logger.debug("SourceID access token is not a JWT payload")
        return None

    @staticmethod
    def _extract_user_role(payload: Optional[Dict[str, Any]]) -> Optional[Any]:
        if payload is None:
            return None

        sourceid_user_role_attribute = os.getenv("SOURCEID_USER_ROLE_ATTRIBUTE")
        if sourceid_user_role_attribute is None:
            return None

        role_value = get_nested_value(payload, sourceid_user_role_attribute)
        if isinstance(role_value, list) and len(role_value) > 0:
            role_value = role_value[0]

        return get_litellm_user_role(role_value)

    @staticmethod
    def _collect_team_ids(
        payloads: List[Optional[Dict[str, Any]]],
        jwt_handler: JWTHandler,
        sso_jwt_handler: Optional[JWTHandler],
    ) -> List[str]:
        all_team_ids: List[str] = []
        for payload in payloads:
            if payload is None:
                continue
            if sso_jwt_handler is not None:
                all_team_ids.extend(sso_jwt_handler.get_team_ids_from_jwt(payload))
            all_team_ids.extend(jwt_handler.get_team_ids_from_jwt(payload))

        deduped_team_ids: List[str] = []
        for team_id in all_team_ids:
            if isinstance(team_id, str) and team_id not in deduped_team_ids:
                deduped_team_ids.append(team_id)

        return deduped_team_ids

    @staticmethod
    def openid_from_response(
        response: Dict[str, Any],
        jwt_handler: JWTHandler,
        sso_jwt_handler: Optional[JWTHandler],
        access_token_payload: Optional[Dict[str, Any]] = None,
    ) -> CustomOpenID:
        sourceid_user_id_attribute = os.getenv("SOURCEID_USER_ID_ATTRIBUTE", "id")
        sourceid_user_email_attribute = os.getenv(
            "SOURCEID_USER_EMAIL_ATTRIBUTE", "attributes.RJEMAIL"
        )
        sourceid_user_display_name_attribute = os.getenv(
            "SOURCEID_USER_DISPLAY_NAME_ATTRIBUTE", "attributes.RJXM"
        )
        sourceid_user_first_name_attribute = os.getenv(
            "SOURCEID_USER_FIRST_NAME_ATTRIBUTE", "attributes.XM"
        )
        sourceid_user_last_name_attribute = os.getenv(
            "SOURCEID_USER_LAST_NAME_ATTRIBUTE", "attributes.XM"
        )

        team_ids = SourceIDSSOHandler._collect_team_ids(
            payloads=[access_token_payload, response],
            jwt_handler=jwt_handler,
            sso_jwt_handler=sso_jwt_handler,
        )

        user_role = SourceIDSSOHandler._extract_user_role(response)
        if user_role is None:
            user_role = SourceIDSSOHandler._extract_user_role(access_token_payload)

        return CustomOpenID(
            id=get_nested_value(response, sourceid_user_id_attribute),
            display_name=get_nested_value(response, sourceid_user_display_name_attribute),
            email=normalize_email(
                get_nested_value(response, sourceid_user_email_attribute)
            ),
            first_name=get_nested_value(response, sourceid_user_first_name_attribute),
            last_name=get_nested_value(response, sourceid_user_last_name_attribute),
            provider="sourceid",
            team_ids=team_ids,
            user_role=user_role,
        )


def _build_sso_jwt_handler(
    general_settings: Dict[str, Any],
    prisma_client: Any,
    user_api_key_cache: Any,
) -> Optional[JWTHandler]:
    ui_access_mode = general_settings.get("ui_access_mode")
    if not isinstance(ui_access_mode, dict):
        return None

    sso_jwt_handler = JWTHandler()
    sso_jwt_handler.update_environment(
        prisma_client=prisma_client,
        user_api_key_cache=user_api_key_cache,
        litellm_jwtauth=LiteLLM_JWTAuth(
            team_ids_jwt_field=ui_access_mode.get("sso_group_jwt_field")
        ),
        leeway=0,
    )
    return sso_jwt_handler


def _validate_state_from_cookie(request: Request, state: Optional[str]) -> None:
    cookie_state = request.cookies.get(SOURCEID_OAUTH_STATE_COOKIE_NAME)
    if (
        not isinstance(state, str)
        or not isinstance(cookie_state, str)
        or not secrets.compare_digest(state, cookie_state)
    ):
        raise ProxyException(
            message=(
                "Invalid OAuth state parameter — does not match the browser-bound "
                "state cookie."
            ),
            type=ProxyErrorTypes.auth_error,
            param="state",
            code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/sso/sourceid/login", tags=["experimental"], include_in_schema=False)
async def sourceid_login(request: Request) -> RedirectResponse:
    _disable_ui_flag = os.getenv("DISABLE_ADMIN_UI")
    if _disable_ui_flag is not None and os.getenv("DISABLE_ADMIN_UI"):
        from litellm.secret_managers.main import str_to_bool

        if str_to_bool(value=_disable_ui_flag):
            return admin_ui_disabled()

    missing_env_vars = show_missing_vars_in_env()
    if missing_env_vars is not None:
        return missing_env_vars

    return_to = request.query_params.get("return_to")

    redirect_url = SSOAuthenticationHandler.get_redirect_url_for_sso(
        request=request,
        sso_callback_route="sso/sourceid/callback",
    )
    state = secrets.token_urlsafe(32)
    auth_url = SourceIDSSOHandler.get_authorization_url(
        redirect_uri=redirect_url,
        state=state,
    )

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=SOURCEID_OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=SOURCEID_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    if return_to is not None and SSOAuthenticationHandler._validate_return_to(return_to):
        response.set_cookie(
            key="litellm_cp_return_to",
            value=return_to,
            max_age=600,
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/sso/sourceid/callback", tags=["experimental"], include_in_schema=False)
async def sourceid_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
) -> RedirectResponse:
    from litellm.proxy.proxy_server import (
        general_settings,
        jwt_handler,
        master_key,
        prisma_client,
        user_api_key_cache,
    )

    if prisma_client is None:
        raise HTTPException(
            status_code=500,
            detail=CommonProxyErrors.db_not_connected_error.value,
        )
    if master_key is None:
        raise ProxyException(
            message=(
                "Master Key not set for Proxy. Please set Master Key to use Admin UI. "
                "Set LITELLM_MASTER_KEY in .env or set general_settings:master_key in config.yaml."
            ),
            type=ProxyErrorTypes.auth_error,
            param="master_key",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if error is not None:
        raise HTTPException(
            status_code=401,
            detail=f"OAuth authentication failed: {error}",
        )
    if not isinstance(code, str) or len(code) == 0:
        raise HTTPException(
            status_code=400,
            detail="Authorization code not provided",
        )

    _validate_state_from_cookie(request=request, state=state)

    redirect_url = SSOAuthenticationHandler.get_redirect_url_for_sso(
        request=request,
        sso_callback_route="sso/sourceid/callback",
    )

    sso_jwt_handler = _build_sso_jwt_handler(
        general_settings=general_settings,
        prisma_client=prisma_client,
        user_api_key_cache=user_api_key_cache,
    )

    token_response = await SourceIDSSOHandler.exchange_code_for_token(
        code=code,
        redirect_uri=redirect_url,
    )
    access_token = token_response.get("access_token")
    if not isinstance(access_token, str) or len(access_token) == 0:
        raise ProxyException(
            message="Access token not found in SourceID token response.",
            type=ProxyErrorTypes.auth_error,
            param="access_token",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    user_info = await SourceIDSSOHandler.get_user_info(access_token=access_token)
    access_token_payload = SourceIDSSOHandler._decode_access_token(access_token)
    result = SourceIDSSOHandler.openid_from_response(
        response=user_info,
        jwt_handler=jwt_handler,
        sso_jwt_handler=sso_jwt_handler,
        access_token_payload=access_token_payload,
    )

    redirect_response = await SSOAuthenticationHandler.get_redirect_response_from_openid(
        result=result,
        request=request,
        received_response=user_info,
        ui_access_mode=general_settings.get("ui_access_mode"),
        access_token_payload=access_token_payload,
        jwt_handler=jwt_handler,
    )
    redirect_response.delete_cookie(SOURCEID_OAUTH_STATE_COOKIE_NAME)
    return redirect_response