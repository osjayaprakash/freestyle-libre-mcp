"""Async client for the LibreLinkUp follower API (login, connections, graph, logbook)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

import httpx2
from pydantic import TypeAdapter, ValidationError

from librelinkup_mcp.core.exceptions import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.models import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient
from librelinkup_mcp.core.regions import Region

# The API only answers requests that look like the official app. Bump VERSION
# when Abbott starts rejecting the current one.
PRODUCT = "llu.android"
VERSION = "4.16.0"

_BASE_HEADERS = {
    "accept-encoding": "gzip",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "product": PRODUCT,
    "version": VERSION,
}

_STEP_ERRORS: dict[str, type[Exception]] = {
    "tou": TermsOfUseError,
    "pp": PrivacyPolicyError,
    "verifyEmail": EmailVerificationError,
}

_PATIENTS = TypeAdapter(list[Patient])
_MEASUREMENTS = TypeAdapter(list[GlucoseMeasurement])

T = TypeVar("T")


class LibreLinkUpClient:
    def __init__(
        self,
        email: str,
        password: str,
        region: Region = Region.US,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.region = region
        self._email = email
        self._password = password
        self._auth_headers: dict[str, str] | None = None
        self._http = httpx2.AsyncClient(
            base_url=region.value, headers=_BASE_HEADERS, transport=transport, timeout=timeout
        )

    async def __aenter__(self) -> LibreLinkUpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def authenticate(self) -> None:
        response = await self._send(
            "POST", "/llu/auth/login", json={"email": self._email, "password": self._password}
        )
        body = _json_object(response, "authenticate")
        data = body.get("data")
        if not isinstance(data, dict):
            data = {}

        if data.get("redirect"):
            raise RedirectError(str(data.get("region", "")).upper())
        step = data.get("step")
        step_type = step.get("type") if isinstance(step, dict) else None
        if step_type in _STEP_ERRORS:
            raise _STEP_ERRORS[step_type]()
        if body.get("status", 0) != 0:
            raise AuthenticationError("LibreLinkUp rejected the credentials")

        try:
            token = data["authTicket"]["token"]
            user_id = data["user"]["id"]
        except (KeyError, TypeError):
            raise ResponseShapeError("authenticate") from None
        if not token or not user_id:
            raise ResponseShapeError("authenticate")
        self._auth_headers = {
            "authorization": f"Bearer {token}",
            "account-id": hashlib.sha256(str(user_id).encode()).hexdigest(),
        }

    async def get_patients(self) -> list[Patient]:
        data = await self._get_data("/llu/connections", "get_patients")
        return _parse("get_patients", lambda: _PATIENTS.validate_python(data))

    async def latest(self, patient_id: UUID) -> GlucoseMeasurementWithTrend:
        data = await self._get_data(f"/llu/connections/{patient_id}/graph", "latest")
        return _parse(
            "latest",
            lambda: GlucoseMeasurementWithTrend.model_validate(
                data["connection"]["glucoseMeasurement"]
            ),
        )

    async def graph(self, patient_id: UUID) -> list[GlucoseMeasurement]:
        data = await self._get_data(f"/llu/connections/{patient_id}/graph", "graph")
        return _parse("graph", lambda: _MEASUREMENTS.validate_python(data["graphData"]))

    async def logbook(self, patient_id: UUID) -> list[GlucoseMeasurement]:
        data = await self._get_data(f"/llu/connections/{patient_id}/logbook", "logbook")
        return _parse("logbook", lambda: _MEASUREMENTS.validate_python(data))

    async def _get_data(self, path: str, call: str) -> Any:
        if self._auth_headers is None:
            raise AuthenticationError("Not logged in")
        response = await self._send("GET", path, headers=self._auth_headers)
        body = _json_object(response, call)
        status = body.get("status", 0)
        if status != 0:
            error = body.get("error")
            if isinstance(error, dict) and error.get("message") == "couldNotLoadPatient":
                raise PatientNotFoundError()
            raise APIError(status if isinstance(status, int) else 0)
        return body.get("data")

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        try:
            response = await self._http.request(method, path, json=json, headers=headers)
        except httpx2.TransportError as exc:
            raise NetworkError(type(exc).__name__) from exc
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise RateLimitError(int(retry_after) if retry_after.isdigit() else None)
        if response.status_code == 401:
            raise AuthenticationError("LibreLinkUp returned HTTP 401")
        if not response.is_success:
            raise APIError(response.status_code)
        return response


def _json_object(response: httpx2.Response, call: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ResponseShapeError(call) from None
    if not isinstance(body, dict):
        raise ResponseShapeError(call)
    return body


def _parse(call: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except (ValidationError, KeyError, TypeError):
        raise ResponseShapeError(call) from None
