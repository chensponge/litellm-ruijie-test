"""
SourceID SSO Authentication Routes

Implements OAuth 2.0 authorization code flow for SourceID authentication.
Reference: https://sourceid.ruishan.cc/linkid/authentication/public/interface/oauth-authentication.html
"""

import asyncio
import os
from typing import Any, Dict, List, Optional, Union, cast
from urllib.parse import urlencode, urlparse, urlunparse

import litellm
from litellm.caching import DualCache

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import RedirectResponse

from litellm._logging import verbose_proxy_logger
from litellm._uuid import uuid
from litellm.llms.custom_httpx.http_handler import (
    get_async_httpx_client,
    httpxSpecialProvider,
)
from litellm.proxy._types import (
    CommonProxyErrors,
    Member,
    NewUserRequest,
    NewUserResponse,
    ProxyErrorTypes,
    ProxyException,
    SSOUserDefinedValues,
    TeamMemberAddRequest,
    UserAPIKeyAuth,
)
from litellm.proxy._types import LiteLLM_UserTable, LitellmUserRoles
from litellm.proxy.auth.auth_checks import ExperimentalUIJWTToken, get_user_object
from litellm.proxy.auth.handle_jwt import JWTHandler
from litellm.proxy.common_utils.admin_ui_utils import admin_ui_disabled, show_missing_vars_in_env
from litellm.proxy.management_endpoints.sso_helper_utils import (
    check_is_admin_only_access,
    has_admin_ui_access,
)
from litellm.proxy.management_endpoints.team_endpoints import team_member_add
from litellm.proxy.management_endpoints.internal_user_endpoints import new_user
from litellm.proxy.management_endpoints.types import (
    CustomOpenID,
    is_valid_litellm_user_role,
)
from litellm.proxy.utils import PrismaClient, ProxyLogging, get_custom_url, get_server_root_path

from litellm.types.proxy.ui_sso import ParsedOpenIDResult, ReturnedUITokenObject
from litellm.litellm_core_utils.dot_notation_indexing import get_nested_value
import jwt

router = APIRouter()


async def create_team_member_add_task(
    team_id: str, user_info: Union[NewUserResponse, LiteLLM_UserTable]
):
    """Create a task for adding a member to a team."""
    try:
        member = Member(user_id=user_info.user_id, role="user")
        team_member_add_request = TeamMemberAddRequest(
            member=member,
            team_id=team_id,
        )
        return await team_member_add(
            data=team_member_add_request,
            user_api_key_dict=UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN),
        )
    except Exception as e:
        verbose_proxy_logger.debug(
            f"[Non-Blocking] Error trying to add sso user to db: {e}"
        )


async def add_missing_team_member(
    user_info: Union[NewUserResponse, LiteLLM_UserTable], sso_teams: List[str]
):
    """
    - Get missing teams (diff b/w user_info.team_ids and sso_teams)
    - Add missing user to missing teams
    """
    user_teams = user_info.teams if user_info.teams is not None else []
    missing_teams = set(sso_teams) - set(user_teams)
    missing_teams_list = list(missing_teams)
    tasks = [
        create_team_member_add_task(team_id, user_info)
        for team_id in missing_teams_list
    ]

    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        verbose_proxy_logger.debug(
            f"[Non-Blocking] Error trying to add sso user to db: {e}"
        )
        

def get_disabled_non_admin_personal_key_creation():
    key_generation_settings = litellm.key_generation_settings
    if key_generation_settings is None:
        return Fal
    personal_key_generation = (
        key_generation_settings.get("personal_key_generation") or {}
    )
    allowed_user_roles = personal_key_generation.get("allowed_user_roles") or []
    return bool("proxy_admin" in allowed_user_roles)


async def get_existing_user_info_from_db(
    user_id: Optional[str],
    user_email: Optional[str],
    prisma_client: PrismaClient,
    user_api_key_cache: DualCache,
    proxy_logging_obj: ProxyLogging,
) -> Optional[LiteLLM_UserTable]:
    try:
        user_info = await get_user_object(
            user_id=user_id,
            user_email=user_email,
            prisma_client=prisma_client,
            user_api_key_cache=user_api_key_cache,
            user_id_upsert=False,
            parent_otel_span=None,
            proxy_logging_obj=proxy_logging_obj,
            sso_user_id=None,
        )
    except Exception as e:
        verbose_proxy_logger.debug(f"Error getting user object: {e}")
        user_info = None

    return user_info


async def get_user_info_from_db(
    result: CustomOpenID,
    prisma_client: PrismaClient,
    user_api_key_cache: DualCache,
    proxy_logging_obj: ProxyLogging,
    user_email: Optional[str],
    user_defined_values: Optional[SSOUserDefinedValues],
    alternate_user_id: Optional[str] = None,
) -> Optional[Union[LiteLLM_UserTable, NewUserResponse]]:
    try:
        potential_user_ids = []
        if alternate_user_id is not None:
            potential_user_ids.append(alternate_user_id)
        if not isinstance(result, dict):
            _id = getattr(result, "id", None)
            if _id is not None and isinstance(_id, str):
                potential_user_ids.append(_id)
        else:
            _id = result.get("id", None)
            if _id is not None and isinstance(_id, str):
                potential_user_ids.append(_id)

        user_email = (
            getattr(result, "email", None)
            if not isinstance(result, dict)
            else result.get("email", None)
        )

        user_info: Optional[Union[LiteLLM_UserTable, NewUserResponse]] = None

        for user_id in potential_user_ids:
            user_info = await get_existing_user_info_from_db(
                user_id=user_id,
                user_email=user_email,
                prisma_client=prisma_client,
                user_api_key_cache=user_api_key_cache,
                proxy_logging_obj=proxy_logging_obj,
            )
            if user_info is not None:
                break

        verbose_proxy_logger.debug(
            f"user_info: {user_info}; litellm.default_internal_user_params: {litellm.default_internal_user_params}"
        )

        if user_info is None:
            user_info = await SSOAuthenticationHandler.upsert_sso_user(
                result=result,
                user_info=user_info,
                user_email=user_email,
                user_defined_values=user_defined_values,
                prisma_client=prisma_client,
            )

        await SSOAuthenticationHandler.add_user_to_teams_from_sso_response(
            result=result,
            user_info=user_info,
        )

        return user_info
    except Exception as e:
        verbose_proxy_logger.exception(
            f"[Non-Blocking] Error trying to add sso user to db: {e}"
        )

    return None


def _should_use_role_from_sso_response(sso_role: Optional[str]) -> bool:
    """returns true if SSO upsert should use the 'role' defined on the SSO response"""
    if sso_role is None:
        return False

    if not is_valid_litellm_user_role(sso_role):
        verbose_proxy_logger.debug(
            f"SSO role '{sso_role}' is not a valid LiteLLM user role. "
            "Ignoring role from SSO response. See LitellmUserRoles enum for valid roles."
        )
        return False
    return True


def apply_user_info_values_to_sso_user_defined_values(
    user_info: Optional[Union[LiteLLM_UserTable, NewUserResponse]],
    user_defined_values: Optional[SSOUserDefinedValues],
) -> Optional[SSOUserDefinedValues]:
    if user_defined_values is None:
        return None
    if user_info is not None and user_info.user_id is not None:
        user_defined_values["user_id"] = user_info.user_id

    sso_role = user_defined_values.get("user_role")
    db_role = user_info.user_role if user_info else None

    if _should_use_role_from_sso_response(sso_role):
        verbose_proxy_logger.info(
            f"Using SSO role: {sso_role} (DB role was: {db_role})"
        )
    else:
        if user_info is None or user_info.user_role is None:
            user_defined_values["user_role"] = (
                LitellmUserRoles.INTERNAL_USER_VIEW_ONLY.value
            )
            verbose_proxy_logger.debug(
                "No SSO or DB role found, using default: INTERNAL_USER_VIEW_ONLY"
            )
        else:
            user_defined_values["user_role"] = user_info.user_role
            verbose_proxy_logger.debug(f"Using DB role: {user_info.user_role}")

    if user_info is not None and hasattr(user_info, "models") and user_info.models:
        user_defined_values["models"] = user_info.models

    return user_defined_values


async def check_and_update_if_proxy_admin_id(
    user_role: str, user_id: str, prisma_client: Optional[PrismaClient]
):
    """
    - Check if user role in DB is admin
    - If not, update user role in DB to admin role
    """
    proxy_admin_id = os.getenv("PROXY_ADMIN_ID")
    if proxy_admin_id is not None and proxy_admin_id == user_id:
        if user_role and user_role == LitellmUserRoles.PROXY_ADMIN.value:
            return user_role

        if prisma_client:
            await prisma_client.db.litellm_usertable.update(
                where={"user_id": user_id},
                data={"user_role": LitellmUserRoles.PROXY_ADMIN.value},
            )

        user_role = LitellmUserRoles.PROXY_ADMIN.value

    return user_role


async def insert_sso_user(
    result_openid: Optional[Union[Any, dict]],
    user_defined_values: Optional[SSOUserDefinedValues] = None,
) -> NewUserResponse:
    """
    Helper function to create a New User in LiteLLM DB after a successful SSO login
    """
    verbose_proxy_logger.debug(
        f"Inserting SSO user into DB. User values: {user_defined_values}"
    )
    if result_openid is None:
        raise ValueError("result_openid is None")
    if isinstance(result_openid, dict):
        result_openid = type("OpenID", (), result_openid)()

    if user_defined_values is None:
        raise ValueError("user_defined_values is None")

    if litellm.default_internal_user_params:
        user_defined_values.update(litellm.default_internal_user_params)  # type: ignore

    if user_defined_values.get("user_role") == LitellmUserRoles.INTERNAL_USER.value:
        if user_defined_values.get("max_budget") is None:
            user_defined_values["max_budget"] = litellm.max_internal_user_budget
        if user_defined_values.get("budget_duration") is None:
            user_defined_values["budget_duration"] = (
                litellm.internal_user_budget_duration
            )

    if user_defined_values["user_role"] is None:
        user_defined_values["user_role"] = LitellmUserRoles.INTERNAL_USER_VIEW_ONLY

    new_user_request = NewUserRequest(
        user_id=user_defined_values["user_id"],
        user_email=user_defined_values["user_email"],
        user_role=user_defined_values["user_role"],  # type: ignore
        max_budget=user_defined_values["max_budget"],
        budget_duration=user_defined_values["budget_duration"],
        sso_user_id=None,
        auto_create_key=False,
    )

    if result_openid and hasattr(result_openid, "provider"):
        new_user_request.metadata = {
            "auth_provider": getattr(result_openid, "provider")
        }

    response = await new_user(
        data=new_user_request,
        user_api_key_dict=UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN),
    )

    return response


class SSOAuthenticationHandler:
    """
    Handler for SSO Authentication across all SSO providers
    """

    @staticmethod
    async def upsert_sso_user(
        result: Optional[Union[CustomOpenID, Any, dict]],
        user_info: Optional[Union[NewUserResponse, LiteLLM_UserTable]],
        user_email: Optional[str],
        user_defined_values: Optional[SSOUserDefinedValues],
        prisma_client: PrismaClient,
    ):
        """
        Connects the SSO Users to the User Table in LiteLLM DB

        - If user on LiteLLM DB, update the user_email with the SSO user_email
        - If user not on LiteLLM DB, insert the user into LiteLLM DB
        """
        try:
            if user_info is not None:
                user_id = user_info.user_id
                await prisma_client.db.litellm_usertable.update_many(
                    where={"user_id": user_id}, data={"user_email": user_email}
                )
            else:
                verbose_proxy_logger.info(
                    "user not in DB, inserting user into LiteLLM DB"
                )
                user_info = await insert_sso_user(
                    result_openid=result,
                    user_defined_values=user_defined_values,
                )
            return user_info
        except Exception as e:
            verbose_proxy_logger.exception(
                f"Error upserting SSO user into LiteLLM DB: {e}"
            )
            return user_info

    @staticmethod
    async def add_user_to_teams_from_sso_response(
        result: Optional[Union[CustomOpenID, Any, dict]],
        user_info: Optional[Union[NewUserResponse, LiteLLM_UserTable]],
    ):
        """
        Adds the user as a team member to the teams specified in the SSO responses `team_ids` field
        """
        if user_info is None:
            verbose_proxy_logger.debug(
                "User not found in LiteLLM DB, skipping team member addition"
            )
            return
        sso_teams = getattr(result, "team_ids", [])
        await add_missing_team_member(user_info=user_info, sso_teams=sso_teams)

    @staticmethod
    def verify_user_in_restricted_sso_group(
        general_settings: Dict,
        result: Optional[Union[CustomOpenID, Any, dict]],
        received_response: Optional[dict],
    ) -> bool:
        """
        when ui_access_mode.type == "restricted_sso_group":
        """
        ui_access_mode = cast(
            Optional[Union[Dict, str]], general_settings.get("ui_access_mode")
        )

        if ui_access_mode is None or isinstance(ui_access_mode, str):
            return True
        team_ids = getattr(result, "team_ids", [])

        if ui_access_mode.get("type") == "restricted_sso_group":
            restricted_sso_group = ui_access_mode.get("restricted_sso_group")
            if restricted_sso_group not in team_ids:
                raise ProxyException(
                    message=f"User is not in the restricted SSO group: {restricted_sso_group}. User groups: {team_ids}. Received SSO response: {received_response}",
                    type=ProxyErrorTypes.auth_error,
                    param="restricted_sso_group",
                    code=status.HTTP_403_FORBIDDEN,
                )
        return True

    @staticmethod
    def _get_user_email_and_id_from_result(
        result: Optional[Union[Any, dict]],
        generic_client_id: Optional[str] = None,
    ) -> ParsedOpenIDResult:
        """
        Gets the user email and id from the OpenID result after validating the email domain
        """
        user_email: Optional[str] = getattr(result, "email", None)
        user_id: Optional[str] = (
            getattr(result, "id", None) if result is not None else None
        )
        user_role: Optional[str] = None

        if user_email is not None and os.getenv("ALLOWED_EMAIL_DOMAINS") is not None:
            email_domain = user_email.split("@")[1]
            allowed_domains = os.getenv("ALLOWED_EMAIL_DOMAINS").split(",")  # type: ignore
            if email_domain not in allowed_domains:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "message": "The email domain={}, is not an allowed email domain={}. Contact your admin to change this.".format(
                            email_domain, allowed_domains
                        )
                    },
                )

        if result is not None:
            _user_role = getattr(result, "user_role", None)
            if _user_role is not None:
                user_role = (
                    _user_role.value
                    if isinstance(_user_role, LitellmUserRoles)
                    else _user_role
                )
                verbose_proxy_logger.debug(
                    f"Extracted user_role from SSO result: {user_role}"
                )

        if generic_client_id is not None and result is not None:
            generic_user_role_attribute_name = os.getenv(
                "GENERIC_USER_ROLE_ATTRIBUTE", "role"
            )
            user_id = getattr(result, "id", None)
            user_email = getattr(result, "email", None)
            user_role = getattr(result, generic_user_role_attribute_name, None)  # type: ignore

        if user_id is None and result is not None:
            _first_name = getattr(result, "first_name", "") or ""
            _last_name = getattr(result, "last_name", "") or ""
            user_id = _first_name + _last_name

        if user_email is not None and (user_id is None or len(user_id) == 0):
            user_id = user_email

        return ParsedOpenIDResult(
            user_email=user_email,
            user_id=user_id,
            user_role=user_role,
        )


class SourceIDSSOHandler:
    """
    Handler for SourceID SSO Authentication using OAuth 2.0 authorization code flow
    """

    @staticmethod
    def get_authorization_url(
        redirect_uri: str,
        state: Optional[str] = None,
    ) -> str:
        """
        Generate the authorization URL for SourceID OAuth 2.0 flow.

        Args:
            redirect_uri: The callback URL after authorization
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL string
        """
        sourceid_client_id = os.getenv("SOURCEID_CLIENT_ID", None)
        sourceid_authorization_endpoint = os.getenv(
            "SOURCEID_AUTHORIZATION_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/authorize"
        )

        if sourceid_client_id is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_ID not set. Set it in .env file",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_ID",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Generate state if not provided
        if state is None:
            state = uuid.uuid4().hex

        params = {
            "response_type": "code",
            "client_id": sourceid_client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }

        # Build authorization URL
        parsed_url = urlparse(sourceid_authorization_endpoint)
        query_string = urlencode(params)
        auth_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            query_string,
            parsed_url.fragment,
        ))

        verbose_proxy_logger.debug(f"SourceID authorization URL: {auth_url}")
        return auth_url

    @staticmethod
    async def exchange_code_for_token(
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from callback
            redirect_uri: The callback URL (must match authorization request)

        Returns:
            Token response dictionary containing access_token and other fields
        """
        sourceid_client_id = os.getenv("SOURCEID_CLIENT_ID", None)
        sourceid_client_secret = os.getenv("SOURCEID_CLIENT_SECRET", None)
        sourceid_token_endpoint = os.getenv(
            "SOURCEID_TOKEN_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/accessToken"
        )

        if sourceid_client_id is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_ID not set. Set it in .env file",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_ID",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if sourceid_client_secret is None:
            raise ProxyException(
                message="SOURCEID_CLIENT_SECRET not set. Set it in .env file",
                type=ProxyErrorTypes.auth_error,
                param="SOURCEID_CLIENT_SECRET",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Prepare token request
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": sourceid_client_id,
            "client_secret": sourceid_client_secret,
        }

        async_client = get_async_httpx_client(
            llm_provider=httpxSpecialProvider.SSO_HANDLER
        )

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        verbose_proxy_logger.debug(
            f"Exchanging code for token at: {sourceid_token_endpoint}"
        )

        try:
            response = await async_client.post(
                sourceid_token_endpoint,
                data=token_data,
                headers=headers,
            )
            response.raise_for_status()
            token_response = response.json()

            verbose_proxy_logger.debug(
                f"Token exchange response: {token_response}"
            )

            return token_response
        except Exception as e:
            verbose_proxy_logger.exception(
                f"Error exchanging code for token: {e}"
            )
            raise ProxyException(
                message=f"Failed to exchange authorization code for token: {str(e)}",
                type=ProxyErrorTypes.auth_error,
                param="token_exchange",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    async def get_user_info(access_token: str) -> Dict[str, Any]:
        """
        Get user information using access token.

        Args:
            access_token: Access token from token exchange

        Returns:
            User information dictionary
        """
        sourceid_userinfo_endpoint = os.getenv(
            "SOURCEID_USERINFO_ENDPOINT",
            "https://sid.ruijie.com.cn/oauth2.0/profile"
        )

        async_client = get_async_httpx_client(
            llm_provider=httpxSpecialProvider.SSO_HANDLER
        )

        # SourceID may use query parameter or Authorization header
        # Try query parameter first as per documentation
        params = {"access_token": access_token}
        headers = {}

        verbose_proxy_logger.debug(
            f"Getting user info from: {sourceid_userinfo_endpoint}"
        )

        try:
            response = await async_client.get(
                sourceid_userinfo_endpoint,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            user_info = response.json()

            verbose_proxy_logger.debug(f"User info response: {user_info}")

            return user_info
        except Exception as e:
            verbose_proxy_logger.exception(
                f"Error getting user info: {e}"
            )
            # Try with Authorization header as fallback
            try:
                headers = {"Authorization": f"Bearer {access_token}"}
                response = await async_client.get(
                    sourceid_userinfo_endpoint,
                    headers=headers,
                )
                response.raise_for_status()
                user_info = response.json()
                return user_info
            except Exception as e2:
                verbose_proxy_logger.exception(
                    f"Error getting user info with Bearer token: {e2}"
                )
                raise ProxyException(
                    message=f"Failed to get user information: {str(e2)}",
                    type=ProxyErrorTypes.auth_error,
                    param="userinfo",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

    @staticmethod
    def convert_to_custom_openid(
        user_info: Dict[str, Any],
        jwt_handler: JWTHandler,
        sso_jwt_handler: Optional[JWTHandler] = None,
    ) -> CustomOpenID:
        """
        Convert SourceID user info response to CustomOpenID format.

        Args:
            user_info: User information dictionary from SourceID
            jwt_handler: JWT handler for team ID extraction
            sso_jwt_handler: Optional SSO-specific JWT handler

        Returns:
            CustomOpenID object
        """
        # Map SourceID user attributes to OpenID format
        # Adjust these based on actual SourceID response structure
        # Defaults align with SourceID response structure; override via env vars if needed
        sourceid_user_id_attribute = os.getenv(
            "SOURCEID_USER_ID_ATTRIBUTE", "id"
        )
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

        # Extract team IDs from JWT if available
        all_teams = []
        if sso_jwt_handler is not None:
            team_ids = sso_jwt_handler.get_team_ids_from_jwt(user_info)
            all_teams.extend(team_ids)

        team_ids = jwt_handler.get_team_ids_from_jwt(user_info)
        all_teams.extend(team_ids)

        return CustomOpenID(
            id=get_nested_value(user_info, sourceid_user_id_attribute),
            display_name=get_nested_value(
                user_info, sourceid_user_display_name_attribute
            ),
            email=get_nested_value(user_info, sourceid_user_email_attribute),
            first_name=get_nested_value(
                user_info, sourceid_user_first_name_attribute
            ),
            last_name=get_nested_value(
                user_info, sourceid_user_last_name_attribute
            ),
            provider="sourceid",
            team_ids=all_teams,
            user_role=None,
        )

    @staticmethod
    def get_redirect_url_for_sso(
        request: Request,
        sso_callback_route: str,
    ) -> str:
        """
        Get the redirect URL for SSO callback.

        Args:
            request: FastAPI request object
            sso_callback_route: Callback route path

        Returns:
            Full callback URL
        """
        redirect_url = get_custom_url(request_base_url=str(request.base_url))
        if redirect_url.endswith("/"):
            redirect_url += sso_callback_route
        else:
            redirect_url += "/" + sso_callback_route
        return redirect_url


@router.get("/sso/sourceid/login", tags=["experimental"], include_in_schema=False)
async def sourceid_login(
    request: Request,
):
    """
    Initiate SourceID SSO login flow.
    Redirects user to SourceID authorization endpoint.
    """

    # Check if UI is disabled
    _disable_ui_flag = os.getenv("DISABLE_ADMIN_UI")
    if _disable_ui_flag is not None:
        from litellm.secret_managers.main import str_to_bool
        is_disabled = str_to_bool(value=_disable_ui_flag)
        if is_disabled:
            return admin_ui_disabled()

    # Detect DB + MASTER KEY in .env
    missing_env_vars = show_missing_vars_in_env()
    if missing_env_vars is not None:
        return missing_env_vars

    # Get redirect URL for callback
    redirect_url = SourceIDSSOHandler.get_redirect_url_for_sso(
        request=request,
        sso_callback_route="sso/sourceid/callback",
    )

    state: Optional[str] = None

    # Generate authorization URL
    auth_url = SourceIDSSOHandler.get_authorization_url(
        redirect_uri=redirect_url,
        state=state,
    )

    verbose_proxy_logger.info(f"Redirecting to SourceID login: {auth_url}")
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/sso/sourceid/callback", tags=["experimental"], include_in_schema=False)
async def sourceid_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Handle SourceID OAuth callback.
    Exchanges authorization code for access token and retrieves user information.
    """
    from litellm.proxy._types import LiteLLM_JWTAuth

    from litellm.proxy.proxy_server import prisma_client, master_key, general_settings, jwt_handler, user_api_key_cache
    if prisma_client is None:
        raise HTTPException(
            status_code=500,
            detail=CommonProxyErrors.db_not_connected_error.value
        )

    if master_key is None:
        raise ProxyException(
            message="Master Key not set for Proxy. Please set Master Key to use Admin UI. Set `LITELLM_MASTER_KEY` in .env or set general_settings:master_key in config.yaml.",
            type=ProxyErrorTypes.auth_error,
            param="master_key",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Check for OAuth errors
    if error:
        verbose_proxy_logger.error(f"SourceID OAuth error: {error}")
        raise HTTPException(
            status_code=401,
            detail=f"OAuth authentication failed: {error}",
        )

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Authorization code not provided",
        )

    # Get redirect URL (must match authorization request)
    redirect_url = SourceIDSSOHandler.get_redirect_url_for_sso(
        request=request,
        sso_callback_route="sso/sourceid/callback",
    )

    # Setup SSO JWT handler if needed
    sso_jwt_handler: Optional[JWTHandler] = None
    ui_access_mode = general_settings.get("ui_access_mode", None)
    if ui_access_mode is not None and isinstance(ui_access_mode, dict):
        sso_jwt_handler = JWTHandler()
        sso_jwt_handler.update_environment(
            prisma_client=prisma_client,
            user_api_key_cache=user_api_key_cache,
            litellm_jwtauth=LiteLLM_JWTAuth(
                team_ids_jwt_field=general_settings.get("ui_access_mode", {}).get(
                    "sso_group_jwt_field", None
                ),
            ),
            leeway=0,
        )

    try:
        # Exchange code for token
        token_response = await SourceIDSSOHandler.exchange_code_for_token(
            code=code,
            redirect_uri=redirect_url,
        )

        access_token = token_response.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=500,
                detail="Access token not found in token response",
            )

        # Get user information
        user_info = await SourceIDSSOHandler.get_user_info(
            access_token=access_token
        )

        print(f"SourceID user info: {user_info}")   
        verbose_proxy_logger.info(f"SourceID user info: {user_info}")   
        # Convert to CustomOpenID format
        result = SourceIDSSOHandler.convert_to_custom_openid(
            user_info=user_info,
            jwt_handler=jwt_handler,
            sso_jwt_handler=sso_jwt_handler,
        )

        # Handle regular UI callback
        return await get_redirect_response_from_sourceid_openid(
            result=result,
            request=request,
            ui_access_mode=ui_access_mode,
        )

    except Exception as e:
        verbose_proxy_logger.exception(f"Error in SourceID callback: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process SourceID authentication: {str(e)}",
        )


async def get_redirect_response_from_sourceid_openid(
    result: CustomOpenID,
    request: Request,
    ui_access_mode: Optional[Dict] = None,
) -> RedirectResponse:
    """
    Generate redirect response after successful SourceID authentication.
    Creates user session and redirects to LiteLLM UI.
    """
    from litellm.proxy.proxy_server import prisma_client, user_api_key_cache, proxy_logging_obj, generate_key_helper_fn, premium_user, user_custom_sso, general_settings
    prisma_client_instance = prisma_client
    if prisma_client_instance is None:
        raise HTTPException(
            status_code=500,
            detail="Prisma client is None, connect a database to your proxy"
        )

    # Parse user info from result
    parsed_openid_result = SSOAuthenticationHandler._get_user_email_and_id_from_result(
        result=result
    )
    user_email = parsed_openid_result.get("user_email")
    user_id = parsed_openid_result.get("user_id")
    user_role = parsed_openid_result.get("user_role")

    verbose_proxy_logger.info(f"SourceID callback result: {result}")

    user_info = None
    user_id_models: list = []
    max_internal_user_budget = litellm.max_internal_user_budget
    internal_user_budget_duration = litellm.internal_user_budget_duration

    default_ui_key_values: Dict[str, Any] = {
        "duration": "24hr",
        "key_max_budget": litellm.max_ui_session_budget,
        "aliases": {},
        "config": {},
        "spend": 0,
        "team_id": "litellm-dashboard",
    }
    user_defined_values: Optional[SSOUserDefinedValues] = None

    if user_custom_sso is not None:
        if asyncio.iscoroutinefunction(user_custom_sso):
            user_defined_values = await user_custom_sso(result)
        else:
            raise ValueError("user_custom_sso must be a coroutine function")
    elif user_id is not None:
        user_defined_values = SSOUserDefinedValues(
            models=user_id_models,
            user_id=user_id,
            user_email=user_email,
            max_budget=max_internal_user_budget,
            user_role=user_role,
            budget_duration=internal_user_budget_duration,
        )

    # Verify user is in restricted SSO group if configured
    SSOAuthenticationHandler.verify_user_in_restricted_sso_group(
        general_settings=general_settings,
        result=result,
        received_response=None,
    )

    # Get or create user info
    user_info = await get_user_info_from_db(
        result=result,
        prisma_client=prisma_client_instance,
        user_api_key_cache=user_api_key_cache,
        proxy_logging_obj=proxy_logging_obj,
        user_email=user_email,
        user_defined_values=user_defined_values,
        alternate_user_id=user_id,
    )

    user_defined_values = apply_user_info_values_to_sso_user_defined_values(
        user_info=user_info,
        user_defined_values=user_defined_values
    )

    if user_defined_values is None:
        raise Exception(
            "Unable to map user identity to known values. 'user_defined_values' is None."
        )

    verbose_proxy_logger.info(
        f"user_defined_values for creating ui key: {user_defined_values}"
    )

    default_ui_key_values.update(user_defined_values)
    default_ui_key_values["request_type"] = "key"
    response = await generate_key_helper_fn(
        **default_ui_key_values,
        table_name="key",
    )

    key = response["token"]
    user_id = response["user_id"]

    user_role = (
        user_defined_values["user_role"]
        or LitellmUserRoles.INTERNAL_USER_VIEW_ONLY.value
    )
    if user_id and isinstance(user_id, str):
        user_role = await check_and_update_if_proxy_admin_id(
            user_role=user_role,
            user_id=user_id,
            prisma_client=prisma_client_instance
        )

    verbose_proxy_logger.debug(
        f"user_role: {user_role}; ui_access_mode: {ui_access_mode}"
    )

    # Check if role allowed to use proxy
    is_admin_only_access = check_is_admin_only_access(ui_access_mode or {})
    if is_admin_only_access:
        has_access = has_admin_ui_access(user_role or "")
        if not has_access:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": f"User not allowed to access proxy. User role={user_role}, proxy mode={ui_access_mode}"
                },
            )

    disabled_non_admin_personal_key_creation = (
        get_disabled_non_admin_personal_key_creation()
    )

    litellm_dashboard_ui = get_custom_url(
        request_base_url=str(request.base_url),
        route="ui/"
    )

    # Use experimental UI login if enabled
    from litellm.secret_managers.main import get_secret_bool
    if get_secret_bool("EXPERIMENTAL_UI_LOGIN"):
        _user_info: Optional[LiteLLM_UserTable] = None
        if (
            user_defined_values is not None
            and user_defined_values["user_id"] is not None
        ):
            _user_info = LiteLLM_UserTable(
                user_id=user_defined_values["user_id"],
                user_role=user_defined_values["user_role"] or user_role,
                models=[],
                max_budget=litellm.max_ui_session_budget,
            )
        if _user_info is None:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "User Information is required for experimental UI login"
                },
            )

        key = ExperimentalUIJWTToken.get_experimental_ui_login_jwt_auth_token(
            _user_info
        )

    returned_ui_token_object = ReturnedUITokenObject(
        user_id=cast(str, user_id),
        key=key,
        user_email=user_email,
        user_role=user_role or LitellmUserRoles.INTERNAL_USER_VIEW_ONLY.value,
        login_method="sso",
        premium_user=True, # 是否是企业用户，有法律风险
        auth_header_name=general_settings.get(
            "litellm_key_header_name", "Authorization"
        ),
        disabled_non_admin_personal_key_creation=disabled_non_admin_personal_key_creation,
        server_root_path=get_server_root_path(),
    )

    from litellm.proxy.proxy_server import master_key

    jwt_token = jwt.encode(
        cast(dict, returned_ui_token_object),
        master_key or "",
        algorithm="HS256",
    )

    if user_id is not None and isinstance(user_id, str):
        litellm_dashboard_ui += "?login=success"

    verbose_proxy_logger.info(f"Redirecting to {litellm_dashboard_ui}")
    redirect_response = RedirectResponse(url=litellm_dashboard_ui, status_code=303)
    redirect_response.set_cookie(key="token", value=jwt_token)
    return redirect_response
