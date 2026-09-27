import asyncio

import pydantic
import pytest
import requests
from mcp.server.mcpserver.exceptions import ToolError
from pylibrelinkup import (
    APIUrl,
    AuthenticationError,
    EmailVerificationError,
    LLUAPIError,
    LLUAPIRateLimitError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RedirectError,
    TermsOfUseError,
)
from pylibrelinkup.models.data import GlucoseMeasurementWithTrend

from librelinkup_mcp.service import GlucoseService
from tests.factories import ANN, BOB
from tests.fakes import FakeLibreClient, http_error


async def test_lazy_login_happens_once_across_calls():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    assert client.calls == []

    await service.list_patients()
    await service.current(None)
    await service.graph(None)

    assert client.count("authenticate") == 1
    assert client.calls[0] == ("authenticate", None)


async def test_concurrent_first_calls_share_one_login():
    client = FakeLibreClient([ANN], auth_delay=0.05)
    service = GlucoseService(client)

    await asyncio.gather(service.current(None), service.graph(None), service.logbook(None))

    assert client.count("authenticate") == 1
    assert client.count("get_patients") == 1


async def test_patient_list_is_cached():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.current(None)
    await service.graph("Ann")
    assert client.count("get_patients") == 1


async def test_data_calls_use_patient_id():
    client = FakeLibreClient([ANN, BOB])
    service = GlucoseService(client)

    patient, reading = await service.current("Bob")
    assert patient is BOB
    assert reading.value == 115
    assert ("latest", BOB.patient_id) in client.calls

    patient, readings = await service.graph("Ann")
    assert patient is ANN and len(readings) == 2
    patient, readings = await service.logbook("Ann")
    assert patient is ANN and readings[0].value == 62


async def test_unknown_patient_refreshes_list_once():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.list_patients()

    client.patients.append(BOB)  # account starts following Bob
    patient, _ = await service.current("Bob")

    assert patient is BOB
    assert client.count("get_patients") == 2


async def test_unknown_patient_after_refresh_errors():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    with pytest.raises(ToolError, match="No followed patient matches 'Zed'"):
        await service.current("Zed")
    assert client.count("get_patients") == 2


@pytest.mark.parametrize(
    "expired", [AuthenticationError("PyLibreLinkUp not authenticated"), http_error(401)]
)
async def test_expired_session_reauthenticates_and_retries(expired):
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.list_patients()

    client.fail_next["graph"] = [expired]
    _, readings = await service.graph(None)

    assert len(readings) == 2
    assert client.count("authenticate") == 2
    assert client.count("graph") == 2


async def test_second_auth_failure_is_surfaced():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.list_patients()

    client.fail_next["graph"] = [http_error(401), http_error(401)]
    with pytest.raises(ToolError, match="LibreLinkUp API error 401"):
        await service.graph(None)
    assert client.count("authenticate") == 2


async def test_bad_credentials_message_and_later_retry_logs_in_again():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    client.fail_next["authenticate"] = [AuthenticationError("Invalid login credentials")]

    with pytest.raises(ToolError, match="Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD"):
        await service.list_patients()

    await service.list_patients()  # credentials fixed / transient failure gone
    assert client.count("authenticate") == 2


@pytest.mark.parametrize(
    "error, message",
    [
        (RedirectError(APIUrl.EU), "belongs to region EU. Set LIBRELINKUP_REGION=EU."),
        (TermsOfUseError(), "accept the updated terms of use"),
        (PrivacyPolicyError(), "accept the updated privacy policy"),
        (EmailVerificationError(), "Verify the account email address"),
    ],
)
async def test_login_errors_are_mapped(error, message):
    client = FakeLibreClient([ANN])
    client.fail_next["authenticate"] = [error]
    with pytest.raises(ToolError, match=message):
        await GlucoseService(client).list_patients()


@pytest.mark.parametrize(
    "error, message",
    [
        (LLUAPIRateLimitError(429, "slow down", retry_after=30), "Try again in 30 seconds."),
        (LLUAPIRateLimitError(429, "slow down"), "Try again later."),
        (PatientNotFoundError(), "LibreLinkUp reports patient not found."),
        (LLUAPIError(500, "boom"), "LibreLinkUp API error 500."),
        (http_error(503), "LibreLinkUp API error 503."),
        (requests.ConnectionError("dns"), "Could not reach LibreLinkUp: ConnectionError."),
        (requests.Timeout("slow"), "Could not reach LibreLinkUp: Timeout."),
    ],
)
async def test_data_call_errors_are_mapped(error, message):
    client = FakeLibreClient([ANN])
    client.fail_next["latest"] = [error]
    with pytest.raises(ToolError) as info:
        await GlucoseService(client).current(None)
    assert str(info.value).endswith(message)
    assert info.value.__cause__ is error


async def test_unexpected_errors_propagate_unchanged():
    client = FakeLibreClient([ANN])
    client.fail_next["latest"] = [KeyError("data")]
    with pytest.raises(KeyError):
        await GlucoseService(client).current(None)


async def test_expired_session_on_patient_list_reauthenticates():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.current(None)  # logged in, patients cached

    client.patients.append(BOB)
    client.fail_next["get_patients"] = [http_error(401)]
    patient, _ = await service.current("Bob")  # cache miss -> refresh -> 401 -> re-auth

    assert patient is BOB
    assert client.count("authenticate") == 2


def _validation_error() -> pydantic.ValidationError:
    try:
        GlucoseMeasurementWithTrend.model_validate({})
    except pydantic.ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


async def test_unexpected_payload_shape_is_a_clean_tool_error():
    client = FakeLibreClient([ANN])
    client.fail_next["latest"] = [_validation_error()]
    with pytest.raises(ToolError, match="no active sensor"):
        await GlucoseService(client).current(None)
