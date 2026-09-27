import json
from datetime import UTC, datetime

from librelinkup_mcp.formatting import (
    current_response,
    measurement_to_dict,
    patient_to_dict,
    readings_response,
)
from tests.factories import ANN, make_current, make_measurement


def test_patient_to_dict_stringifies_uuids():
    assert patient_to_dict(ANN) == {
        "patient_id": "22222222-2222-2222-2222-222222222222",
        "id": "11111111-1111-1111-1111-111111111111",
        "first_name": "Ann",
        "last_name": "Lee",
    }


def test_mg_dl_measurement():
    m = make_measurement("9/26/2026 7:05:00 AM", 115)
    assert measurement_to_dict(m) == {
        "timestamp": "2026-09-26T07:05:00",
        "timestamp_utc": "2026-09-26T07:05:00+00:00",
        "value": 115.0,
        "value_mg_dl": 115.0,
        "unit": "mg/dL",
        "is_high": False,
        "is_low": False,
    }


def test_mmol_measurement_keeps_both_values():
    m = make_measurement("9/26/2026 7:05:00 AM", 8.8, mg_dl=158, units=0)
    d = measurement_to_dict(m)
    assert (d["value"], d["value_mg_dl"], d["unit"]) == (8.8, 158.0, "mmol/L")


def test_trend_fields_only_on_current_reading():
    plain = measurement_to_dict(make_measurement("9/26/2026 7:05:00 AM", 115))
    assert "trend" not in plain and "trend_arrow" not in plain

    current = measurement_to_dict(make_current("9/26/2026 7:05:00 AM", 115, trend=4))
    assert current["trend"] == "UP_SLOW"
    assert current["trend_arrow"] == "↗"


def test_current_response_shape():
    result = current_response(ANN, make_current("9/26/2026 7:05:00 AM", 115, trend=3))
    assert result["patient"]["first_name"] == "Ann"
    assert result["reading"]["trend"] == "STABLE"


def test_readings_response_sorts_ascending_and_counts():
    late = make_measurement("9/26/2026 9:00:00 AM", 140)
    early = make_measurement("9/26/2026 1:00:00 AM", 90)
    noon = make_measurement("9/26/2026 12:00:00 PM", 120)
    result = readings_response(ANN, [late, early, noon])
    assert result["count"] == 3
    assert [r["value"] for r in result["readings"]] == [90.0, 140.0, 120.0]


def test_readings_response_empty_history():
    result = readings_response(ANN, [])
    assert result["count"] == 0
    assert result["readings"] == []


def test_responses_are_json_serialisable():
    json.dumps(readings_response(ANN, [make_measurement("9/26/2026 7:05:00 AM", 115)]))
    json.dumps(current_response(ANN, make_current("9/26/2026 7:05:00 AM", 115, trend=0)))


def test_current_reading_reports_age_so_stale_values_are_visible():
    reading = make_current("9/26/2026 7:05:00 AM", 115, trend=3)
    now = datetime(2026, 9, 26, 10, 5, 30, tzinfo=UTC)
    result = current_response(ANN, reading, now=now)
    assert result["reading"]["timestamp_utc"] == "2026-09-26T07:05:00+00:00"
    assert result["reading"]["age_minutes"] == 180


def test_readings_sort_by_utc_not_local_time():
    # DST fall-back: local 1:30 AM happens twice; UTC order is the truth.
    first = make_measurement("11/1/2026 1:45:00 AM", 100, utc="11/1/2026 5:45:00 AM")
    second = make_measurement("11/1/2026 1:15:00 AM", 110, utc="11/1/2026 6:15:00 AM")
    result = readings_response(ANN, [second, first])
    assert [r["value"] for r in result["readings"]] == [100.0, 110.0]
