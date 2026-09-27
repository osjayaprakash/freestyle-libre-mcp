"""Convert pylibrelinkup models into JSON-serialisable dicts for tool results."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pylibrelinkup.models.data import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient

# LibreLinkUp's GlucoseUnits field: 1 = mg/dL, 0 = mmol/L.
_MG_DL = 1


def patient_to_dict(patient: Patient) -> dict[str, str]:
    return {
        "patient_id": str(patient.patient_id),
        "id": str(patient.id),
        "first_name": patient.first_name,
        "last_name": patient.last_name,
    }


def measurement_to_dict(measurement: GlucoseMeasurement) -> dict[str, Any]:
    result: dict[str, Any] = {
        "timestamp": measurement.timestamp.isoformat(),
        "value": measurement.value,
        "value_mg_dl": measurement.value_in_mg_per_dl,
        "unit": "mg/dL" if measurement.glucose_units == _MG_DL else "mmol/L",
        "is_high": measurement.is_high,
        "is_low": measurement.is_low,
    }
    if isinstance(measurement, GlucoseMeasurementWithTrend):
        result["trend"] = measurement.trend.name
        result["trend_arrow"] = measurement.trend.indicator
    return result


def current_response(patient: Patient, measurement: GlucoseMeasurementWithTrend) -> dict[str, Any]:
    return {"patient": patient_to_dict(patient), "reading": measurement_to_dict(measurement)}


def readings_response(
    patient: Patient, measurements: Iterable[GlucoseMeasurement]
) -> dict[str, Any]:
    ordered = sorted(measurements, key=lambda m: m.timestamp)
    return {
        "patient": patient_to_dict(patient),
        "count": len(ordered),
        "readings": [measurement_to_dict(m) for m in ordered],
    }
