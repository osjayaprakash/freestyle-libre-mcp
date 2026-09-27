"""GlucoseService: patient lookup, lazy login and error mapping over the LibreLinkUp client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError

from librelinkup_mcp import tracing
from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    GlucoseMeasurement,
    GlucoseMeasurementWithTrend,
    NetworkError,
    Patient,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)

T = TypeVar("T")


class LibreClient(Protocol):
    """The subset of core.client.LibreLinkUpClient that GlucoseService uses."""

    async def authenticate(self) -> None: ...
    async def get_patients(self) -> list[Patient]: ...
    async def latest(self, patient_id: UUID) -> GlucoseMeasurementWithTrend: ...
    async def graph(self, patient_id: UUID) -> list[GlucoseMeasurement]: ...
    async def logbook(self, patient_id: UUID) -> list[GlucoseMeasurement]: ...


class UnknownPatientError(ToolError):
    """No followed patient matches the requested identifier."""


def _describe(patients: list[Patient]) -> str:
    if not patients:
        return "none"
    return ", ".join(f"{p.first_name} {p.last_name} ({p.patient_id})" for p in patients)


def resolve_patient(patients: list[Patient], identifier: str | None) -> Patient:
    """Pick the patient named by `identifier` (UUID or name); None means "the only one"."""
    text = " ".join((identifier or "").split())
    if not text:
        if len(patients) == 1:
            return patients[0]
        if not patients:
            raise ToolError("No patients are followed by this LibreLinkUp account.")
        raise ToolError(
            "This account follows several patients; pass `patient` as one of: "
            + _describe(patients)
        )

    try:
        wanted = UUID(text)
    except ValueError:
        key = text.casefold()
        matches = [p for p in patients if f"{p.first_name} {p.last_name}".casefold() == key]
        if not matches:
            matches = [p for p in patients if p.first_name.casefold() == key]
    else:
        matches = [p for p in patients if wanted in (p.patient_id, p.id)]

    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ToolError(
            f"Patient {text!r} is ambiguous; pass the patient_id of one of: {_describe(matches)}"
        )
    raise UnknownPatientError(
        f"No followed patient matches {text!r}. Followed patients: {_describe(patients)}"
    )


def _to_tool_error(exc: Exception) -> ToolError | None:
    """Translate a LibreLinkUp client error into a user-facing ToolError."""
    if isinstance(exc, AuthenticationError):
        return ToolError(
            "LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD."
        )
    if isinstance(exc, RedirectError):
        return ToolError(
            f"This account belongs to region {exc.region}. Set LIBRELINKUP_REGION={exc.region}."
        )
    if isinstance(exc, TermsOfUseError):
        return ToolError(
            "Open the LibreLinkUp app and accept the updated terms of use, then retry."
        )
    if isinstance(exc, PrivacyPolicyError):
        return ToolError(
            "Open the LibreLinkUp app and accept the updated privacy policy, then retry."
        )
    if isinstance(exc, EmailVerificationError):
        return ToolError("Verify the account email address in the LibreLinkUp app, then retry.")
    if isinstance(exc, RateLimitError):
        wait = f"in {exc.retry_after} seconds" if exc.retry_after is not None else "later"
        return ToolError(f"Rate limited by LibreLinkUp. Try again {wait}.")
    if isinstance(exc, PatientNotFoundError):
        return ToolError("LibreLinkUp reports patient not found.")
    if isinstance(exc, APIError):
        return ToolError(f"LibreLinkUp API error {exc.status}.")
    if isinstance(exc, NetworkError):
        return ToolError(f"Could not reach LibreLinkUp: {exc.kind}.")
    if isinstance(exc, ResponseShapeError):
        return ToolError(f"LibreLinkUp returned unexpected data for {exc.call}.")
    return None


class GlucoseService:
    """Lazy login, re-login on expiry, and patient lookup over a LibreLinkUp client."""

    def __init__(self, client: LibreClient) -> None:
        self._client = client
        self._auth_lock = asyncio.Lock()
        self._patients_lock = asyncio.Lock()
        self._authenticated = False
        self._patients: list[Patient] | None = None

    async def list_patients(self) -> list[Patient]:
        return await self._patient_list(refresh=False)

    async def current(self, patient: str | None) -> tuple[Patient, GlucoseMeasurementWithTrend]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("latest", self._client.latest, resolved)

    async def graph(self, patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("graph", self._client.graph, resolved)

    async def logbook(self, patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("logbook", self._client.logbook, resolved)

    async def _resolve(self, identifier: str | None) -> Patient:
        try:
            return resolve_patient(await self._patient_list(refresh=False), identifier)
        except UnknownPatientError:
            # The account may have started following someone since the list was cached.
            return resolve_patient(await self._patient_list(refresh=True), identifier)

    async def _patient_list(self, *, refresh: bool) -> list[Patient]:
        async with self._patients_lock:
            if self._patients is None or refresh:
                self._patients = await self._request("get_patients", self._client.get_patients)
            return self._patients

    async def _authenticate(self, *, force: bool) -> None:
        async with self._auth_lock:
            if self._authenticated and not force:
                return
            self._authenticated = False
            await self._client.authenticate()
            self._authenticated = True

    async def _request(
        self, method: str, fn: Callable[..., Awaitable[T]], patient: Patient | None = None
    ) -> T:
        args = () if patient is None else (patient.patient_id,)
        metadata = None if patient is None else {"patient_id": str(patient.patient_id)}
        async with tracing.span(f"librelinkup.{method}", metadata):
            try:
                return await self._call_with_reauth(fn, *args)
            except Exception as exc:
                tool_error = _to_tool_error(exc)
                if tool_error is None:
                    raise
                raise tool_error from exc

    async def _call_with_reauth(self, fn: Callable[..., Awaitable[T]], *args: object) -> T:
        await self._authenticate(force=False)
        try:
            return await fn(*args)
        except AuthenticationError:
            pass  # token expired: log in again and retry once
        await self._authenticate(force=True)
        return await fn(*args)
