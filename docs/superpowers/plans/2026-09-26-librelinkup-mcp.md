# librelinkup-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python MCP server (stdio) that exposes read-only FreeStyle Libre glucose readings from a LibreLinkUp follower account, with optional privacy-preserving Langfuse tracing.

**Architecture:** Four small modules behind a thin MCP layer: `config` reads env vars, `formatting` turns pylibrelinkup models into dicts, `tracing` wraps Langfuse and does nothing when disabled, and `service` (`GlucoseService`) is the only code that calls pylibrelinkup. It handles lazy login, re-login on expiry, patient lookup and error mapping. `server.py` registers four `MCPServer` tools that call the service and format the result.

**Tech Stack:** Python ≥3.11, `mcp` 2.x (`MCPServer`), `pylibrelinkup` ≥0.11, optional `langfuse` 4.x, uv, hatchling, pytest + pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-09-26-librelinkup-mcp-design.md`

**Status of the code below:** every file in this plan was written and run in a scratch copy before the plan was written. The full suite passed (86 tests, 1 live test deselected), ruff was clean, and a stdio subprocess run and a real-Langfuse run both behaved correctly. Copy the code exactly.

## Global Constraints

- `requires-python = ">=3.11"`.
- Dependencies: `mcp>=2.2,<3`, `pylibrelinkup>=0.11`. Optional extra `langfuse`: `langfuse>=4,<5`.
- mcp 2.x API: `from mcp.server.mcpserver import MCPServer`; `ToolError` is at `mcp.server.mcpserver.exceptions`; the in-process test client is `from mcp import Client` and is used as `Client(server)`. Result fields are snake_case: `is_error`, `structured_content`, `input_schema`, `annotations.read_only_hint`. There is no `mcp.server.fastmcp` in 2.x.
- pylibrelinkup's top level exports `APIUrl`, `PyLibreLinkUp` and the exceptions, but **not** the models. Import `Patient`, `GlucoseMeasurement` and `GlucoseMeasurementWithTrend` from `pylibrelinkup.models.data`.
- Only `service.py` imports the pylibrelinkup client and exceptions. `formatting.py` and tests may import the models.
- Credentials come from env vars only: `LIBRELINKUP_EMAIL`, `LIBRELINKUP_PASSWORD`, `LIBRELINKUP_REGION` (default `US`).
- Nothing may write to stdout except the MCP transport. Logging goes to stderr.
- Tracing sends no glucose values, names or error messages unless `LANGFUSE_CAPTURE_DATA` is `true`/`1`/`yes`. Only UUIDs, tool names, timings and exception class names are sent otherwise.
- Tests never touch the network or real Langfuse, except `tests/test_live.py`, which is marker `live` and deselected by default.
- Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run everything through `uv run …`. If uv prints a warning that `VIRTUAL_ENV=… does not match the project environment`, ignore it; uv uses the project's `.venv`.

## Review Focus

These are inputs and conditions the spec implies but doesn't spell out, and each has a test in the task named:

1. **No active sensor or odd payload:** pylibrelinkup raises `pydantic.ValidationError`. The user should get a clean tool error, not a stack dump. Tested in Task 5 by `test_unexpected_payload_shape_is_a_clean_tool_error`.
2. **The MCP client sends `patient: ""` or whitespace** instead of omitting it. This should be treated as omitted. Tested in Task 4 by `test_blank_identifier_picks_only_patient`.
3. **Something writes to stdout** (a log line or Langfuse output) and corrupts the stdio protocol. Tested in Task 6 by `test_stdio_server_starts_and_lists_tools`, which runs the real entry point as a subprocess.
4. **Password with leading or trailing spaces** must be sent exactly as given, never stripped. Tested in Task 1 by `test_password_is_used_verbatim`.
5. **Session expires and the next call is the patient-list refresh** (401 on `get_patients`). This must re-authenticate like the data calls do. Tested in Task 5 by `test_expired_session_on_patient_list_reauthenticates`.

---

### Task 1: Project scaffold and configuration

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md` (one-line stub; Task 7 replaces it), `src/librelinkup_mcp/__init__.py`, `src/librelinkup_mcp/config.py`, `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `librelinkup_mcp.config.ConfigError(Exception)`; frozen dataclass `Settings(email: str, password: str, region: pylibrelinkup.APIUrl, langfuse_enabled: bool, langfuse_capture_data: bool)` with the password hidden from `repr`; `load_settings(env: Mapping[str, str] | None = None) -> Settings`, which reads `os.environ` when `env` is None.

- [ ] **Step 1: Create packaging files**

`pyproject.toml`:

```toml
[project]
name = "librelinkup-mcp"
version = "0.1.0"
description = "MCP server exposing FreeStyle Libre glucose readings from LibreLinkUp"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "mcp>=2.2,<3",
    "pylibrelinkup>=0.11",
]

[project.optional-dependencies]
langfuse = ["langfuse>=4,<5"]

[project.scripts]
librelinkup-mcp = "librelinkup_mcp.server:main"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/librelinkup_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-m 'not live'"
markers = ["live: calls the real LibreLinkUp API (needs LIBRELINKUP_EMAIL/PASSWORD)"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

`.gitignore`:

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
dist/
.env
```

`README.md`:

```markdown
# librelinkup-mcp
```

`src/librelinkup_mcp/__init__.py`:

```python
"""MCP server for FreeStyle Libre glucose readings via LibreLinkUp."""
```

`tests/__init__.py`: empty file.

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: creates `.venv/` and `uv.lock` with no errors.

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:

```python
import pytest
from pylibrelinkup import APIUrl

from librelinkup_mcp.config import ConfigError, load_settings

CREDS = {"LIBRELINKUP_EMAIL": "me@example.com", "LIBRELINKUP_PASSWORD": "s3cret"}


def test_minimal_env_uses_defaults():
    settings = load_settings(CREDS)
    assert settings.email == "me@example.com"
    assert settings.password == "s3cret"
    assert settings.region is APIUrl.US
    assert settings.langfuse_enabled is False
    assert settings.langfuse_capture_data is False


def test_password_not_in_repr():
    assert "s3cret" not in repr(load_settings(CREDS))


@pytest.mark.parametrize("missing", ["LIBRELINKUP_EMAIL", "LIBRELINKUP_PASSWORD"])
def test_missing_credential_raises(missing):
    env = {k: v for k, v in CREDS.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_password_is_used_verbatim():
    assert load_settings({**CREDS, "LIBRELINKUP_PASSWORD": " pass word "}).password == " pass word "


def test_blank_email_counts_as_missing():
    with pytest.raises(ConfigError, match="LIBRELINKUP_EMAIL"):
        load_settings({**CREDS, "LIBRELINKUP_EMAIL": "   "})


@pytest.mark.parametrize(
    "raw, expected", [("eu", APIUrl.EU), (" EU2 ", APIUrl.EU2), ("", APIUrl.US)]
)
def test_region_is_case_insensitive_and_defaults_to_us(raw, expected):
    assert load_settings({**CREDS, "LIBRELINKUP_REGION": raw}).region is expected


def test_invalid_region_lists_valid_regions():
    with pytest.raises(ConfigError) as info:
        load_settings({**CREDS, "LIBRELINKUP_REGION": "mars"})
    assert "'mars'" in str(info.value)
    assert "US" in str(info.value) and "EU2" in str(info.value)


@pytest.mark.parametrize(
    "public, secret, enabled",
    [("pk", "sk", True), ("pk", "", False), ("", "sk", False), ("", "", False)],
)
def test_langfuse_enabled_only_with_both_keys(public, secret, enabled):
    env = {**CREDS, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
    assert load_settings(env).langfuse_enabled is enabled


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_capture_flag_parsing(raw, expected):
    env = {**CREDS, "LANGFUSE_CAPTURE_DATA": raw}
    assert load_settings(env).langfuse_capture_data is expected
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'librelinkup_mcp.config'`.

- [ ] **Step 5: Implement `config.py`**

`src/librelinkup_mcp/config.py`:

```python
"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from pylibrelinkup import APIUrl

_TRUTHY = {"true", "1", "yes"}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    email: str
    password: str = field(repr=False)
    region: APIUrl
    langfuse_enabled: bool
    langfuse_capture_data: bool


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ). Raises ConfigError."""
    env = os.environ if env is None else env

    email = env.get("LIBRELINKUP_EMAIL", "").strip()
    password = env.get("LIBRELINKUP_PASSWORD", "")
    missing = [
        name
        for name, value in (("LIBRELINKUP_EMAIL", email), ("LIBRELINKUP_PASSWORD", password))
        if not value
    ]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}")

    region_name = env.get("LIBRELINKUP_REGION", "").strip() or "US"
    try:
        region = APIUrl.from_string(region_name)
    except ValueError:
        valid = ", ".join(member.name for member in APIUrl)
        raise ConfigError(
            f"Invalid LIBRELINKUP_REGION {region_name!r}. Valid regions: {valid}"
        ) from None

    langfuse_enabled = bool(
        env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    capture = env.get("LANGFUSE_CAPTURE_DATA", "").strip().lower() in _TRUTHY

    return Settings(
        email=email,
        password=password,
        region=region,
        langfuse_enabled=langfuse_enabled,
        langfuse_capture_data=capture,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: `20 passed`.

- [ ] **Step 7: Lint**

Run: `uv run ruff check src tests && uv run ruff format --check src tests`
Expected: `All checks passed!` and no files to reformat.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore README.md src tests
git commit -m "feat: project scaffold and env-based settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Formatting models into tool output

**Files:**
- Create: `src/librelinkup_mcp/formatting.py`, `tests/factories.py`
- Test: `tests/test_formatting.py`

**Interfaces:**
- Consumes: pylibrelinkup models from `pylibrelinkup.models.data`.
- Produces:
  - `patient_to_dict(Patient) -> dict[str, str]` with keys `patient_id`, `id`, `first_name`, `last_name`.
  - `measurement_to_dict(GlucoseMeasurement) -> dict` with keys `timestamp`, `value`, `value_mg_dl`, `unit`, `is_high`, `is_low`, plus `trend` and `trend_arrow` for `GlucoseMeasurementWithTrend`.
  - `current_response(Patient, GlucoseMeasurementWithTrend) -> {"patient", "reading"}`.
  - `readings_response(Patient, Iterable[GlucoseMeasurement]) -> {"patient", "count", "readings"}`, sorted oldest first.
  - Test helpers in `tests/factories.py`: `make_patient`, `make_measurement`, `make_current`, and the fixtures `ANN`, `BOB`, `ANN_SMITH`. Tasks 4 to 6 reuse these.

The `GlucoseUnits` encoding comes from pylibrelinkup's own fixtures: `1` means mg/dL and `0` means mmol/L. `timestamp` is the sensor's local time with no timezone, which is how the API reports it.

- [ ] **Step 1: Write the test factories**

`tests/factories.py`:

```python
"""Builders for real pylibrelinkup models, using the API's JSON field names."""

from __future__ import annotations

from pylibrelinkup.models.data import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient


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
    timestamp: str, value: float, *, mg_dl: float | None = None, units: int = 1
) -> GlucoseMeasurement:
    """`timestamp` uses the API format, e.g. "9/26/2026 7:00:00 AM"."""
    data = _measurement_json(timestamp, value, value if mg_dl is None else mg_dl, units)
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
```

- [ ] **Step 2: Write the failing test**

`tests/test_formatting.py`:

```python
import json

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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_formatting.py -q`
Expected: collection error, `No module named 'librelinkup_mcp.formatting'`.

- [ ] **Step 4: Implement `formatting.py`**

`src/librelinkup_mcp/formatting.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `28 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/formatting.py tests/factories.py tests/test_formatting.py
git commit -m "feat: format glucose readings and patients as tool output

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Optional Langfuse tracing

**Files:**
- Create: `src/librelinkup_mcp/tracing.py`
- Test: `tests/test_tracing.py`

**Interfaces:**
- Consumes: `Settings` from Task 1.
- Produces:
  - `configure(settings: Settings, *, client: Any | None = None) -> None`. Tests pass `client=` to inject a fake.
  - `shutdown() -> None`.
  - `span(name: str, metadata: dict | None = None)`: an async context manager for child spans.
  - `traced(name: str)`: a decorator for async tool functions that preserves `__name__`, signature and docstring, so `MCPServer` still builds the right schema.

**Why not Langfuse's `@observe`:** it always writes `str(exception)` into the trace, and our error messages can contain patient names. This module opens observations with `client.start_as_current_observation(...)` and catches exceptions *inside* the observation. It records `level="ERROR"` with the class name, or with the message only when capture is on, then re-raises after the observation closes. That way the SDK never sees the raw exception. The Langfuse 4 signatures this relies on are `start_as_current_observation(*, name, as_type, input, metadata, ...)` (a context manager yielding an object with `.update(output=..., level=..., status_message=...)`) and `Langfuse.shutdown()`.

`traced` checks whether tracing is on at call time, not when the function is decorated, because `configure()` runs in `main()` after the tools have already been decorated at import.

- [ ] **Step 1: Write the failing test**

`tests/test_tracing.py`:

```python
import builtins
from contextlib import contextmanager

import pytest

from librelinkup_mcp import tracing
from librelinkup_mcp.config import load_settings

CREDS = {"LIBRELINKUP_EMAIL": "me@example.com", "LIBRELINKUP_PASSWORD": "pw"}
LANGFUSE = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}


class FakeObservation:
    def __init__(self, **kwargs):
        self.start = kwargs
        self.updates = {}

    def update(self, **kwargs):
        self.updates.update(kwargs)


class FakeLangfuse:
    def __init__(self):
        self.observations: list[FakeObservation] = []
        self.shut_down = False

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = FakeObservation(**kwargs)
        self.observations.append(observation)
        yield observation

    def shutdown(self):
        self.shut_down = True


@pytest.fixture(autouse=True)
def reset_tracing():
    yield
    tracing.configure(load_settings(CREDS))


def enable(capture: bool) -> FakeLangfuse:
    fake = FakeLangfuse()
    env = {**CREDS, **LANGFUSE, "LANGFUSE_CAPTURE_DATA": "true" if capture else "false"}
    tracing.configure(load_settings(env), client=fake)
    return fake


@tracing.traced("echo")
async def echo(patient: str | None = None) -> dict:
    return {"patient": patient}


@tracing.traced("boom")
async def boom(patient: str | None = None) -> dict:
    raise ValueError(f"no patient named {patient}")


async def test_disabled_is_passthrough():
    tracing.configure(load_settings(CREDS), client=FakeLangfuse())
    assert await echo(patient="Ann") == {"patient": "Ann"}
    with pytest.raises(ValueError, match="no patient named Ann"):
        await boom(patient="Ann")
    tracing.shutdown()


def test_missing_langfuse_package_disables_tracing(monkeypatch, caplog):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("no langfuse")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tracing.configure(load_settings({**CREDS, **LANGFUSE}))
    assert tracing._client is None
    assert "not installed" in caplog.text


async def test_metadata_only_by_default():
    fake = enable(capture=False)
    assert await echo(patient="Ann") == {"patient": "Ann"}
    [obs] = fake.observations
    assert obs.start["name"] == "echo"
    assert obs.start["as_type"] == "tool"
    assert obs.start["input"] is None
    assert obs.start["metadata"] == {"tool": "echo"}
    assert "output" not in obs.updates


async def test_capture_records_input_and_output():
    fake = enable(capture=True)
    await echo(patient="Ann")
    [obs] = fake.observations
    assert obs.start["input"] == {"patient": "Ann"}
    assert obs.updates["output"] == {"patient": "Ann"}


async def test_error_without_capture_hides_message():
    fake = enable(capture=False)
    with pytest.raises(ValueError, match="no patient named Ann"):
        await boom(patient="Ann")
    [obs] = fake.observations
    assert obs.updates == {"level": "ERROR", "status_message": "ValueError"}


async def test_error_with_capture_includes_message():
    fake = enable(capture=True)
    with pytest.raises(ValueError):
        await boom(patient="Ann")
    assert fake.observations[0].updates["status_message"] == "no patient named Ann"


async def test_span_records_metadata_and_errors():
    fake = enable(capture=False)
    async with tracing.span("librelinkup.graph", {"patient_id": "abc"}):
        pass
    with pytest.raises(RuntimeError):
        async with tracing.span("librelinkup.graph", {"patient_id": "abc"}):
            raise RuntimeError("Ann Lee")
    ok, failed = fake.observations
    assert ok.start["as_type"] == "span"
    assert ok.start["metadata"] == {"patient_id": "abc"}
    assert failed.updates == {"level": "ERROR", "status_message": "RuntimeError"}


def test_shutdown_flushes_client():
    fake = enable(capture=False)
    tracing.shutdown()
    assert fake.shut_down


def test_traced_preserves_signature_for_schema_generation():
    import inspect

    assert list(inspect.signature(echo).parameters) == ["patient"]
    assert echo.__name__ == "echo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracing.py -q`
Expected: collection error, `cannot import name 'tracing'`.

- [ ] **Step 3: Implement `tracing.py`**

`src/librelinkup_mcp/tracing.py`:

```python
"""Optional Langfuse tracing.

Every entry point is a passthrough until `configure()` installs a Langfuse
client. Errors are recorded by hand instead of via Langfuse's `@observe`,
which always writes `str(exception)` into the trace; our error messages can
contain patient names, which must stay out of traces unless capture is on.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, ParamSpec, TypeVar

from librelinkup_mcp.config import Settings

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_client: Any | None = None
_capture = False


def configure(settings: Settings, *, client: Any | None = None) -> None:
    """Enable tracing when settings allow it. `client` overrides the Langfuse client (tests)."""
    global _client, _capture
    _client = None
    _capture = settings.langfuse_capture_data
    if not settings.langfuse_enabled:
        return
    if client is None:
        try:
            from langfuse import get_client
        except ImportError:
            log.warning(
                "LANGFUSE_* keys are set but the 'langfuse' package is not installed; "
                "tracing is disabled. Install with: pip install 'librelinkup-mcp[langfuse]'"
            )
            return
        client = get_client()
    _client = client


def shutdown() -> None:
    """Flush pending traces. Safe to call when tracing is disabled."""
    if _client is not None:
        _client.shutdown()


def _discard(_value: Any) -> None:
    pass


@asynccontextmanager
async def _observe(
    name: str, as_type: str, *, input: Any = None, metadata: dict[str, Any] | None = None
) -> AsyncIterator[Callable[[Any], None]]:
    """Open an observation; yields a callback that records the output."""
    if _client is None:
        yield _discard
        return

    error: Exception | None = None
    with _client.start_as_current_observation(
        name=name,
        as_type=as_type,
        input=input if _capture else None,
        metadata=metadata,
    ) as observation:

        def record_output(value: Any) -> None:
            if _capture:
                observation.update(output=value)

        try:
            yield record_output
        except Exception as exc:
            error = exc
            observation.update(
                level="ERROR",
                status_message=str(exc) if _capture else type(exc).__name__,
            )
    if error is not None:
        raise error


def span(name: str, metadata: dict[str, Any] | None = None):
    """Async context manager for a child span, e.g. one upstream API call."""
    return _observe(name, "span", metadata=metadata)


def traced(name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorate an async MCP tool so each call becomes one Langfuse observation."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            async with _observe(
                name, "tool", input=dict(kwargs), metadata={"tool": name}
            ) as record_output:
                result = await func(*args, **kwargs)
                record_output(result)
            return result

        return wrapper

    return decorator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `37 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/tracing.py tests/test_tracing.py
git commit -m "feat: optional Langfuse tracing that keeps health data out by default

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Patient resolution

**Files:**
- Create: `src/librelinkup_mcp/service.py` (resolution only; Task 5 adds `GlucoseService`)
- Test: `tests/test_patient_resolution.py`

**Interfaces:**
- Consumes: `tests/factories.py` from Task 2.
- Produces: `UnknownPatientError(ToolError)` and `resolve_patient(patients: list[Patient], identifier: str | None) -> Patient`. The rules:
  1. A blank identifier (`None`, `""`, whitespace) picks the only patient. With no patients it raises ToolError "No patients are followed…"; with several it raises ToolError listing `First Last (patient_id)` for each.
  2. A UUID in any case matches `patient_id` or `id`.
  3. Otherwise the identifier is matched case-insensitively against the full name, with whitespace collapsed, and then against the first name if no full name matches.
  4. One match is returned. Several matches raise ToolError "…ambiguous…" listing the candidates. No match raises `UnknownPatientError` listing all followed patients, or "none".

Only the not-found case uses `UnknownPatientError`, because Task 5 refreshes the cached list when it sees that error, and only then.

- [ ] **Step 1: Write the failing test**

`tests/test_patient_resolution.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_patient_resolution.py -q`
Expected: collection error, `No module named 'librelinkup_mcp.service'`.

- [ ] **Step 3: Implement resolution in `service.py`**

`src/librelinkup_mcp/service.py`:

```python
"""GlucoseService: the only module that talks to pylibrelinkup."""

from __future__ import annotations

from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError
from pylibrelinkup.models.data import Patient


class UnknownPatientError(ToolError):
    """No followed patient matches the requested identifier."""


def _describe(patients: list[Patient]) -> str:
    if not patients:
        return "none"
    return ", ".join(f"{p.first_name} {p.last_name} ({p.patient_id})" for p in patients)


def resolve_patient(patients: list[Patient], identifier: str | None) -> Patient:
    """Pick the patient named by `identifier` (UUID or name); None means "the only one"."""
    text = " ".join((identifier or "").split())
    if not text:
        if len(patients) == 1:
            return patients[0]
        if not patients:
            raise ToolError("No patients are followed by this LibreLinkUp account.")
        raise ToolError(
            "This account follows several patients; pass `patient` as one of: "
            + _describe(patients)
        )

    try:
        wanted = UUID(text)
    except ValueError:
        key = text.casefold()
        matches = [p for p in patients if f"{p.first_name} {p.last_name}".casefold() == key]
        if not matches:
            matches = [p for p in patients if p.first_name.casefold() == key]
    else:
        matches = [p for p in patients if wanted in (p.patient_id, p.id)]

    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ToolError(
            f"Patient {text!r} is ambiguous; pass the patient_id of one of: {_describe(matches)}"
        )
    raise UnknownPatientError(
        f"No followed patient matches {text!r}. Followed patients: {_describe(patients)}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `54 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/service.py tests/test_patient_resolution.py
git commit -m "feat: resolve patients by name or UUID

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: GlucoseService (login, retry, error mapping)

**Files:**
- Modify: `src/librelinkup_mcp/service.py` (replace it with the full version below; the Task 4 functions are unchanged)
- Create: `tests/fakes.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `resolve_patient` and `UnknownPatientError` (Task 4), and `tracing.span` (Task 3).
- Produces: `GlucoseService(client: LibreClient)` with these async methods:
  - `list_patients() -> list[Patient]`
  - `current(patient: str | None) -> tuple[Patient, GlucoseMeasurementWithTrend]`
  - `graph(patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]`
  - `logbook(patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]`

  `LibreClient` is a `Protocol` that `pylibrelinkup.PyLibreLinkUp` satisfies. `tests/fakes.py` provides `FakeLibreClient(patients, *, auth_delay=0.0)` with `.calls`, `.count(method)`, `.patients` and `.fail_next[method] = [exc, …]`, plus `http_error(status)`. Task 6 reuses both.

**Behaviour:**
- **Lazy login:** the first call logs in. `_auth_lock` makes concurrent first calls share one login.
- **Patient cache:** the list is fetched once under `_patients_lock` and fetched again once on `UnknownPatientError`.
- **Expiry:** pylibrelinkup reports an expired token as `requests.HTTPError` 401, or as `AuthenticationError` when the token was never set. Either one triggers one re-login and one retry of the call, and a second failure surfaces.
- **Blocking I/O:** every client call runs in `asyncio.to_thread`.
- **Tracing:** each upstream call is wrapped in `tracing.span("librelinkup.<method>", {"patient_id": …})`, which carries the UUID only.
- **Error mapping:** exceptions become ToolErrors per the spec table, chained with `from exc`. Anything not in the table propagates unchanged. The check order matters: `LLUAPIRateLimitError` before `LLUAPIError` (it's a subclass), and `HTTPError` before `RequestException`.

- [ ] **Step 1: Write the fake client**

`tests/fakes.py`:

```python
"""A scriptable stand-in for pylibrelinkup.PyLibreLinkUp."""

from __future__ import annotations

import threading
import time
from uuid import UUID

import requests

from tests.factories import make_current, make_measurement


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


class FakeLibreClient:
    """Records calls; `fail_next[method]` holds exceptions to raise, one per call."""

    def __init__(self, patients, *, auth_delay: float = 0.0):
        self.patients = list(patients)
        self.auth_delay = auth_delay
        self.calls: list[tuple[str, UUID | None]] = []
        self.fail_next: dict[str, list[Exception]] = {}
        self._lock = threading.Lock()

    def _record(self, method: str, patient_id: UUID | None = None) -> None:
        with self._lock:
            self.calls.append((method, patient_id))
            queue = self.fail_next.get(method)
            error = queue.pop(0) if queue else None
        if error is not None:
            raise error

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    def authenticate(self) -> None:
        if self.auth_delay:
            time.sleep(self.auth_delay)
        self._record("authenticate")

    def get_patients(self):
        self._record("get_patients")
        return list(self.patients)

    def latest(self, patient_identifier):
        self._record("latest", patient_identifier)
        return make_current("9/26/2026 7:05:00 AM", 115, trend=3)

    def graph(self, patient_identifier):
        self._record("graph", patient_identifier)
        return [
            make_measurement("9/26/2026 7:00:00 AM", 120),
            make_measurement("9/26/2026 6:45:00 AM", 110),
        ]

    def logbook(self, patient_identifier):
        self._record("logbook", patient_identifier)
        return [make_measurement("9/20/2026 3:00:00 AM", 62)]
```

- [ ] **Step 2: Write the failing test**

`tests/test_service.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_service.py -q`
Expected: collection error, `cannot import name 'GlucoseService'`.

- [ ] **Step 4: Replace `service.py` with the full implementation**

`src/librelinkup_mcp/service.py`:

```python
"""GlucoseService: the only module that talks to pylibrelinkup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol, TypeVar
from uuid import UUID

import pydantic
import requests
from mcp.server.mcpserver.exceptions import ToolError
from pylibrelinkup import (
    AuthenticationError,
    EmailVerificationError,
    LLUAPIError,
    LLUAPIRateLimitError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RedirectError,
    TermsOfUseError,
)
from pylibrelinkup.models.data import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient

from librelinkup_mcp import tracing

T = TypeVar("T")


class LibreClient(Protocol):
    """The subset of pylibrelinkup.PyLibreLinkUp that GlucoseService uses."""

    def authenticate(self) -> None: ...
    def get_patients(self) -> list[Patient]: ...
    def latest(self, patient_identifier: UUID) -> GlucoseMeasurementWithTrend: ...
    def graph(self, patient_identifier: UUID) -> list[GlucoseMeasurement]: ...
    def logbook(self, patient_identifier: UUID) -> list[GlucoseMeasurement]: ...


class UnknownPatientError(ToolError):
    """No followed patient matches the requested identifier."""


def _describe(patients: list[Patient]) -> str:
    if not patients:
        return "none"
    return ", ".join(f"{p.first_name} {p.last_name} ({p.patient_id})" for p in patients)


def resolve_patient(patients: list[Patient], identifier: str | None) -> Patient:
    """Pick the patient named by `identifier` (UUID or name); None means "the only one"."""
    text = " ".join((identifier or "").split())
    if not text:
        if len(patients) == 1:
            return patients[0]
        if not patients:
            raise ToolError("No patients are followed by this LibreLinkUp account.")
        raise ToolError(
            "This account follows several patients; pass `patient` as one of: "
            + _describe(patients)
        )

    try:
        wanted = UUID(text)
    except ValueError:
        key = text.casefold()
        matches = [p for p in patients if f"{p.first_name} {p.last_name}".casefold() == key]
        if not matches:
            matches = [p for p in patients if p.first_name.casefold() == key]
    else:
        matches = [p for p in patients if wanted in (p.patient_id, p.id)]

    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ToolError(
            f"Patient {text!r} is ambiguous; pass the patient_id of one of: {_describe(matches)}"
        )
    raise UnknownPatientError(
        f"No followed patient matches {text!r}. Followed patients: {_describe(patients)}"
    )


def _is_auth_failure(exc: Exception) -> bool:
    if isinstance(exc, AuthenticationError):
        return True
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and exc.response.status_code == 401
    )


def _to_tool_error(exc: Exception) -> ToolError | None:
    """Translate a pylibrelinkup/requests exception into a user-facing ToolError."""
    if isinstance(exc, AuthenticationError):
        return ToolError(
            "LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD."
        )
    if isinstance(exc, RedirectError):
        region = exc.region.name
        return ToolError(
            f"This account belongs to region {region}. Set LIBRELINKUP_REGION={region}."
        )
    if isinstance(exc, TermsOfUseError):
        return ToolError(
            "Open the LibreLinkUp app and accept the updated terms of use, then retry."
        )
    if isinstance(exc, PrivacyPolicyError):
        return ToolError(
            "Open the LibreLinkUp app and accept the updated privacy policy, then retry."
        )
    if isinstance(exc, EmailVerificationError):
        return ToolError("Verify the account email address in the LibreLinkUp app, then retry.")
    if isinstance(exc, LLUAPIRateLimitError):
        wait = f"in {exc.retry_after} seconds" if exc.retry_after is not None else "later"
        return ToolError(f"Rate limited by LibreLinkUp. Try again {wait}.")
    if isinstance(exc, PatientNotFoundError):
        return ToolError("LibreLinkUp reports patient not found.")
    if isinstance(exc, LLUAPIError):
        return ToolError(f"LibreLinkUp API error {exc.response_code}.")
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else "unknown"
        return ToolError(f"LibreLinkUp API error {status}.")
    if isinstance(exc, requests.RequestException):
        return ToolError(f"Could not reach LibreLinkUp: {type(exc).__name__}.")
    if isinstance(exc, pydantic.ValidationError):
        return ToolError(
            "LibreLinkUp returned data in an unexpected shape "
            "(for example, no active sensor for this patient)."
        )
    return None


class GlucoseService:
    """Async facade over a sync LibreLinkUp client: lazy login, re-auth, patient lookup."""

    def __init__(self, client: LibreClient) -> None:
        self._client = client
        self._auth_lock = asyncio.Lock()
        self._patients_lock = asyncio.Lock()
        self._authenticated = False
        self._patients: list[Patient] | None = None

    async def list_patients(self) -> list[Patient]:
        return await self._patient_list(refresh=False)

    async def current(self, patient: str | None) -> tuple[Patient, GlucoseMeasurementWithTrend]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("latest", self._client.latest, resolved)

    async def graph(self, patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("graph", self._client.graph, resolved)

    async def logbook(self, patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]:
        resolved = await self._resolve(patient)
        return resolved, await self._request("logbook", self._client.logbook, resolved)

    async def _resolve(self, identifier: str | None) -> Patient:
        try:
            return resolve_patient(await self._patient_list(refresh=False), identifier)
        except UnknownPatientError:
            # The account may have started following someone since the list was cached.
            return resolve_patient(await self._patient_list(refresh=True), identifier)

    async def _patient_list(self, *, refresh: bool) -> list[Patient]:
        async with self._patients_lock:
            if self._patients is None or refresh:
                self._patients = await self._request("get_patients", self._client.get_patients)
            return self._patients

    async def _authenticate(self, *, force: bool) -> None:
        async with self._auth_lock:
            if self._authenticated and not force:
                return
            self._authenticated = False
            await asyncio.to_thread(self._client.authenticate)
            self._authenticated = True

    async def _request(
        self, method: str, fn: Callable[..., T], patient: Patient | None = None
    ) -> T:
        args = () if patient is None else (patient.patient_id,)
        metadata = None if patient is None else {"patient_id": str(patient.patient_id)}
        async with tracing.span(f"librelinkup.{method}", metadata):
            try:
                return await self._call_with_reauth(fn, *args)
            except Exception as exc:
                tool_error = _to_tool_error(exc)
                if tool_error is None:
                    raise
                raise tool_error from exc

    async def _call_with_reauth(self, fn: Callable[..., T], *args: object) -> T:
        await self._authenticate(force=False)
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as exc:
            if not _is_auth_failure(exc):
                raise
        await self._authenticate(force=True)
        return await asyncio.to_thread(fn, *args)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `78 passed`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/service.py tests/fakes.py tests/test_service.py
git commit -m "feat: GlucoseService with lazy auth, re-auth and error mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: MCP server and entry point

**Files:**
- Create: `src/librelinkup_mcp/server.py`, `src/librelinkup_mcp/__main__.py`
- Test: `tests/test_server.py`, `tests/test_stdio.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `server.mcp` (an `MCPServer`), `server.set_service(GlucoseService | None)`, `server.main()` (the console script `librelinkup-mcp`), and `python -m librelinkup_mcp`.

**Notes:**
- **Decorator order:** `@mcp.tool(...)` must be outermost and `@tracing.traced(...)` inner, so the registered function is the traced wrapper. The schema still comes from the original signature via `functools.wraps`.
- **Read-only hint:** tools carry `ToolAnnotations(readOnlyHint=True, openWorldHint=True)` so clients can treat them as read-only.
- **Error reporting:** `MCPServer` turns a raised `ToolError` into a result with `is_error=True` and the text `Error executing tool <name>: <message>`.
- **`main()` order:** stderr logging, then settings (exit 1 with a stderr message on `ConfigError`), then tracing, then the `atexit` shutdown hook, then the real `PyLibreLinkUp`, then `mcp.run("stdio")`.
- **`test_stdio.py`:** launches the real module with dummy credentials and only lists tools, which needs no network. Don't add a tool call there, because it would send a real login to Abbott's servers.

- [ ] **Step 1: Write the failing tests**

`tests/test_server.py`:

```python
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
```

`tests/test_stdio.py`:

```python
"""Run the real entry point as a subprocess: proves nothing but MCP frames reach stdout."""

import sys

from mcp import Client, StdioServerParameters

ENV = {
    "LIBRELINKUP_EMAIL": "nobody@example.com",
    "LIBRELINKUP_PASSWORD": "unused",
    "PATH": "",
}


async def test_stdio_server_starts_and_lists_tools():
    params = StdioServerParameters(command=sys.executable, args=["-m", "librelinkup_mcp"], env=ENV)
    async with Client(params) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools.tools} == {
        "list_patients",
        "get_current_glucose",
        "get_glucose_graph",
        "get_glucose_logbook",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py tests/test_stdio.py -q`
Expected: `test_server.py` fails to collect with `cannot import name 'server'`. `test_stdio.py` fails because the subprocess exits with "No module named librelinkup_mcp.__main__", which the client surfaces as a connection error.

- [ ] **Step 3: Implement the server**

`src/librelinkup_mcp/server.py`:

```python
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

from librelinkup_mcp import formatting, tracing
from librelinkup_mcp.config import ConfigError, load_settings
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
    client = PyLibreLinkUp(
        email=settings.email, password=settings.password, api_url=settings.region
    )
    set_service(GlucoseService(client))
    mcp.run("stdio")
```

`src/librelinkup_mcp/__main__.py`:

```python
from librelinkup_mcp.server import main

main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `86 passed`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/server.py src/librelinkup_mcp/__main__.py tests/test_server.py tests/test_stdio.py
git commit -m "feat: MCP server with four read-only glucose tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: README, live smoke test, final verification

**Files:**
- Modify: `README.md` (replace the stub)
- Create: `tests/test_live.py`

**Interfaces:**
- Consumes: `server.mcp`, `server.set_service`, `GlucoseService`, `load_settings`.
- Produces: user documentation and an opt-in live test.

- [ ] **Step 1: Write the live test**

`tests/test_live.py`:

```python
"""Hits the real LibreLinkUp API. Run with: uv run pytest -m live"""

import os

import pytest
from mcp import Client
from pylibrelinkup import PyLibreLinkUp

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
    client = PyLibreLinkUp(
        email=settings.email, password=settings.password, api_url=settings.region
    )
    server.set_service(GlucoseService(client))
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
```

- [ ] **Step 2: Verify it's deselected by default and skipped without credentials**

Run: `uv run pytest -q`
Expected: `86 passed, 1 deselected`.

Run: `env -u LIBRELINKUP_EMAIL -u LIBRELINKUP_PASSWORD uv run pytest -m live -q -rs`
Expected: `1 skipped` with reason `needs LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD`.

- [ ] **Step 3: Write the README**

`README.md`:

````markdown
# librelinkup-mcp

An MCP server that gives Claude (or any MCP client) read-only access to FreeStyle Libre
CGM glucose readings shared through LibreLinkUp. Built on
[pylibrelinkup](https://github.com/robberwick/pylibrelinkup).

## Tools

| Tool | Returns |
|---|---|
| `list_patients` | People the LibreLinkUp account follows |
| `get_current_glucose` | Latest reading with trend arrow |
| `get_glucose_graph` | Readings from about the last 12 hours, oldest first |
| `get_glucose_logbook` | Logged events from about the last 2 weeks, oldest first |

Every reading tool takes an optional `patient`: a name (`"Ann Lee"`, `"ann"`) or a
`patient_id` from `list_patients`. It can be omitted when the account follows one person.

Readings include `value` in the account's unit, `value_mg_dl`, `unit`, `timestamp` (the
sensor's local time), and `is_high`/`is_low` flags.

## Setup

You need a LibreLinkUp **follower** account: invite it from the LibreLink app, accept the
invite in the LibreLinkUp app, and accept any terms there before using this server.

```bash
git clone <this repo> && cd librelinkup-mcp
uv sync
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LIBRELINKUP_EMAIL` | yes | | Follower account email |
| `LIBRELINKUP_PASSWORD` | yes | | Follower account password |
| `LIBRELINKUP_REGION` | no | `US` | One of `US`, `EU`, `EU2`, `AE`, `AP`, `AU`, `CA`, `DE`, `FR`, `JP`, `LA`, `RU` |

If the region is wrong, the first tool call tells you which one to set.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "librelinkup": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/librelinkup-mcp", "run", "librelinkup-mcp"],
      "env": {
        "LIBRELINKUP_EMAIL": "you@example.com",
        "LIBRELINKUP_PASSWORD": "your-password",
        "LIBRELINKUP_REGION": "US"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add librelinkup \
  -e LIBRELINKUP_EMAIL=you@example.com \
  -e LIBRELINKUP_PASSWORD=your-password \
  -e LIBRELINKUP_REGION=US \
  -- uv --directory /absolute/path/to/librelinkup-mcp run librelinkup-mcp
```

## Langfuse tracing (optional)

Each tool call becomes a Langfuse trace, with a child span for the LibreLinkUp API call.
Install the extra and set the keys:

```bash
uv sync --extra langfuse
```

In the server command, use `run --extra langfuse librelinkup-mcp` instead of
`run librelinkup-mcp`.

| Variable | Meaning |
|---|---|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | Tracing is on only when both are set |
| `LANGFUSE_BASE_URL` | Langfuse URL for self-hosted or regional instances (default: Langfuse Cloud) |
| `LANGFUSE_CAPTURE_DATA` | `true` to include tool inputs, outputs and error messages. Default `false` |

**Privacy:** glucose readings and patient names are health data. By default, traces hold
only tool names, timings, patient UUIDs, and error class names. Setting
`LANGFUSE_CAPTURE_DATA=true` sends readings and names to your Langfuse instance; only do
that with an instance you trust, such as a self-hosted one.

## Development

```bash
uv sync
uv run pytest            # offline suite
uv run pytest -m live    # hits the real API; needs LIBRELINKUP_EMAIL/PASSWORD
uv run ruff check src tests && uv run ruff format --check src tests
```
````

- [ ] **Step 4: Check the Langfuse extra installs and the server still starts**

Run: `uv sync --extra langfuse && uv run pytest -q && uv sync`
Expected: `86 passed, 1 deselected`. The last `uv sync` returns the env to the default set.

- [ ] **Step 5: Final verification**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`
Expected: `All checks passed!`, no files to reformat, `86 passed, 1 deselected`.

- [ ] **Step 6: Commit**

```bash
git add README.md tests/test_live.py
git commit -m "docs: README with client setup and Langfuse privacy notes; live smoke test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7 (manual, for the user): live check**

With real credentials exported, run `uv run pytest -m live -q`, expecting `1 passed`. Then add the server to Claude Desktop or Claude Code as the README describes and ask "what's my glucose right now?".
