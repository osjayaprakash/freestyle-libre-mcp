import pytest
from mcp.server.mcpserver.exceptions import ToolError

from librelinkup_mcp.service import UnknownPatientError, resolve_patient
from tests.factories import ANN, ANN_SMITH, BOB


@pytest.mark.parametrize("identifier", [None, "", "   "])
def test_blank_identifier_picks_only_patient(identifier):
    assert resolve_patient([ANN], identifier) is ANN


def test_blank_identifier_with_no_patients():
    with pytest.raises(ToolError, match="No patients are followed"):
        resolve_patient([], None)


def test_blank_identifier_with_several_patients_lists_them():
    with pytest.raises(ToolError) as info:
        resolve_patient([ANN, BOB], None)
    assert not isinstance(info.value, UnknownPatientError)
    assert "Ann Lee (22222222-2222-2222-2222-222222222222)" in str(info.value)
    assert "Bob Lee" in str(info.value)


def test_patient_id_uuid():
    assert resolve_patient([ANN, BOB], "44444444-4444-4444-4444-444444444444") is BOB


def test_connection_id_uuid():
    assert resolve_patient([ANN, BOB], "11111111-1111-1111-1111-111111111111") is ANN


def test_uppercase_uuid():
    assert resolve_patient([ANN, BOB], "44444444-4444-4444-4444-444444444444".upper()) is BOB


@pytest.mark.parametrize("identifier", ["ann lee", "ANN LEE", "  Ann   Lee "])
def test_full_name_is_case_and_whitespace_insensitive(identifier):
    assert resolve_patient([ANN, BOB, ANN_SMITH], identifier) is ANN


def test_first_name_when_unique():
    assert resolve_patient([ANN, BOB], "bob") is BOB


def test_full_name_wins_over_ambiguous_first_name():
    assert resolve_patient([ANN, ANN_SMITH], "Ann Smith") is ANN_SMITH


def test_ambiguous_first_name_lists_candidates():
    with pytest.raises(ToolError, match="ambiguous") as info:
        resolve_patient([ANN, ANN_SMITH, BOB], "ann")
    assert not isinstance(info.value, UnknownPatientError)
    assert "Ann Lee" in str(info.value) and "Ann Smith" in str(info.value)
    assert "Bob" not in str(info.value)


def test_unknown_name_is_unknown_patient_error_listing_followed():
    with pytest.raises(UnknownPatientError, match="'Zed'") as info:
        resolve_patient([ANN], "Zed")
    assert "Ann Lee" in str(info.value)


def test_unknown_uuid():
    with pytest.raises(UnknownPatientError):
        resolve_patient([ANN], "99999999-9999-9999-9999-999999999999")


def test_named_patient_with_no_patients_says_none():
    with pytest.raises(UnknownPatientError, match="Followed patients: none"):
        resolve_patient([], "Ann")
