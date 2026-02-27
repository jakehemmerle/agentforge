"""Tests for the OpenEMR OAuth2 client."""

from __future__ import annotations

import time

import pytest

from ai_agent.openemr_client import (
    DEFAULT_SCOPES,
    OpenEMRAuthError,
    OpenEMRClient,
    _TOKEN_REFRESH_MARGIN_SECS,
)

pytestmark = pytest.mark.unit


# -- fixtures -----------------------------------------------------------------

TOKEN_RESPONSE = {
    "access_token": "test-token-abc",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": DEFAULT_SCOPES,
}


@pytest.fixture
def client() -> OpenEMRClient:
    return OpenEMRClient(
        base_url="http://openemr:80",
        client_id="test-client-id",
        client_secret="test-secret",
        username="admin",
        password="pass",
    )


# -- authenticate -------------------------------------------------------------


async def test_authenticate_success(client: OpenEMRClient, httpx_mock):
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )

    await client.authenticate()

    assert client._access_token == "test-token-abc"
    assert client._token_expiry > time.monotonic()

    req = httpx_mock.get_request()
    body = req.content.decode()
    assert "grant_type=password" in body
    assert "client_id=test-client-id" in body
    assert "client_secret=test-secret" in body
    assert "username=admin" in body


async def test_authenticate_failure(client: OpenEMRClient, httpx_mock):
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        status_code=400,
        text="invalid_grant",
    )

    with pytest.raises(OpenEMRAuthError, match="400"):
        await client.authenticate()


async def test_authenticate_no_secret(httpx_mock):
    """Password grant without client_secret (public client)."""
    c = OpenEMRClient(
        base_url="http://openemr:80",
        client_id="pub-id",
        client_secret="",
        username="admin",
        password="pass",
    )
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )

    await c.authenticate()

    req = httpx_mock.get_request()
    body = req.content.decode()
    assert "client_secret" not in body


# -- token validity -----------------------------------------------------------


def test_token_is_valid_when_fresh(client: OpenEMRClient):
    client._access_token = "tok"
    client._token_expiry = time.monotonic() + 3600
    assert client._token_is_valid()


def test_token_is_invalid_when_expired(client: OpenEMRClient):
    client._access_token = "tok"
    client._token_expiry = time.monotonic() - 1
    assert not client._token_is_valid()


def test_token_is_invalid_within_refresh_margin(client: OpenEMRClient):
    client._access_token = "tok"
    client._token_expiry = time.monotonic() + _TOKEN_REFRESH_MARGIN_SECS - 1
    assert not client._token_is_valid()


def test_token_is_invalid_when_none(client: OpenEMRClient):
    assert not client._token_is_valid()


# -- get with auto-auth -------------------------------------------------------


async def test_get_auto_authenticates(client: OpenEMRClient, httpx_mock):
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/patient",
        method="GET",
        json={"data": [{"id": 1}]},
    )

    result = await client.get("/apis/default/api/patient")
    assert result == {"data": [{"id": 1}]}

    requests = httpx_mock.get_requests()
    assert requests[0].url.path == "/oauth2/default/token"
    assert requests[1].url.path == "/apis/default/api/patient"
    assert requests[1].headers["authorization"] == "Bearer test-token-abc"


async def test_get_retries_on_401(client: OpenEMRClient, httpx_mock):
    """On 401, client should re-authenticate then retry the request."""
    # Pre-set a stale token so _ensure_token doesn't call authenticate first
    client._access_token = "stale-token"
    client._token_expiry = time.monotonic() + 3600

    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/patient",
        method="GET",
        status_code=401,
    )
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/patient",
        method="GET",
        json={"data": []},
    )

    result = await client.get("/apis/default/api/patient")
    assert result == {"data": []}

    requests = httpx_mock.get_requests()
    assert len(requests) == 3
    assert requests[0].headers["authorization"] == "Bearer stale-token"
    assert requests[1].url.path == "/oauth2/default/token"
    assert requests[2].headers["authorization"] == "Bearer test-token-abc"


# -- post with auto-auth ------------------------------------------------------


async def test_post_sends_json(client: OpenEMRClient, httpx_mock):
    client._access_token = "tok"
    client._token_expiry = time.monotonic() + 3600

    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/appointment",
        method="POST",
        json={"id": 42},
    )

    result = await client.post("/apis/default/api/appointment", json={"patient_id": 1})
    assert result == {"id": 42}

    req = httpx_mock.get_request()
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["content-type"] == "application/json"


async def test_post_retries_on_401(client: OpenEMRClient, httpx_mock):
    client._access_token = "stale"
    client._token_expiry = time.monotonic() + 3600

    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/encounter",
        method="POST",
        status_code=401,
    )
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/encounter",
        method="POST",
        json={"id": 99},
    )

    result = await client.post("/apis/default/api/encounter", json={"note": "hi"})
    assert result == {"id": 99}


# -- context manager ----------------------------------------------------------


async def test_context_manager(httpx_mock):
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/token",
        method="POST",
        json=TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="http://openemr:80/apis/default/api/patient",
        method="GET",
        json={"data": []},
    )

    async with OpenEMRClient(
        base_url="http://openemr:80",
        client_id="cid",
        client_secret="cs",
    ) as c:
        result = await c.get("/apis/default/api/patient")

    assert result == {"data": []}


# -- register_client ----------------------------------------------------------


async def test_register_client_success(httpx_mock):
    reg_response = {
        "client_id": "new-id",
        "client_secret": "new-secret",
        "registration_access_token": "rat",
    }
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/registration",
        method="POST",
        json=reg_response,
        status_code=201,
    )

    result = await OpenEMRClient.register_client(base_url="http://openemr:80")
    assert result["client_id"] == "new-id"
    assert result["client_secret"] == "new-secret"

    req = httpx_mock.get_request()
    import json

    body = json.loads(req.content)
    assert body["application_type"] == "private"
    assert body["client_name"] == "openemr-ai-agent"


async def test_register_client_failure(httpx_mock):
    httpx_mock.add_response(
        url="http://openemr:80/oauth2/default/registration",
        method="POST",
        status_code=400,
        text="invalid scope",
    )

    with pytest.raises(OpenEMRAuthError, match="registration failed"):
        await OpenEMRClient.register_client(base_url="http://openemr:80")
