"""MCP server exposing LibreLinkUp glucose readings as read-only tools."""

from __future__ import annotations

import atexit
import logging
import sys
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.models.login import LoginArgs

from librelinkup_mcp import formatting, tracing
from librelinkup_mcp.config import ConfigError, Settings, load_settings
from librelinkup_mcp.service import GlucoseService

mcp = MCPServer(
    "librelinkup",
    instructions=(
        "Read-only access to FreeStyle Libre CGM glucose readings shared through LibreLinkUp. "
        "Values are reported in the account's unit (mg/dL or mmol/L) and also in mg/dL. "
        "Timestamps are the sensor's local time."
    ),
)

_READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

PatientArg = Annotated[
    str | None,
    Field(
        description=(
            "Name (e.g. 'Ann Lee' or 'Ann') or patient_id from list_patients. "
            "Omit when the account follows exactly one person."
        )
    ),
]

_service: GlucoseService | None = None


def set_service(service: GlucoseService | None) -> None:
    global _service
    _service = service


def _get_service() -> GlucoseService:
    if _service is None:
        raise RuntimeError("GlucoseService is not configured; call main() or set_service().")
    return _service


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("list_patients")
async def list_patients() -> dict[str, Any]:
    """List the people this LibreLinkUp account follows."""
    patients = await _get_service().list_patients()
    return {"patients": [formatting.patient_to_dict(p) for p in patients]}


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_current_glucose")
async def get_current_glucose(patient: PatientArg = None) -> dict[str, Any]:
    """Most recent glucose reading with its trend arrow."""
    resolved, reading = await _get_service().current(patient)
    return formatting.current_response(resolved, reading)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_glucose_graph")
async def get_glucose_graph(patient: PatientArg = None) -> dict[str, Any]:
    """Glucose readings from roughly the last 12 hours (about every 15 minutes), oldest first."""
    resolved, readings = await _get_service().graph(patient)
    return formatting.readings_response(resolved, readings)


@mcp.tool(annotations=_READ_ONLY)
@tracing.traced("get_glucose_logbook")
async def get_glucose_logbook(patient: PatientArg = None) -> dict[str, Any]:
    """Logged glucose events (scans, alarms) from roughly the last 2 weeks, oldest first."""
    resolved, readings = await _get_service().logbook(patient)
    return formatting.readings_response(resolved, readings)


def build_client(settings: Settings) -> PyLibreLinkUp:
    client = PyLibreLinkUp(
        email=settings.email, password=settings.password, api_url=settings.region
    )
    # pylibrelinkup's LoginArgs strips whitespace; passwords must be sent verbatim.
    client.login_args = LoginArgs.model_construct(email=settings.email, password=settings.password)
    return client


def main() -> None:
    # stdout carries the MCP protocol; every log line must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"librelinkup-mcp: {exc}", file=sys.stderr)
        sys.exit(1)

    tracing.configure(settings)
    atexit.register(tracing.shutdown)
    set_service(GlucoseService(build_client(settings)))
    mcp.run("stdio")
