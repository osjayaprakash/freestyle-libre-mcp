"""Builders for real core models, using the API's JSON field names."""

from __future__ import annotations

from librelinkup_mcp.core import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient


def make_patient(first: str, last: str, patient_id: str, connection_id: str) -> Patient:
    return Patient.model_validate(
        {"id": connection_id, "patientId": patient_id, "firstName": first, "lastName": last}
    )


def _measurement_json(timestamp: str, value: float, mg_dl: float, units: int) -> dict:
    return {
        "FactoryTimestamp": timestamp,
        "Timestamp": timestamp,
        "type": 1,
        "ValueInMgPerDl": mg_dl,
        "MeasurementColor": 1,
        "GlucoseUnits": units,
        "Value": value,
        "isHigh": False,
        "isLow": False,
    }


def make_measurement(
    timestamp: str,
    value: float,
    *,
    mg_dl: float | None = None,
    units: int = 1,
    utc: str | None = None,
) -> GlucoseMeasurement:
    """`timestamp` uses the API format, e.g. "9/26/2026 7:00:00 AM".

    `utc` sets FactoryTimestamp (UTC); it defaults to `timestamp`.
    """
    data = _measurement_json(timestamp, value, value if mg_dl is None else mg_dl, units)
    if utc is not None:
        data["FactoryTimestamp"] = utc
    return GlucoseMeasurement.model_validate(data)


def make_current(
    timestamp: str, value: float, trend: int, *, mg_dl: float | None = None, units: int = 1
) -> GlucoseMeasurementWithTrend:
    data = _measurement_json(timestamp, value, value if mg_dl is None else mg_dl, units)
    data["TrendArrow"] = trend
    return GlucoseMeasurementWithTrend.model_validate(data)


ANN = make_patient(
    "Ann", "Lee", "22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111"
)
BOB = make_patient(
    "Bob", "Lee", "44444444-4444-4444-4444-444444444444", "33333333-3333-3333-3333-333333333333"
)
ANN_SMITH = make_patient(
    "Ann", "Smith", "66666666-6666-6666-6666-666666666666", "55555555-5555-5555-5555-555555555555"
)
