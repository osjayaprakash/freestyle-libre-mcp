import hashlib
from datetime import UTC, datetime
from uuid import UUID

import httpx2
import pytest

from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    NetworkError,
    PatientNotFoundError,
    RateLimitError,
    ResponseShapeError,
    Trend,
)
from librelinkup_mcp.core.client import LibreLinkUpClient
from tests.core.mock_api import MockAPI, fixture

PATIENT = UUID("22222222-2222-2222-2222-222222222222")
CONNECTIONS = "/llu/connections"
GRAPH = f"/llu/connections/{PATIENT}/graph"
LOGBOOK = f"/llu/connections/{PATIENT}/logbook"


async def logged_in(api: MockAPI) -> LibreLinkUpClient:
    api.on("POST", "/llu/auth/login", json_body=fixture("login_ok"))
    client = LibreLinkUpClient("me@example.com", "pw", transport=api.transport())
    await client.authenticate()
    return client


async def test_data_calls_send_auth_headers():
    api = MockAPI()
    api.on("GET", CONNECTIONS, json_body=fixture("connections"))
    client = await logged_in(api)
    await client.get_patients()
    await client.aclose()

    request = api.requests[-1]
    assert request.headers["authorization"] == "Bearer token-abc"
    assert request.headers["account-id"] == hashlib.sha256(b"follower-user-0001").hexdigest()
    assert request.headers["product"] == "llu.android"


async def test_get_patients():
    api = MockAPI()
    api.on("GET", CONNECTIONS, json_body=fixture("connections"))
    client = await logged_in(api)
    [patient] = await client.get_patients()
    assert patient.patient_id == PATIENT
    assert (patient.first_name, patient.last_name) == ("Ann", "Lee")


async def test_latest_reads_connection_measurement():
    api = MockAPI()
    api.on("GET", GRAPH, json_body=fixture("graph"))
    client = await logged_in(api)
    reading = await client.latest(PATIENT)
    assert reading.value == 115
    assert reading.trend is Trend.STABLE
    assert reading.factory_timestamp == datetime(2026, 9, 26, 13, 5, tzinfo=UTC)
    assert str(api.requests[-1].url) == f"https://api.libreview.io{GRAPH}"


async def test_graph_reads_graph_data():
    api = MockAPI()
    api.on("GET", GRAPH, json_body=fixture("graph"))
    client = await logged_in(api)
    readings = await client.graph(PATIENT)
    assert [r.value for r in readings] == [110, 120]


async def test_logbook():
    api = MockAPI()
    api.on("GET", LOGBOOK, json_body=fixture("logbook"))
    client = await logged_in(api)
    [event] = await client.logbook(PATIENT)
    assert (event.value, event.is_low) == (62, True)


async def test_data_call_before_login_sends_nothing():
    api = MockAPI()
    client = LibreLinkUpClient("me@example.com", "pw", transport=api.transport())
    with pytest.raises(AuthenticationError):
        await client.get_patients()
    assert api.requests == []


async def test_expired_token_401():
    api = MockAPI()
    api.on("GET", CONNECTIONS, status=401, json_body={"message": "expired"})
    client = await logged_in(api)
    with pytest.raises(AuthenticationError):
        await client.get_patients()


async def test_rate_limited_data_call():
    api = MockAPI()
    api.on("GET", GRAPH, status=429, json_body={}, headers={"Retry-After": "12"})
    client = await logged_in(api)
    with pytest.raises(RateLimitError) as info:
        await client.graph(PATIENT)
    assert info.value.retry_after == 12


async def test_server_error_data_call():
    api = MockAPI()
    api.on("GET", LOGBOOK, status=500, text="oops")
    client = await logged_in(api)
    with pytest.raises(APIError) as info:
        await client.logbook(PATIENT)
    assert info.value.status == 500


async def test_timeout_data_call():
    api = MockAPI()
    api.on("GET", CONNECTIONS, raises=httpx2.ReadTimeout("slow"))
    client = await logged_in(api)
    with pytest.raises(NetworkError, match="ReadTimeout"):
        await client.get_patients()


async def test_patient_not_found_body():
    api = MockAPI()
    api.on("GET", GRAPH, json_body=fixture("patient_not_found"))
    client = await logged_in(api)
    with pytest.raises(PatientNotFoundError):
        await client.latest(PATIENT)


async def test_other_nonzero_body_status_is_api_error():
    api = MockAPI()
    api.on("GET", CONNECTIONS, json_body={"status": 911, "error": {"message": "maintenance"}})
    client = await logged_in(api)
    with pytest.raises(APIError) as info:
        await client.get_patients()
    assert info.value.status == 911


@pytest.mark.parametrize(
    "method, path, body, call",
    [
        (
            "get_patients",
            CONNECTIONS,
            {"status": 0, "data": [{"firstName": "Ann"}]},
            "get_patients",
        ),
        ("get_patients", CONNECTIONS, {"status": 0}, "get_patients"),
        ("latest", GRAPH, {"status": 0, "data": {"connection": {}}}, "latest"),
        ("graph", GRAPH, {"status": 0, "data": {}}, "graph"),
        ("logbook", LOGBOOK, {"status": 0, "data": [{"Value": 1}]}, "logbook"),
    ],
)
async def test_unexpected_shapes_name_the_call(method, path, body, call):
    api = MockAPI()
    api.on("GET", path, json_body=body)
    client = await logged_in(api)
    args = () if method == "get_patients" else (PATIENT,)
    with pytest.raises(ResponseShapeError) as info:
        await getattr(client, method)(*args)
    assert info.value.call == call
