from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from librelinkup_mcp.core import (
    GlucoseMeasurement,
    GlucoseMeasurementWithTrend,
    Patient,
    Trend,
)

READING = {
    "FactoryTimestamp": "9/26/2026 1:05:00 PM",
    "Timestamp": "9/26/2026 3:05:00 PM",
    "type": 1,
    "ValueInMgPerDl": 158,
    "MeasurementColor": 1,
    "GlucoseUnits": 0,
    "Value": 8.8,
    "isHigh": False,
    "isLow": False,
}


def test_patient_from_api_keys_strips_names():
    patient = Patient.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "patientId": "22222222-2222-2222-2222-222222222222",
            "firstName": " Ann ",
            "lastName": "Lee",
            "sensor": {"sn": "ignored"},
        }
    )
    assert patient.patient_id == UUID("22222222-2222-2222-2222-222222222222")
    assert patient.id == UUID("11111111-1111-1111-1111-111111111111")
    assert (patient.first_name, patient.last_name) == ("Ann", "Lee")


def test_measurement_timestamps_local_and_utc():
    m = GlucoseMeasurement.model_validate(READING)
    assert m.timestamp == datetime(2026, 9, 26, 15, 5)
    assert m.timestamp.tzinfo is None
    assert m.factory_timestamp == datetime(2026, 9, 26, 13, 5, tzinfo=UTC)


def test_measurement_mmol_fields():
    m = GlucoseMeasurement.model_validate(READING)
    assert (m.value, m.value_in_mg_per_dl, m.glucose_units) == (8.8, 158.0, 0)
    assert (m.is_high, m.is_low) == (False, False)


def test_bad_timestamp_is_a_validation_error():
    with pytest.raises(ValidationError):
        GlucoseMeasurement.model_validate({**READING, "Timestamp": "yesterday"})


def test_trend_parsed():
    m = GlucoseMeasurementWithTrend.model_validate({**READING, "TrendArrow": 4})
    assert m.trend is Trend.UP_SLOW
    assert m.trend.indicator == "↗"


@pytest.mark.parametrize("raw", [9, None, "up"])
def test_unknown_trend_values_become_unknown(raw):
    m = GlucoseMeasurementWithTrend.model_validate({**READING, "TrendArrow": raw})
    assert m.trend is Trend.UNKNOWN
    assert m.trend.indicator == "?"


def test_missing_trend_is_unknown():
    assert GlucoseMeasurementWithTrend.model_validate(READING).trend is Trend.UNKNOWN
