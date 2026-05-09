import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request
from fastapi.responses import RedirectResponse

from litellm.proxy.auth.auth_utils import _has_user_setup_sso
from litellm.proxy.auth.handle_jwt import JWTHandler
from litellm.proxy.management_endpoints.types import CustomOpenID
from litellm.proxy.management_endpoints.ui_sso import google_login
from litellm.proxy.management_endpoints.ui_sourceid_sso import (
    SOURCEID_OAUTH_STATE_COOKIE_NAME,
    SourceIDSSOHandler,
    sourceid_callback,
    sourceid_login,
)


def _make_request(
    path: str,
    query_string: bytes = b"",
    cookie_header: bytes = b"",
    scheme: str = "https",
) -> Request:
    headers = []
    if cookie_header:
        headers.append((b"cookie", cookie_header))

    scope = {
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "path": path,
        "query_string": query_string,
        "headers": headers,
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope)


def test_sourceid_sso_handler_get_authorization_url_should_include_required_params():
    with patch.dict(
        os.environ,
        {
            "SOURCEID_CLIENT_ID": "sourceid-client",
            "SOURCEID_SCOPE": "openid profile email",
            "SOURCEID_AUTHORIZATION_ENDPOINT": "https://id.example.com/oauth2/authorize",
        },
        clear=False,
    ):
        auth_url = SourceIDSSOHandler.get_authorization_url(
            redirect_uri="https://proxy.example.com/sso/sourceid/callback",
            state="state-123",
        )

    assert "client_id=sourceid-client" in auth_url
    assert "response_type=code" in auth_url
    assert "state=state-123" in auth_url
    assert "redirect_uri=https%3A%2F%2Fproxy.example.com%2Fsso%2Fsourceid%2Fcallback" in auth_url
    assert "scope=openid+profile+email" in auth_url


def test_sourceid_sso_handler_openid_from_response_should_map_nested_attributes():
    jwt_handler = MagicMock(spec=JWTHandler)
    jwt_handler.get_team_ids_from_jwt.side_effect = lambda payload: payload.get(
        "groups", []
    )

    sso_jwt_handler = MagicMock(spec=JWTHandler)
    sso_jwt_handler.get_team_ids_from_jwt.side_effect = lambda payload: payload.get(
        "sso_groups", []
    )

    response = {
        "id": "user-123",
        "attributes": {
            "RJEMAIL": "User@Example.com",
            "RJXM": "SourceID User",
            "XM": "SourceID",
            "role": "proxy_admin",
        },
        "groups": ["team-userinfo"],
    }
    access_token_payload = {
        "groups": ["team-token"],
        "sso_groups": ["restricted-team"],
    }

    with patch.dict(
        os.environ,
        {"SOURCEID_USER_ROLE_ATTRIBUTE": "attributes.role"},
        clear=False,
    ):
        result = SourceIDSSOHandler.openid_from_response(
            response=response,
            jwt_handler=jwt_handler,
            sso_jwt_handler=sso_jwt_handler,
            access_token_payload=access_token_payload,
        )

    assert isinstance(result, CustomOpenID)
    assert result.provider == "sourceid"
    assert result.id == "user-123"
    assert result.email == "user@example.com"
    assert result.display_name == "SourceID User"
    assert result.first_name == "SourceID"
    assert result.last_name == "SourceID"
    assert result.team_ids == ["restricted-team", "team-token", "team-userinfo"]
    assert result.user_role is not None
    assert result.user_role.value == "proxy_admin"


def test_sourceid_login_should_redirect_and_set_state_cookie():
    request = _make_request(path="/sso/sourceid/login")

    with (
        patch.dict(os.environ, {"SOURCEID_CLIENT_ID": "sourceid-client"}, clear=False),
        patch(
            "litellm.proxy.management_endpoints.ui_sourceid_sso.show_missing_vars_in_env",
            return_value=None,
        ),
        patch(
            "litellm.proxy.management_endpoints.ui_sourceid_sso.SSOAuthenticationHandler.get_redirect_url_for_sso",
            return_value="https://proxy.example.com/sso/sourceid/callback",
        ),
    ):
        response = asyncio.run(sourceid_login(request))

    assert response.status_code == 302
    location = response.headers["location"]
    set_cookie = response.headers["set-cookie"]
    assert "/oauth2.0/authorize" in location
    assert "state=" in location
    assert SOURCEID_OAUTH_STATE_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie


def test_sourceid_login_should_store_return_to_cookie_when_valid():
    request = _make_request(
        path="/sso/sourceid/login",
        query_string=b"return_to=https%3A%2F%2Fproxy.example.com%2Fui%2Flogin",
    )

    with (
        patch.dict(os.environ, {"SOURCEID_CLIENT_ID": "sourceid-client"}, clear=False),
        patch(
            "litellm.proxy.management_endpoints.ui_sourceid_sso.show_missing_vars_in_env",
            return_value=None,
        ),
        patch(
            "litellm.proxy.management_endpoints.ui_sourceid_sso.SSOAuthenticationHandler.get_redirect_url_for_sso",
            return_value="https://proxy.example.com/sso/sourceid/callback",
        ),
        patch(
            "litellm.proxy.management_endpoints.ui_sourceid_sso.SSOAuthenticationHandler._validate_return_to",
            return_value=True,
        ),
    ):
        response = asyncio.run(sourceid_login(request))

    assert response.status_code == 302
    set_cookie_headers = [
        header_value.decode("latin-1")
        for header_name, header_value in response.raw_headers
        if header_name == b"set-cookie"
    ]
    assert any(
        'litellm_cp_return_to="https://proxy.example.com/ui/login"' in header
        for header in set_cookie_headers
    )


def test_sourceid_should_mark_sso_as_configured():
    with patch.dict(os.environ, {"SOURCEID_CLIENT_ID": "sourceid-client"}, clear=False):
        assert _has_user_setup_sso() is True


def test_sso_generate_should_redirect_to_sourceid_login_for_ui_flow():
    import litellm.proxy.proxy_server as proxy_server

    request = _make_request(path="/sso/key/generate")
    original_premium_user = getattr(proxy_server, "premium_user", None)
    original_prisma_client = getattr(proxy_server, "prisma_client", None)
    original_user_api_key_cache = getattr(proxy_server, "user_api_key_cache", None)
    original_user_custom_ui_sso_sign_in_handler = getattr(
        proxy_server, "user_custom_ui_sso_sign_in_handler", None
    )

    proxy_server.premium_user = True
    proxy_server.prisma_client = None
    proxy_server.user_api_key_cache = MagicMock()
    proxy_server.user_custom_ui_sso_sign_in_handler = None

    try:
        with (
            patch.dict(os.environ, {"SOURCEID_CLIENT_ID": "sourceid-client"}, clear=False),
            patch(
                "litellm.proxy.management_endpoints.ui_sso.show_missing_vars_in_env",
                return_value=None,
            ),
            patch(
                "litellm.proxy.management_endpoints.ui_sso.SSOAuthenticationHandler._validate_return_to",
                return_value=True,
            ),
        ):
            response = asyncio.run(
                google_login(
                    request=request,
                    return_to="https://proxy.example.com/ui/login",
                )
            )
    finally:
        proxy_server.premium_user = original_premium_user
        proxy_server.prisma_client = original_prisma_client
        proxy_server.user_api_key_cache = original_user_api_key_cache
        proxy_server.user_custom_ui_sso_sign_in_handler = (
            original_user_custom_ui_sso_sign_in_handler
        )

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "/sso/sourceid/login?return_to=https%3A%2F%2Fproxy.example.com%2Fui%2Flogin"
    )


def test_sourceid_callback_should_exchange_code_and_delegate_to_common_sso_handler():
    import litellm.proxy.proxy_server as proxy_server

    encoded_access_token = (
        "eyJhbGciOiJub25lIn0."
        "eyJncm91cHMiOlsidGVhbS10b2tlbiJdLCJzc29fZ3JvdXBzIjpbInJlc3RyaWN0ZWQtdGVhbSJdfQ."
    )
    request = _make_request(
        path="/sso/sourceid/callback",
        query_string=b"code=test-code&state=state-123",
        cookie_header=b"litellm_sourceid_oauth_state=state-123",
    )

    original_prisma_client = getattr(proxy_server, "prisma_client", None)
    original_master_key = getattr(proxy_server, "master_key", None)
    original_general_settings = getattr(proxy_server, "general_settings", None)
    original_jwt_handler = getattr(proxy_server, "jwt_handler", None)
    original_user_api_key_cache = getattr(proxy_server, "user_api_key_cache", None)

    proxy_server.prisma_client = object()
    proxy_server.master_key = "sk-test"
    proxy_server.general_settings = {}
    proxy_server.jwt_handler = MagicMock(spec=JWTHandler)
    proxy_server.jwt_handler.get_team_ids_from_jwt.side_effect = lambda payload: payload.get(
        "groups", []
    )
    proxy_server.user_api_key_cache = MagicMock()

    delegated_response = RedirectResponse(
        url="https://proxy.example.com/ui/?login=success",
        status_code=303,
    )

    try:
        with (
            patch(
                "litellm.proxy.management_endpoints.ui_sourceid_sso.SourceIDSSOHandler.exchange_code_for_token",
                new=AsyncMock(return_value={"access_token": encoded_access_token}),
            ),
            patch(
                "litellm.proxy.management_endpoints.ui_sourceid_sso.SourceIDSSOHandler.get_user_info",
                new=AsyncMock(
                    return_value={
                        "id": "user-123",
                        "attributes": {
                            "RJEMAIL": "user@example.com",
                            "RJXM": "SourceID User",
                            "XM": "SourceID",
                        },
                        "groups": ["team-userinfo"],
                    }
                ),
            ),
            patch(
                "litellm.proxy.management_endpoints.ui_sourceid_sso.SSOAuthenticationHandler.get_redirect_response_from_openid",
                new=AsyncMock(return_value=delegated_response),
            ) as mock_redirect,
        ):
            response = asyncio.run(
                sourceid_callback(
                    request=request,
                    code="test-code",
                    state="state-123",
                )
            )
    finally:
        proxy_server.prisma_client = original_prisma_client
        proxy_server.master_key = original_master_key
        proxy_server.general_settings = original_general_settings
        proxy_server.jwt_handler = original_jwt_handler
        proxy_server.user_api_key_cache = original_user_api_key_cache

    assert response.status_code == 303
    assert response.headers["location"] == "https://proxy.example.com/ui/?login=success"
    assert mock_redirect.await_count == 1
    redirect_kwargs = mock_redirect.await_args.kwargs
    assert redirect_kwargs["result"].provider == "sourceid"
    assert redirect_kwargs["access_token_payload"] == {
        "groups": ["team-token"],
        "sso_groups": ["restricted-team"],
    }