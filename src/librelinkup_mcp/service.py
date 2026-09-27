"""GlucoseService: the only module that talks to pylibrelinkup."""

from __future__ import annotations

from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from pylibrelinkup.models.data import Patient


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
