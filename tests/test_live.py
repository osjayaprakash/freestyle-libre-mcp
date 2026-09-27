"""Hits the real LibreLinkUp API. Run with: uv run pytest -m live"""

import os

import pytest
from mcp import Client

from librelinkup_mcp import server
from librelinkup_mcp.config import load_settings
from librelinkup_mcp.service import GlucoseService

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("LIBRELINKUP_EMAIL") and os.environ.get("LIBRELINKUP_PASSWORD")),
        reason="needs LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD",
    ),
]


async def test_live_list_patients_and_current_reading():
    settings = load_settings()
    server.set_service(GlucoseService(server.build_client(settings)))
    try:
        async with Client(server.mcp) as mcp_client:
            patients = await mcp_client.call_tool("list_patients", {})
            assert not patients.is_error, patients.content
            first = patients.structured_content["patients"][0]["patient_id"]
            current = await mcp_client.call_tool("get_current_glucose", {"patient": first})
            assert not current.is_error, current.content
            assert current.structured_content["reading"]["value_mg_dl"] > 0
    finally:
        server.set_service(None)
