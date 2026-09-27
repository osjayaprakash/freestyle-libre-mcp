import json

import pytest
from mcp import Client

from librelinkup_mcp import server
from librelinkup_mcp.service import GlucoseService
from tests.factories import ANN, BOB
from tests.fakes import FakeLibreClient

TOOLS = {"list_patients", "get_current_glucose", "get_glucose_graph", "get_glucose_logbook"}


@pytest.fixture
def fake_client():
    client = FakeLibreClient([ANN, BOB])
    server.set_service(GlucoseService(client))
    yield client
    server.set_service(None)


async def call(name, arguments=None):
    async with Client(server.mcp) as client:
        return await client.call_tool(name, arguments or {})


async def test_lists_four_read_only_tools(fake_client):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == TOOLS
    assert all(t.annotations.read_only_hint for t in tools.values())
    assert tools["list_patients"].input_schema.get("properties", {}) == {}
    for name in TOOLS - {"list_patients"}:
        schema = tools[name].input_schema
        assert list(schema["properties"]) == ["patient"]
        assert schema.get("required", []) == []
        assert "list_patients" in schema["properties"]["patient"]["description"]


async def test_list_patients(fake_client):
    result = await call("list_patients")
    assert not result.is_error
    names = [p["first_name"] for p in result.structured_content["patients"]]
    assert names == ["Ann", "Bob"]


async def test_get_current_glucose(fake_client):
    result = await call("get_current_glucose", {"patient": "bob"})
    assert not result.is_error
    body = result.structured_content
    assert body["patient"]["first_name"] == "Bob"
    assert body["reading"]["value"] == 115.0
    assert body["reading"]["trend_arrow"] == "→"
    assert json.loads(result.content[0].text) == body


async def test_get_glucose_graph_sorted(fake_client):
    result = await call("get_glucose_graph", {"patient": "Ann"})
    body = result.structured_content
    assert body["count"] == 2
    assert [r["value"] for r in body["readings"]] == [110.0, 120.0]


async def test_get_glucose_logbook(fake_client):
    result = await call("get_glucose_logbook", {"patient": str(ANN.patient_id)})
    assert result.structured_content["readings"][0]["value"] == 62.0


async def test_tool_error_is_reported_not_raised(fake_client):
    result = await call("get_current_glucose")  # two patients, none chosen
    assert result.is_error
    assert "follows several patients" in result.content[0].text
    assert "Ann Lee" in result.content[0].text


async def test_main_exits_on_missing_credentials(monkeypatch, capsys):
    monkeypatch.delenv("LIBRELINKUP_EMAIL", raising=False)
    monkeypatch.delenv("LIBRELINKUP_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as info:
        server.main()
    assert info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "LIBRELINKUP_EMAIL" in captured.err


def test_build_client_sends_password_verbatim():
    from pylibrelinkup import APIUrl

    from librelinkup_mcp.config import load_settings

    settings = load_settings(
        {
            "LIBRELINKUP_EMAIL": "me@example.com",
            "LIBRELINKUP_PASSWORD": " pass word ",
            "LIBRELINKUP_REGION": "EU",
        }
    )
    client = server.build_client(settings)
    assert client.login_args.model_dump() == {
        "email": "me@example.com",
        "password": " pass word ",
    }
    assert client.api_url == APIUrl.EU.value
