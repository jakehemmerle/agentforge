"""Async OAuth2 client for the OpenEMR REST API."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = (
    "openid api:oemr "
    "user/appointment.read "
    "user/encounter.read "
    "user/patient.read "
    "user/insurance.read "
    "user/vital.read "
    "user/soap_note.read "
    "user/AllergyIntolerance.read "
    "user/Condition.read "
    "user/MedicationRequest.read"
)

# Re-authenticate when token has less than this many seconds remaining.
_TOKEN_REFRESH_MARGIN_SECS = 60


class OpenEMRAuthError(Exception):
    """Raised when authentication with OpenEMR fails."""


class OpenEMRClient:
    """Async HTTP client that handles OAuth2 password-grant auth with OpenEMR.

    Usage::

        async with OpenEMRClient(base_url, client_id, client_secret) as client:
            patients = await client.get("/apis/default/api/patient")
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str = "",
        username: str = "admin",
        password: str = "pass",
        scopes: str = DEFAULT_SCOPES,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.scopes = scopes

        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    @classmethod
    def from_settings(cls) -> OpenEMRClient:
        """Construct an OpenEMRClient from application settings."""
        from ai_agent.config import get_settings

        settings = get_settings()
        return cls(
            base_url=settings.openemr_base_url,
            client_id=settings.openemr_client_id,
            client_secret=settings.openemr_client_secret,
            username=settings.openemr_username,
            password=settings.openemr_password,
        )

    # -- context manager -------------------------------------------------------

    async def __aenter__(self) -> OpenEMRClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # -- authentication --------------------------------------------------------

    async def authenticate(self) -> None:
        """Acquire an access token using the OAuth2 password grant."""
        data: dict[str, str] = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "client_id": self.client_id,
            "scope": self.scopes,
            "user_role": "users",
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        logger.debug("POST %s/oauth2/default/token (password grant)", self.base_url)

        resp = await self._http.post("/oauth2/default/token", data=data)

        if resp.status_code != 200:
            body = resp.text
            logger.error(
                "OAuth2 token request failed (%s): %s", resp.status_code, body
            )
            raise OpenEMRAuthError(
                f"Token request failed ({resp.status_code}): {body}"
            )

        payload = resp.json()
        self._access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expiry = time.monotonic() + expires_in
        logger.info(
            "Authenticated with OpenEMR (token expires in %ds)", expires_in
        )

    def _token_is_valid(self) -> bool:
        return (
            self._access_token is not None
            and time.monotonic() < self._token_expiry - _TOKEN_REFRESH_MARGIN_SECS
        )

    async def _ensure_token(self) -> None:
        if not self._token_is_valid():
            await self.authenticate()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    # -- HTTP helpers ----------------------------------------------------------

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send an authenticated GET request. Retries once on 401."""
        await self._ensure_token()

        logger.debug("GET %s%s", self.base_url, path)
        resp = await self._http.get(path, params=params, headers=self._auth_headers())

        if resp.status_code == 401:
            logger.warning("Got 401, re-authenticating and retrying GET %s", path)
            await self.authenticate()
            resp = await self._http.get(
                path, params=params, headers=self._auth_headers()
            )

        resp.raise_for_status()
        return resp.json()

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send an authenticated POST request. Retries once on 401."""
        await self._ensure_token()

        logger.debug("POST %s%s", self.base_url, path)
        resp = await self._http.post(path, json=json, headers=self._auth_headers())

        if resp.status_code == 401:
            logger.warning("Got 401, re-authenticating and retrying POST %s", path)
            await self.authenticate()
            resp = await self._http.post(
                path, json=json, headers=self._auth_headers()
            )

        resp.raise_for_status()
        return resp.json()

    # -- client registration (optional first-run) ------------------------------

    @staticmethod
    async def register_client(
        base_url: str,
        client_name: str = "openemr-ai-agent",
        redirect_uris: list[str] | None = None,
        scopes: str = DEFAULT_SCOPES,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Register a new OAuth2 client with OpenEMR.

        Returns the registration response containing client_id and
        client_secret (for confidential/private apps).
        """
        payload: dict[str, Any] = {
            "application_type": "private",
            "client_name": client_name,
            "redirect_uris": redirect_uris or ["https://localhost"],
            "scope": scopes,
        }

        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout
        ) as http:
            logger.debug("POST %s/oauth2/default/registration", base_url)
            resp = await http.post("/oauth2/default/registration", json=payload)

        if resp.status_code not in (200, 201):
            body = resp.text
            logger.error(
                "Client registration failed (%s): %s", resp.status_code, body
            )
            raise OpenEMRAuthError(
                f"Client registration failed ({resp.status_code}): {body}"
            )

        result = resp.json()
        logger.info(
            "Registered OAuth2 client %s (client_id=%s)",
            client_name,
            result.get("client_id"),
        )
        return result
