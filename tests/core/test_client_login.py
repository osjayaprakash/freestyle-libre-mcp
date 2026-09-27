import json

import httpx2
import pytest

from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    Region,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.client import PRODUCT, VERSION, LibreLinkUpClient
from tests.core.mock_api import MockAPI, fixture

LOGIN = "/llu/auth/login"


def make_client(api: MockAPI, *, password: str = "pw", region: Region = Region.US):
    return LibreLinkUpClient("me@example.com", password, region, transport=api.transport())


async def test_login_posts_verbatim_credentials_with_app_headers():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_ok"))
    async with make_client(api, password=" pass word ", region=Region.EU2) as client:
        await client.authenticate()

    [request] = api.requests
    assert str(request.url) == "https://api-eu2.libreview.io/llu/auth/login"
    assert json.loads(request.content) == {"email": "me@example.com", "password": " pass word "}
    assert request.headers["product"] == PRODUCT == "llu.android"
    assert request.headers["version"] == VERSION
    assert "authorization" not in request.headers


async def test_redirect_carries_upper_cased_region():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_redirect"))
    async with make_client(api) as client:
        with pytest.raises(RedirectError) as info:
            await client.authenticate()
    assert info.value.region == "EU2"


@pytest.mark.parametrize(
    "name, error",
    [
        ("login_terms", TermsOfUseError),
        ("login_privacy", PrivacyPolicyError),
        ("login_verify_email", EmailVerificationError),
    ],
)
async def test_login_steps_raise_specific_errors(name, error):
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture(name))
    async with make_client(api) as client:
        with pytest.raises(error):
            await client.authenticate()


async def test_bad_credentials_body_status():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_bad_credentials"))
    async with make_client(api) as client:
        with pytest.raises(AuthenticationError):
            await client.authenticate()


async def test_http_401_on_login():
    api = MockAPI()
    api.on("POST", LOGIN, status=401, json_body={"error": "Unauthorized"})
    async with make_client(api) as client:
        with pytest.raises(AuthenticationError):
            await client.authenticate()


@pytest.mark.parametrize("header, expected", [({"Retry-After": "30"}, 30), ({}, None)])
async def test_rate_limit_on_login(header, expected):
    api = MockAPI()
    api.on("POST", LOGIN, status=429, json_body={}, headers=header)
    async with make_client(api) as client:
        with pytest.raises(RateLimitError) as info:
            await client.authenticate()
    assert info.value.retry_after == expected


async def test_server_error_on_login():
    api = MockAPI()
    api.on("POST", LOGIN, status=503, text="unavailable")
    async with make_client(api) as client:
        with pytest.raises(APIError) as info:
            await client.authenticate()
    assert info.value.status == 503


@pytest.mark.parametrize(
    "exc, kind",
    [
        (httpx2.ConnectError("dns"), "ConnectError"),
        (httpx2.ReadTimeout("slow"), "ReadTimeout"),
    ],
)
async def test_network_errors_on_login(exc, kind):
    api = MockAPI()
    api.on("POST", LOGIN, raises=exc)
    async with make_client(api) as client:
        with pytest.raises(NetworkError) as info:
            await client.authenticate()
    assert info.value.kind == kind


@pytest.mark.parametrize(
    "body",
    [
        {"status": 0, "data": {"user": {"id": "u"}}},
        {"status": 0, "data": {"authTicket": {"token": "t"}}},
        {"status": 0},
        ["not", "an", "object"],
    ],
)
async def test_login_payload_missing_token_or_user(body):
    api = MockAPI()
    api.on("POST", LOGIN, json_body=body)
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError) as info:
            await client.authenticate()
    assert info.value.call == "authenticate"


async def test_login_non_json_body():
    api = MockAPI()
    api.on("POST", LOGIN, text="<html>maintenance</html>")
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError):
            await client.authenticate()


async def test_aclose_closes_http_client():
    client = make_client(MockAPI())
    await client.aclose()
    assert client._http.is_closed
