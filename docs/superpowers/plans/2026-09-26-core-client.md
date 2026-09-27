# Core LibreLinkUp Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `pylibrelinkup` dependency with an in-house async LibreLinkUp client in `src/librelinkup_mcp/core/`, with no change to MCP tool names, arguments or output.

**Architecture:** `core/` holds `regions.py` (a `Region` enum of base URLs), `models.py` (pydantic models with only the fields we read), `exceptions.py` (a `LibreLinkUpError` hierarchy), and `client.py` (`LibreLinkUpClient` on `httpx2.AsyncClient`). `GlucoseService` awaits the client directly instead of using `asyncio.to_thread`, and maps the core exceptions to ToolErrors.

**Tech Stack:** Python ≥3.11, `httpx2` (import name `httpx2`, already installed by `mcp`), `pydantic` 2, pytest + pytest-asyncio with `httpx2.MockTransport`, uv, ruff.

**Spec:** `docs/superpowers/specs/2026-09-26-core-client-design.md`. It supersedes the pylibrelinkup parts of `2026-09-26-librelinkup-mcp-design.md`.

**Status of the code below:** every file was written and run in a scratch worktree of this branch before the plan was written. The expected test counts come from real runs: 103, 121, 138 and 138 passed, with the live test deselected. ruff was clean, the stdio subprocess test passed, and the suite also passed with the `langfuse` extra installed. Copy the code exactly.

## Global Constraints

- The work continues on branch `feat/librelinkup-mcp`, starting at commit `748487f`. The baseline suite is `89 passed, 1 deselected`.
- `import httpx2`, not `httpx`, which is not installed. The APIs used are `httpx2.AsyncClient(base_url=, headers=, transport=, timeout=)`, `.request()`, `.aclose()`, `.is_closed`, `httpx2.Response(status, json=|text=, headers=)`, `.is_success`, `httpx2.MockTransport(handler)`, and `httpx2.TransportError` (the parent of `ConnectError`, `ReadTimeout` and every other timeout).
- Dependencies after Task 4: `httpx2>=2.5,<3`, `mcp>=2.2,<3`, `pydantic>=2.12,<3`, with no `pylibrelinkup` and no `requests` anywhere under `src/`. The extra `langfuse>=4,<5` is unchanged.
- The client is written fresh from API behaviour. Don't copy pylibrelinkup source or its fixture files. All fixtures in this plan are hand-written.
- Exception messages must never contain patient names or readings, because tracing may record `str(exc)` when capture is on.
- Tests never touch the network. `tests/test_live.py` stays marker `live` and is deselected by default.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `docs/` is in the user's uncommitted `.gitignore` edit. Leave `.gitignore` alone, and use `git add -f` if you ever need to commit a doc. This plan commits none.
- Ignore uv's warning `VIRTUAL_ENV=… does not match the project environment`.

## Review Focus

These are inputs the spec implies, each with a test in the task named:

1. **A maintenance page or other non-JSON body** should give `ResponseShapeError`, not a crash. Tested in Task 2 by `test_login_non_json_body`; the helper is shared with the data calls.
2. **A non-zero body `status` with no `error` object**, returned with HTTP 200, should give `APIError(status)` rather than a `KeyError`. Tested in Task 3 by `test_other_nonzero_body_status_is_api_error`.
3. **A password with surrounding spaces** must be sent verbatim. Tested in Task 2 by `test_login_posts_verbatim_credentials_with_app_headers`.
4. **A token that expires mid-session** (HTTP 401 on a data call) should raise `AuthenticationError`, which the service answers by logging in again. Tested in Task 3 by `test_expired_token_401` and in Task 4 by `test_expired_session_reauthenticates_and_retries`.
5. **A data call before login** must raise without sending a request carrying a missing bearer token. Tested in Task 3 by `test_data_call_before_login_sends_nothing`.

---

### Task 1: Core regions, models and exceptions

**Files:**
- Create: `src/librelinkup_mcp/core/__init__.py`, `src/librelinkup_mcp/core/regions.py`, `src/librelinkup_mcp/core/models.py`, `src/librelinkup_mcp/core/exceptions.py`, `tests/core/__init__.py` (empty)
- Test: `tests/core/test_regions.py`, `tests/core/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all re-exported from `librelinkup_mcp.core`):
  - `Region(StrEnum)`: its values are base URLs, and `Region.from_name(str) -> Region` raises `ValueError`.
  - `Patient(id, patient_id, first_name, last_name)`.
  - `Trend(IntEnum)` with an `.indicator` arrow.
  - `GlucoseMeasurement`, with fields `timestamp` (naive local), `factory_timestamp` (UTC-aware), `value`, `value_in_mg_per_dl`, `glucose_units`, `is_high` and `is_low`.
  - `GlucoseMeasurementWithTrend`, which adds `trend`.
  - The exceptions `LibreLinkUpError`, `AuthenticationError`, `RedirectError(region: str)`, `TermsOfUseError`, `PrivacyPolicyError`, `EmailVerificationError`, `RateLimitError(retry_after: int | None)`, `PatientNotFoundError`, `APIError(status: int)`, `NetworkError(kind: str)` and `ResponseShapeError(call: str)`.

  Model field names match the pylibrelinkup attributes the app already reads, so Task 4 only changes imports.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_regions.py`:

```python
import pytest

from librelinkup_mcp.core import Region


@pytest.mark.parametrize("name", ["eu2", "EU2", " Eu2 "])
def test_from_name_ignores_case_and_whitespace(name):
    assert Region.from_name(name) is Region.EU2


def test_from_name_rejects_unknown():
    with pytest.raises(ValueError, match="'mars'"):
        Region.from_name("mars")


def test_values_are_base_urls():
    assert Region.US == "https://api.libreview.io"
    assert Region.RU == "https://api.libreview.ru"
    assert len(Region) == 12
```

`tests/core/test_models.py`:

```python
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
```

Also create an empty `tests/core/__init__.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core -q`
Expected: 2 collection errors, `cannot import name … from 'librelinkup_mcp.core'`.

- [ ] **Step 3: Implement the modules**

`src/librelinkup_mcp/core/regions.py`:

```python
"""LibreLinkUp regional API hosts."""

from __future__ import annotations

from enum import StrEnum


class Region(StrEnum):
    US = "https://api.libreview.io"
    EU = "https://api-eu.libreview.io"
    EU2 = "https://api-eu2.libreview.io"
    AE = "https://api-ae.libreview.io"
    AP = "https://api-ap.libreview.io"
    AU = "https://api-au.libreview.io"
    CA = "https://api-ca.libreview.io"
    DE = "https://api-de.libreview.io"
    FR = "https://api-fr.libreview.io"
    JP = "https://api-jp.libreview.io"
    LA = "https://api-la.libreview.io"
    RU = "https://api.libreview.ru"

    @classmethod
    def from_name(cls, name: str) -> Region:
        """Look up a region by member name, ignoring case and surrounding whitespace."""
        try:
            return cls[name.strip().upper()]
        except KeyError:
            raise ValueError(f"Unknown LibreLinkUp region {name!r}") from None
```

`src/librelinkup_mcp/core/models.py`:

```python
"""Pydantic models for the LibreLinkUp payloads this server reads."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TIME_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.strptime(value, _TIME_FORMAT)


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="ignore")


class Patient(_Model):
    id: UUID
    patient_id: UUID = Field(alias="patientId")
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")


class Trend(IntEnum):
    UNKNOWN = 0
    DOWN_FAST = 1
    DOWN_SLOW = 2
    STABLE = 3
    UP_SLOW = 4
    UP_FAST = 5

    @property
    def indicator(self) -> str:
        return _ARROWS[self]


_ARROWS = {
    Trend.UNKNOWN: "?",
    Trend.DOWN_FAST: "↓",
    Trend.DOWN_SLOW: "↘",
    Trend.STABLE: "→",
    Trend.UP_SLOW: "↗",
    Trend.UP_FAST: "↑",
}


class GlucoseMeasurement(_Model):
    timestamp: datetime = Field(alias="Timestamp")  # sensor local time, no offset
    factory_timestamp: datetime = Field(alias="FactoryTimestamp")  # UTC
    value: float = Field(alias="Value")
    value_in_mg_per_dl: float = Field(alias="ValueInMgPerDl")
    glucose_units: int = Field(alias="GlucoseUnits")  # 1 = mg/dL, 0 = mmol/L
    is_high: bool = Field(alias="isHigh")
    is_low: bool = Field(alias="isLow")

    @field_validator("timestamp", mode="before")
    @classmethod
    def _parse_local(cls, value: Any) -> datetime:
        return _parse_time(value)

    @field_validator("factory_timestamp", mode="before")
    @classmethod
    def _parse_utc(cls, value: Any) -> datetime:
        return _parse_time(value).replace(tzinfo=UTC)


class GlucoseMeasurementWithTrend(GlucoseMeasurement):
    trend: Trend = Field(default=Trend.UNKNOWN, alias="TrendArrow")

    @field_validator("trend", mode="before")
    @classmethod
    def _parse_trend(cls, value: Any) -> Trend:
        try:
            return Trend(value)
        except (TypeError, ValueError):
            return Trend.UNKNOWN
```

`src/librelinkup_mcp/core/exceptions.py`:

```python
"""Errors raised by LibreLinkUpClient. Messages never contain names or readings."""

from __future__ import annotations


class LibreLinkUpError(Exception):
    """Base class for every client error."""


class AuthenticationError(LibreLinkUpError):
    """Credentials rejected, session expired, or no login yet."""


class RedirectError(LibreLinkUpError):
    """The account lives in another region; `region` is its upper-cased name."""

    def __init__(self, region: str) -> None:
        self.region = region
        super().__init__(f"Account belongs to region {region}")


class TermsOfUseError(LibreLinkUpError):
    """The account must accept updated terms of use in the app."""


class PrivacyPolicyError(LibreLinkUpError):
    """The account must accept an updated privacy policy in the app."""


class EmailVerificationError(LibreLinkUpError):
    """The account's email address is not verified."""


class RateLimitError(LibreLinkUpError):
    def __init__(self, retry_after: int | None) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited (retry after {retry_after})")


class PatientNotFoundError(LibreLinkUpError):
    """The API could not load the requested patient."""


class APIError(LibreLinkUpError):
    """Unexpected HTTP status, or a non-zero `status` in the response body."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"LibreLinkUp API error {status}")


class NetworkError(LibreLinkUpError):
    """Connection failure or timeout; `kind` is the transport error class name."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Network error: {kind}")


class ResponseShapeError(LibreLinkUpError):
    """A response did not have the expected shape; `call` names the client method."""

    def __init__(self, call: str) -> None:
        self.call = call
        super().__init__(f"Unexpected response shape from {call}")
```

`src/librelinkup_mcp/core/__init__.py`:

```python
"""In-house async client for the LibreLinkUp follower API."""

from librelinkup_mcp.core.exceptions import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    LibreLinkUpError,
    NetworkError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.models import (
    GlucoseMeasurement,
    GlucoseMeasurementWithTrend,
    Patient,
    Trend,
)
from librelinkup_mcp.core.regions import Region

__all__ = [
    "APIError",
    "AuthenticationError",
    "EmailVerificationError",
    "GlucoseMeasurement",
    "GlucoseMeasurementWithTrend",
    "LibreLinkUpError",
    "NetworkError",
    "Patient",
    "PatientNotFoundError",
    "PrivacyPolicyError",
    "RateLimitError",
    "RedirectError",
    "Region",
    "ResponseShapeError",
    "TermsOfUseError",
    "Trend",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `103 passed, 1 deselected`.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/core tests/core
git commit -m "feat(core): regions, models and exceptions for the in-house client

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Client login

**Files:**
- Create: `src/librelinkup_mcp/core/client.py` (login only; Task 3 adds the data calls), `tests/core/mock_api.py`, and `tests/core/fixtures/login_ok.json`, `login_redirect.json`, `login_terms.json`, `login_privacy.json`, `login_verify_email.json`, `login_bad_credentials.json`
- Test: `tests/core/test_client_login.py`

**Interfaces:**
- Consumes: Task 1's `Region` and exceptions.
- Produces:
  - `LibreLinkUpClient(email, password, region=Region.US, *, transport=None, timeout=15.0)` with `.region`, `async authenticate()`, `async aclose()`, and `async with` support.
  - The module constants `PRODUCT` and `VERSION`.
  - The private helpers `_send(method, path, *, json=None, headers=None)` and `_json_object(response, call)`, which Task 3 reuses.
  - Test helpers: `tests.core.mock_api.MockAPI` with `.on(method, path, *, status=200, json_body=None, text=None, headers=None, raises=None)`, `.transport()` and `.requests`, plus `fixture(name)`.

**Login order (from the spec):**
1. A transport error raises `NetworkError(class name)`.
2. HTTP 429 raises `RateLimitError`.
3. HTTP 401 raises `AuthenticationError`; any other non-2xx raises `APIError`.
4. `data.redirect` raises `RedirectError(region.upper())`.
5. `data.step.type` of `tou`, `pp` or `verifyEmail` raises the matching error.
6. A non-zero body `status` raises `AuthenticationError`.
7. A missing token or user id raises `ResponseShapeError("authenticate")`.

Step checks come before the status check because those responses carry `status: 4`.

- [ ] **Step 1: Write fixtures and the mock API helper**

`tests/core/fixtures/login_ok.json`:

```json
{
  "status": 0,
  "data": {
    "user": {"id": "follower-user-0001", "firstName": "Follower", "lastName": "Account"},
    "authTicket": {"token": "token-abc", "expires": 1790000000, "duration": 15552000000}
  }
}
```

`tests/core/fixtures/login_redirect.json`:

```json
{"status": 0, "data": {"redirect": true, "region": "eu2"}}
```

`tests/core/fixtures/login_terms.json`:

```json
{"status": 4, "data": {"step": {"type": "tou", "componentName": "AcceptDocument"}}}
```

`tests/core/fixtures/login_privacy.json`:

```json
{"status": 4, "data": {"step": {"type": "pp", "componentName": "AcceptDocument"}}}
```

`tests/core/fixtures/login_verify_email.json`:

```json
{"status": 4, "data": {"step": {"type": "verifyEmail", "componentName": "VerifyEmail"}}}
```

`tests/core/fixtures/login_bad_credentials.json`:

```json
{"status": 2, "error": {"message": "notAuthenticated"}}
```

`tests/core/mock_api.py`:

```python
"""A scriptable stand-in for the LibreLinkUp HTTP API, served through httpx2.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class MockAPI:
    """Route (method, path) to a canned reply; records every request it sees."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self._routes: dict[tuple[str, str], dict[str, Any]] = {}

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._routes[(method, path)] = {
            "status": status,
            "json_body": json_body,
            "text": text,
            "headers": headers or {},
            "raises": raises,
        }

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        route = self._routes[(request.method, request.url.path)]
        if route["raises"] is not None:
            raise route["raises"]
        if route["text"] is not None:
            return httpx2.Response(route["status"], text=route["text"], headers=route["headers"])
        return httpx2.Response(route["status"], json=route["json_body"], headers=route["headers"])
```

- [ ] **Step 2: Write the failing test**

`tests/core/test_client_login.py`:

```python
import json

import httpx2
import pytest

from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    Region,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.client import PRODUCT, VERSION, LibreLinkUpClient
from tests.core.mock_api import MockAPI, fixture

LOGIN = "/llu/auth/login"


def make_client(api: MockAPI, *, password: str = "pw", region: Region = Region.US):
    return LibreLinkUpClient("me@example.com", password, region, transport=api.transport())


async def test_login_posts_verbatim_credentials_with_app_headers():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_ok"))
    async with make_client(api, password=" pass word ", region=Region.EU2) as client:
        await client.authenticate()

    [request] = api.requests
    assert str(request.url) == "https://api-eu2.libreview.io/llu/auth/login"
    assert json.loads(request.content) == {"email": "me@example.com", "password": " pass word "}
    assert request.headers["product"] == PRODUCT == "llu.android"
    assert request.headers["version"] == VERSION
    assert "authorization" not in request.headers


async def test_redirect_carries_upper_cased_region():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_redirect"))
    async with make_client(api) as client:
        with pytest.raises(RedirectError) as info:
            await client.authenticate()
    assert info.value.region == "EU2"


@pytest.mark.parametrize(
    "name, error",
    [
        ("login_terms", TermsOfUseError),
        ("login_privacy", PrivacyPolicyError),
        ("login_verify_email", EmailVerificationError),
    ],
)
async def test_login_steps_raise_specific_errors(name, error):
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture(name))
    async with make_client(api) as client:
        with pytest.raises(error):
            await client.authenticate()


async def test_bad_credentials_body_status():
    api = MockAPI()
    api.on("POST", LOGIN, json_body=fixture("login_bad_credentials"))
    async with make_client(api) as client:
        with pytest.raises(AuthenticationError):
            await client.authenticate()


async def test_http_401_on_login():
    api = MockAPI()
    api.on("POST", LOGIN, status=401, json_body={"error": "Unauthorized"})
    async with make_client(api) as client:
        with pytest.raises(AuthenticationError):
            await client.authenticate()


@pytest.mark.parametrize("header, expected", [({"Retry-After": "30"}, 30), ({}, None)])
async def test_rate_limit_on_login(header, expected):
    api = MockAPI()
    api.on("POST", LOGIN, status=429, json_body={}, headers=header)
    async with make_client(api) as client:
        with pytest.raises(RateLimitError) as info:
            await client.authenticate()
    assert info.value.retry_after == expected


async def test_server_error_on_login():
    api = MockAPI()
    api.on("POST", LOGIN, status=503, text="unavailable")
    async with make_client(api) as client:
        with pytest.raises(APIError) as info:
            await client.authenticate()
    assert info.value.status == 503


@pytest.mark.parametrize(
    "exc, kind",
    [
        (httpx2.ConnectError("dns"), "ConnectError"),
        (httpx2.ReadTimeout("slow"), "ReadTimeout"),
    ],
)
async def test_network_errors_on_login(exc, kind):
    api = MockAPI()
    api.on("POST", LOGIN, raises=exc)
    async with make_client(api) as client:
        with pytest.raises(NetworkError) as info:
            await client.authenticate()
    assert info.value.kind == kind


@pytest.mark.parametrize(
    "body",
    [
        {"status": 0, "data": {"user": {"id": "u"}}},
        {"status": 0, "data": {"authTicket": {"token": "t"}}},
        {"status": 0},
        ["not", "an", "object"],
    ],
)
async def test_login_payload_missing_token_or_user(body):
    api = MockAPI()
    api.on("POST", LOGIN, json_body=body)
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError) as info:
            await client.authenticate()
    assert info.value.call == "authenticate"


async def test_login_non_json_body():
    api = MockAPI()
    api.on("POST", LOGIN, text="<html>maintenance</html>")
    async with make_client(api) as client:
        with pytest.raises(ResponseShapeError):
            await client.authenticate()


async def test_aclose_closes_http_client():
    client = make_client(MockAPI())
    await client.aclose()
    assert client._http.is_closed
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_client_login.py -q`
Expected: collection error, `No module named 'librelinkup_mcp.core.client'`.

- [ ] **Step 4: Implement login**

`src/librelinkup_mcp/core/client.py`:

```python
"""Async client for the LibreLinkUp follower API (login, connections, graph, logbook)."""

from __future__ import annotations

import hashlib
from typing import Any

import httpx2

from librelinkup_mcp.core.exceptions import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.regions import Region

# The API only answers requests that look like the official app. Bump VERSION
# when Abbott starts rejecting the current one.
PRODUCT = "llu.android"
VERSION = "4.16.0"

_BASE_HEADERS = {
    "accept-encoding": "gzip",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "product": PRODUCT,
    "version": VERSION,
}

_STEP_ERRORS: dict[str, type[Exception]] = {
    "tou": TermsOfUseError,
    "pp": PrivacyPolicyError,
    "verifyEmail": EmailVerificationError,
}


class LibreLinkUpClient:
    def __init__(
        self,
        email: str,
        password: str,
        region: Region = Region.US,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.region = region
        self._email = email
        self._password = password
        self._auth_headers: dict[str, str] | None = None
        self._http = httpx2.AsyncClient(
            base_url=region.value, headers=_BASE_HEADERS, transport=transport, timeout=timeout
        )

    async def __aenter__(self) -> LibreLinkUpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def authenticate(self) -> None:
        response = await self._send(
            "POST", "/llu/auth/login", json={"email": self._email, "password": self._password}
        )
        body = _json_object(response, "authenticate")
        data = body.get("data")
        if not isinstance(data, dict):
            data = {}

        if data.get("redirect"):
            raise RedirectError(str(data.get("region", "")).upper())
        step = data.get("step")
        step_type = step.get("type") if isinstance(step, dict) else None
        if step_type in _STEP_ERRORS:
            raise _STEP_ERRORS[step_type]()
        if body.get("status", 0) != 0:
            raise AuthenticationError("LibreLinkUp rejected the credentials")

        try:
            token = data["authTicket"]["token"]
            user_id = data["user"]["id"]
        except (KeyError, TypeError):
            raise ResponseShapeError("authenticate") from None
        if not token or not user_id:
            raise ResponseShapeError("authenticate")
        self._auth_headers = {
            "authorization": f"Bearer {token}",
            "account-id": hashlib.sha256(str(user_id).encode()).hexdigest(),
        }

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        try:
            response = await self._http.request(method, path, json=json, headers=headers)
        except httpx2.TransportError as exc:
            raise NetworkError(type(exc).__name__) from exc
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise RateLimitError(int(retry_after) if retry_after.isdigit() else None)
        if response.status_code == 401:
            raise AuthenticationError("LibreLinkUp returned HTTP 401")
        if not response.is_success:
            raise APIError(response.status_code)
        return response


def _json_object(response: httpx2.Response, call: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ResponseShapeError(call) from None
    if not isinstance(body, dict):
        raise ResponseShapeError(call)
    return body
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `121 passed, 1 deselected`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/core/client.py tests/core
git commit -m "feat(core): async LibreLinkUp login

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Client data calls

**Files:**
- Modify: `src/librelinkup_mcp/core/client.py` (replace it with the full version below; login is unchanged)
- Create: `tests/core/fixtures/connections.json`, `graph.json`, `logbook.json`, `patient_not_found.json`
- Test: `tests/core/test_client_data.py`

**Interfaces:**
- Consumes: Task 2's client and `MockAPI`.
- Produces: the async methods `get_patients() -> list[Patient]`, `latest(patient_id: UUID) -> GlucoseMeasurementWithTrend`, `graph(patient_id: UUID) -> list[GlucoseMeasurement]` and `logbook(patient_id: UUID) -> list[GlucoseMeasurement]`. Every failure raises a core exception; a missing key, a wrong type or a `ValidationError` becomes `ResponseShapeError(<method name>)`.

- [ ] **Step 1: Write fixtures**

`tests/core/fixtures/connections.json`:

```json
{
  "status": 0,
  "data": [
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "patientId": "22222222-2222-2222-2222-222222222222",
      "firstName": "Ann",
      "lastName": "Lee",
      "targetLow": 70,
      "targetHigh": 180
    }
  ]
}
```

`tests/core/fixtures/graph.json`:

```json
{
  "status": 0,
  "data": {
    "connection": {
      "id": "11111111-1111-1111-1111-111111111111",
      "patientId": "22222222-2222-2222-2222-222222222222",
      "firstName": "Ann",
      "lastName": "Lee",
      "glucoseMeasurement": {
        "FactoryTimestamp": "9/26/2026 1:05:00 PM",
        "Timestamp": "9/26/2026 3:05:00 PM",
        "type": 1,
        "ValueInMgPerDl": 115,
        "TrendArrow": 3,
        "TrendMessage": null,
        "MeasurementColor": 1,
        "GlucoseUnits": 1,
        "Value": 115,
        "isHigh": false,
        "isLow": false
      }
    },
    "activeSensors": [],
    "graphData": [
      {
        "FactoryTimestamp": "9/26/2026 12:45:00 PM",
        "Timestamp": "9/26/2026 2:45:00 PM",
        "type": 0,
        "ValueInMgPerDl": 110,
        "MeasurementColor": 1,
        "GlucoseUnits": 1,
        "Value": 110,
        "isHigh": false,
        "isLow": false
      },
      {
        "FactoryTimestamp": "9/26/2026 1:00:00 PM",
        "Timestamp": "9/26/2026 3:00:00 PM",
        "type": 0,
        "ValueInMgPerDl": 120,
        "MeasurementColor": 1,
        "GlucoseUnits": 1,
        "Value": 120,
        "isHigh": false,
        "isLow": false
      }
    ]
  },
  "ticket": {"token": "token-refreshed", "expires": 1790000000, "duration": 15552000000}
}
```

`tests/core/fixtures/logbook.json`:

```json
{
  "status": 0,
  "data": [
    {
      "FactoryTimestamp": "9/20/2026 1:00:00 AM",
      "Timestamp": "9/20/2026 3:00:00 AM",
      "type": 2,
      "ValueInMgPerDl": 62,
      "TrendArrow": 2,
      "MeasurementColor": 3,
      "GlucoseUnits": 1,
      "Value": 62,
      "isHigh": false,
      "isLow": true
    }
  ],
  "ticket": {"token": "token-refreshed", "expires": 1790000000, "duration": 15552000000}
}
```

`tests/core/fixtures/patient_not_found.json`:

```json
{"status": 4, "error": {"message": "couldNotLoadPatient"}}
```

- [ ] **Step 2: Write the failing test**

`tests/core/test_client_data.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_client_data.py -q`
Expected: `17 failed`. Most fail with `AttributeError: 'LibreLinkUpClient' object has no attribute 'get_patients'` (or `latest`, `graph`, `logbook`).

- [ ] **Step 4: Replace `client.py` with the full implementation**

`src/librelinkup_mcp/core/client.py`:

```python
"""Async client for the LibreLinkUp follower API (login, connections, graph, logbook)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID

import httpx2
from pydantic import TypeAdapter, ValidationError

from librelinkup_mcp.core.exceptions import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.core.models import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient
from librelinkup_mcp.core.regions import Region

# The API only answers requests that look like the official app. Bump VERSION
# when Abbott starts rejecting the current one.
PRODUCT = "llu.android"
VERSION = "4.16.0"

_BASE_HEADERS = {
    "accept-encoding": "gzip",
    "cache-control": "no-cache",
    "content-type": "application/json",
    "product": PRODUCT,
    "version": VERSION,
}

_STEP_ERRORS: dict[str, type[Exception]] = {
    "tou": TermsOfUseError,
    "pp": PrivacyPolicyError,
    "verifyEmail": EmailVerificationError,
}

_PATIENTS = TypeAdapter(list[Patient])
_MEASUREMENTS = TypeAdapter(list[GlucoseMeasurement])

T = TypeVar("T")


class LibreLinkUpClient:
    def __init__(
        self,
        email: str,
        password: str,
        region: Region = Region.US,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.region = region
        self._email = email
        self._password = password
        self._auth_headers: dict[str, str] | None = None
        self._http = httpx2.AsyncClient(
            base_url=region.value, headers=_BASE_HEADERS, transport=transport, timeout=timeout
        )

    async def __aenter__(self) -> LibreLinkUpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def authenticate(self) -> None:
        response = await self._send(
            "POST", "/llu/auth/login", json={"email": self._email, "password": self._password}
        )
        body = _json_object(response, "authenticate")
        data = body.get("data")
        if not isinstance(data, dict):
            data = {}

        if data.get("redirect"):
            raise RedirectError(str(data.get("region", "")).upper())
        step = data.get("step")
        step_type = step.get("type") if isinstance(step, dict) else None
        if step_type in _STEP_ERRORS:
            raise _STEP_ERRORS[step_type]()
        if body.get("status", 0) != 0:
            raise AuthenticationError("LibreLinkUp rejected the credentials")

        try:
            token = data["authTicket"]["token"]
            user_id = data["user"]["id"]
        except (KeyError, TypeError):
            raise ResponseShapeError("authenticate") from None
        if not token or not user_id:
            raise ResponseShapeError("authenticate")
        self._auth_headers = {
            "authorization": f"Bearer {token}",
            "account-id": hashlib.sha256(str(user_id).encode()).hexdigest(),
        }

    async def get_patients(self) -> list[Patient]:
        data = await self._get_data("/llu/connections", "get_patients")
        return _parse("get_patients", lambda: _PATIENTS.validate_python(data))

    async def latest(self, patient_id: UUID) -> GlucoseMeasurementWithTrend:
        data = await self._get_data(f"/llu/connections/{patient_id}/graph", "latest")
        return _parse(
            "latest",
            lambda: GlucoseMeasurementWithTrend.model_validate(
                data["connection"]["glucoseMeasurement"]
            ),
        )

    async def graph(self, patient_id: UUID) -> list[GlucoseMeasurement]:
        data = await self._get_data(f"/llu/connections/{patient_id}/graph", "graph")
        return _parse("graph", lambda: _MEASUREMENTS.validate_python(data["graphData"]))

    async def logbook(self, patient_id: UUID) -> list[GlucoseMeasurement]:
        data = await self._get_data(f"/llu/connections/{patient_id}/logbook", "logbook")
        return _parse("logbook", lambda: _MEASUREMENTS.validate_python(data))

    async def _get_data(self, path: str, call: str) -> Any:
        if self._auth_headers is None:
            raise AuthenticationError("Not logged in")
        response = await self._send("GET", path, headers=self._auth_headers)
        body = _json_object(response, call)
        status = body.get("status", 0)
        if status != 0:
            error = body.get("error")
            if isinstance(error, dict) and error.get("message") == "couldNotLoadPatient":
                raise PatientNotFoundError()
            raise APIError(status if isinstance(status, int) else 0)
        return body.get("data")

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        try:
            response = await self._http.request(method, path, json=json, headers=headers)
        except httpx2.TransportError as exc:
            raise NetworkError(type(exc).__name__) from exc
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise RateLimitError(int(retry_after) if retry_after.isdigit() else None)
        if response.status_code == 401:
            raise AuthenticationError("LibreLinkUp returned HTTP 401")
        if not response.is_success:
            raise APIError(response.status_code)
        return response


def _json_object(response: httpx2.Response, call: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ResponseShapeError(call) from None
    if not isinstance(body, dict):
        raise ResponseShapeError(call)
    return body


def _parse(call: str, build: Callable[[], T]) -> T:
    try:
        return build()
    except (ValidationError, KeyError, TypeError):
        raise ResponseShapeError(call) from None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `138 passed, 1 deselected`.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/librelinkup_mcp/core/client.py tests/core
git commit -m "feat(core): connections, graph and logbook calls

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Switch the server to the core client and drop pylibrelinkup

**Files:**
- Create: `tests/test_no_pylibrelinkup.py`
- Modify (full contents below): `tests/factories.py`, `tests/fakes.py`, `tests/test_config.py`, `tests/test_service.py`, `tests/test_server.py`, `tests/test_live.py`, `src/librelinkup_mcp/config.py`, `src/librelinkup_mcp/formatting.py`, `src/librelinkup_mcp/service.py`, `src/librelinkup_mcp/server.py`, `pyproject.toml`
- Modify: `uv.lock` (regenerated) and `README.md` (one paragraph)

**Interfaces:**
- Consumes: everything in `librelinkup_mcp.core`.
- Produces:
  - `Settings.region: Region`.
  - `server.build_client(settings) -> LibreLinkUpClient`. The `LoginArgs` password workaround is gone, because the core client sends the password verbatim.
  - The `GlucoseService.LibreClient` Protocol is now async.
  - The new ToolError message `LibreLinkUp returned unexpected data for <call>.`

**Behaviour notes:**
- **Re-login:** `_call_with_reauth` retries only on `AuthenticationError`, since the client already maps HTTP 401 to it, so the old `_is_auth_failure` helper goes away.
- **Second failure:** a second auth failure now surfaces as the login-failed message.
- **Test fake:** `FakeLibreClient` becomes async, and its `auth_delay` uses `asyncio.sleep`, so the concurrent-login test still proves the lock.

- [ ] **Step 1: Write the guard test and update the existing tests**

`tests/test_no_pylibrelinkup.py`:

```python
"""The server must run on its own LibreLinkUp client: no pylibrelinkup, no requests."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
FORBIDDEN = re.compile(r"^\s*(?:import|from)\s+(pylibrelinkup|requests)\b", re.MULTILINE)


def test_src_does_not_import_pylibrelinkup_or_requests():
    offenders = [
        f"{path.relative_to(SRC)}: {match.group(1)}"
        for path in sorted(SRC.rglob("*.py"))
        for match in FORBIDDEN.finditer(path.read_text())
    ]
    assert offenders == []
```

`tests/factories.py`:

```python
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
```

`tests/fakes.py`:

```python
"""A scriptable stand-in for librelinkup_mcp.core.client.LibreLinkUpClient."""

from __future__ import annotations

import asyncio
from uuid import UUID

from tests.factories import make_current, make_measurement


class FakeLibreClient:
    """Records calls; `fail_next[method]` holds exceptions to raise, one per call."""

    def __init__(self, patients, *, auth_delay: float = 0.0):
        self.patients = list(patients)
        self.auth_delay = auth_delay
        self.calls: list[tuple[str, UUID | None]] = []
        self.fail_next: dict[str, list[Exception]] = {}

    def _record(self, method: str, patient_id: UUID | None = None) -> None:
        self.calls.append((method, patient_id))
        queue = self.fail_next.get(method)
        if queue:
            raise queue.pop(0)

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    async def authenticate(self) -> None:
        if self.auth_delay:
            await asyncio.sleep(self.auth_delay)
        self._record("authenticate")

    async def get_patients(self):
        self._record("get_patients")
        return list(self.patients)

    async def latest(self, patient_id):
        self._record("latest", patient_id)
        return make_current("9/26/2026 7:05:00 AM", 115, trend=3)

    async def graph(self, patient_id):
        self._record("graph", patient_id)
        return [
            make_measurement("9/26/2026 7:00:00 AM", 120),
            make_measurement("9/26/2026 6:45:00 AM", 110),
        ]

    async def logbook(self, patient_id):
        self._record("logbook", patient_id)
        return [make_measurement("9/20/2026 3:00:00 AM", 62)]
```

`tests/test_config.py`:

```python
import pytest

from librelinkup_mcp.config import ConfigError, load_settings
from librelinkup_mcp.core import Region

CREDS = {"LIBRELINKUP_EMAIL": "me@example.com", "LIBRELINKUP_PASSWORD": "s3cret"}


def test_minimal_env_uses_defaults():
    settings = load_settings(CREDS)
    assert settings.email == "me@example.com"
    assert settings.password == "s3cret"
    assert settings.region is Region.US
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
    "raw, expected", [("eu", Region.EU), (" EU2 ", Region.EU2), ("", Region.US)]
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

`tests/test_service.py`:

```python
import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    NetworkError,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)
from librelinkup_mcp.service import GlucoseService
from tests.factories import ANN, BOB
from tests.fakes import FakeLibreClient


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


async def test_expired_session_reauthenticates_and_retries():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.list_patients()

    client.fail_next["graph"] = [AuthenticationError("LibreLinkUp returned HTTP 401")]
    _, readings = await service.graph(None)

    assert len(readings) == 2
    assert client.count("authenticate") == 2
    assert client.count("graph") == 2


async def test_second_auth_failure_is_surfaced():
    client = FakeLibreClient([ANN])
    service = GlucoseService(client)
    await service.list_patients()

    client.fail_next["graph"] = [AuthenticationError("401"), AuthenticationError("401")]
    with pytest.raises(ToolError, match="LibreLinkUp login failed"):
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
        (RedirectError("EU"), "belongs to region EU. Set LIBRELINKUP_REGION=EU."),
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
        (RateLimitError(30), "Try again in 30 seconds."),
        (RateLimitError(None), "Try again later."),
        (PatientNotFoundError(), "LibreLinkUp reports patient not found."),
        (APIError(500), "LibreLinkUp API error 500."),
        (APIError(911), "LibreLinkUp API error 911."),
        (NetworkError("ConnectError"), "Could not reach LibreLinkUp: ConnectError."),
        (NetworkError("ReadTimeout"), "Could not reach LibreLinkUp: ReadTimeout."),
        (ResponseShapeError("latest"), "LibreLinkUp returned unexpected data for latest."),
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
    client.fail_next["get_patients"] = [AuthenticationError("LibreLinkUp returned HTTP 401")]
    patient, _ = await service.current("Bob")  # cache miss -> refresh -> 401 -> re-auth

    assert patient is BOB
    assert client.count("authenticate") == 2
```

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


def test_build_client_uses_settings():
    from librelinkup_mcp.config import load_settings
    from librelinkup_mcp.core import Region
    from librelinkup_mcp.core.client import LibreLinkUpClient

    settings = load_settings(
        {
            "LIBRELINKUP_EMAIL": "me@example.com",
            "LIBRELINKUP_PASSWORD": " pass word ",
            "LIBRELINKUP_REGION": "EU",
        }
    )
    client = server.build_client(settings)
    assert isinstance(client, LibreLinkUpClient)
    assert client.region is Region.EU
```

`tests/test_live.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q`
Expected: `36 failed, 102 passed, 1 deselected`. The failures are in `test_config.py` (`Region` vs `APIUrl`), `test_formatting.py` (factories now build core models), `test_server.py`, `test_service.py` (async fake vs `to_thread`, and core exception types), and the guard test.

- [ ] **Step 3: Switch the source modules**

`src/librelinkup_mcp/config.py`:

```python
"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from librelinkup_mcp.core.regions import Region

_TRUTHY = {"true", "1", "yes"}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    email: str
    password: str = field(repr=False)
    region: Region
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
        region = Region.from_name(region_name)
    except ValueError:
        valid = ", ".join(member.name for member in Region)
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

`src/librelinkup_mcp/formatting.py`:

```python
"""Convert core models into JSON-serialisable dicts for tool results."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from librelinkup_mcp.core import GlucoseMeasurement, GlucoseMeasurementWithTrend, Patient

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
        "timestamp_utc": measurement.factory_timestamp.isoformat(),
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


def current_response(
    patient: Patient,
    measurement: GlucoseMeasurementWithTrend,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    reading = measurement_to_dict(measurement)
    elapsed = (now or datetime.now(UTC)) - measurement.factory_timestamp
    reading["age_minutes"] = int(elapsed.total_seconds() // 60)
    return {"patient": patient_to_dict(patient), "reading": reading}


def readings_response(
    patient: Patient, measurements: Iterable[GlucoseMeasurement]
) -> dict[str, Any]:
    ordered = sorted(measurements, key=lambda m: m.factory_timestamp)
    return {
        "patient": patient_to_dict(patient),
        "count": len(ordered),
        "readings": [measurement_to_dict(m) for m in ordered],
    }
```

`src/librelinkup_mcp/service.py`:

```python
"""GlucoseService: patient lookup, lazy login and error mapping over the LibreLinkUp client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeVar
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError

from librelinkup_mcp import tracing
from librelinkup_mcp.core import (
    APIError,
    AuthenticationError,
    EmailVerificationError,
    GlucoseMeasurement,
    GlucoseMeasurementWithTrend,
    NetworkError,
    Patient,
    PatientNotFoundError,
    PrivacyPolicyError,
    RateLimitError,
    RedirectError,
    ResponseShapeError,
    TermsOfUseError,
)

T = TypeVar("T")


class LibreClient(Protocol):
    """The subset of core.client.LibreLinkUpClient that GlucoseService uses."""

    async def authenticate(self) -> None: ...
    async def get_patients(self) -> list[Patient]: ...
    async def latest(self, patient_id: UUID) -> GlucoseMeasurementWithTrend: ...
    async def graph(self, patient_id: UUID) -> list[GlucoseMeasurement]: ...
    async def logbook(self, patient_id: UUID) -> list[GlucoseMeasurement]: ...


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


def _to_tool_error(exc: Exception) -> ToolError | None:
    """Translate a LibreLinkUp client error into a user-facing ToolError."""
    if isinstance(exc, AuthenticationError):
        return ToolError(
            "LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD."
        )
    if isinstance(exc, RedirectError):
        return ToolError(
            f"This account belongs to region {exc.region}. Set LIBRELINKUP_REGION={exc.region}."
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
    if isinstance(exc, RateLimitError):
        wait = f"in {exc.retry_after} seconds" if exc.retry_after is not None else "later"
        return ToolError(f"Rate limited by LibreLinkUp. Try again {wait}.")
    if isinstance(exc, PatientNotFoundError):
        return ToolError("LibreLinkUp reports patient not found.")
    if isinstance(exc, APIError):
        return ToolError(f"LibreLinkUp API error {exc.status}.")
    if isinstance(exc, NetworkError):
        return ToolError(f"Could not reach LibreLinkUp: {exc.kind}.")
    if isinstance(exc, ResponseShapeError):
        return ToolError(f"LibreLinkUp returned unexpected data for {exc.call}.")
    return None


class GlucoseService:
    """Lazy login, re-login on expiry, and patient lookup over a LibreLinkUp client."""

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
            await self._client.authenticate()
            self._authenticated = True

    async def _request(
        self, method: str, fn: Callable[..., Awaitable[T]], patient: Patient | None = None
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

    async def _call_with_reauth(self, fn: Callable[..., Awaitable[T]], *args: object) -> T:
        await self._authenticate(force=False)
        try:
            return await fn(*args)
        except AuthenticationError:
            pass  # token expired: log in again and retry once
        await self._authenticate(force=True)
        return await fn(*args)
```

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

from librelinkup_mcp import formatting, tracing
from librelinkup_mcp.config import ConfigError, Settings, load_settings
from librelinkup_mcp.core.client import LibreLinkUpClient
from librelinkup_mcp.service import GlucoseService

mcp = MCPServer(
    "librelinkup",
    instructions=(
        "Read-only access to FreeStyle Libre CGM glucose readings shared through LibreLinkUp. "
        "Values are reported in the account's unit (mg/dL or mmol/L) and also in mg/dL. "
        "`timestamp` is the sensor's local time; `timestamp_utc` is UTC."
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
    """Most recent glucose reading with its trend arrow.

    Check `age_minutes`: if the sensor or phone is out of range, this can be an old reading.
    """
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


def build_client(settings: Settings) -> LibreLinkUpClient:
    return LibreLinkUpClient(settings.email, settings.password, settings.region)


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
    set_service(GlucoseService(build_client(settings)))
    mcp.run("stdio")
```

`pyproject.toml`:

```toml
[project]
name = "librelinkup-mcp"
version = "0.1.0"
description = "MCP server exposing FreeStyle Libre glucose readings from LibreLinkUp"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "httpx2>=2.5,<3",
    "mcp>=2.2,<3",
    "pydantic>=2.12,<3",
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

- [ ] **Step 4: Re-lock and check the old packages are gone**

Run: `uv lock && uv sync && grep -c 'name = "pylibrelinkup"\|name = "requests"' uv.lock`
Expected: the lock succeeds and the count prints `0`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: `138 passed, 1 deselected`.

- [ ] **Step 6: Update the README intro**

In `README.md`, replace:

```markdown
An MCP server that gives Claude (or any MCP client) read-only access to FreeStyle Libre
CGM glucose readings shared through LibreLinkUp. Built on
[pylibrelinkup](https://github.com/robberwick/pylibrelinkup).
```

with:

```markdown
An MCP server that gives Claude (or any MCP client) read-only access to FreeStyle Libre
CGM glucose readings shared through LibreLinkUp. It talks to the LibreLinkUp API with its
own small async client (`librelinkup_mcp.core`); the API behaviour it relies on follows
[pylibrelinkup](https://github.com/robberwick/pylibrelinkup).
```

- [ ] **Step 7: Final verification**

Run: `uv sync --extra langfuse && uv run pytest -q && uv sync`
Expected: `138 passed, 1 deselected`, which proves the tracing extra still works.

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pytest -q`
Expected: `All checks passed!`, no files to reformat, and `138 passed, 1 deselected`.

Run: `env -u LIBRELINKUP_EMAIL -u LIBRELINKUP_PASSWORD uv run pytest -m live -q -rs`
Expected: `1 skipped`, which proves the live test still imports cleanly.

- [ ] **Step 8: Commit**

```bash
git add tests src pyproject.toml uv.lock README.md
git commit -m "refactor: run on the in-house core client; drop pylibrelinkup and requests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9 (manual, for the user): live check**

With real credentials exported, run `uv run pytest -m live -q`, expecting `1 passed`. This is the first time the new client talks to the real API.
