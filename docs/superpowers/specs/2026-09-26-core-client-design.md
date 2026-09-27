# librelinkup-mcp core client — Design

Date: 2026-09-26
Status: Draft for review
Supersedes: every pylibrelinkup reference in
`2026-09-26-librelinkup-mcp-design.md` (tool behaviour, config, tracing and
error messages in that spec still apply).

## Goal

Replace the `pylibrelinkup` dependency with an in-house async LibreLinkUp
client in `src/librelinkup_mcp/core/`, written from the API's observed
behaviour.

Why: (A) fewer dependencies — `httpx2` and `pydantic` are already installed
by `mcp`, so the client adds no packages and removes `pylibrelinkup` and
`requests`; (C) async end to end — no `asyncio.to_thread`.

Success: the full offline suite and `pytest -m live` pass with no
`pylibrelinkup` or `requests` import anywhere under `src/`; MCP tool names,
arguments and output shapes are unchanged.

## Decisions

- Minimal client: only login, connections, graph, logbook. No hardware,
  alarm rules, or other endpoints.
- Written fresh from API behaviour; pylibrelinkup's code and fixture files
  are not copied. README credits pylibrelinkup as the reference.
- Package lives at `src/librelinkup_mcp/core/` (not a top-level `core`).
- HTTP via `httpx2.AsyncClient` (import name `httpx2`), models via pydantic.
  Both become explicit dependencies in `pyproject.toml`.
- The `ticket` refresh in graph/logbook responses is ignored; token expiry is
  handled by the service's existing re-login-once-on-auth-error rule.

## Out of scope

Token refresh from `ticket`, endpoints beyond the four above, login backoff,
caching.

## Layout

```
src/librelinkup_mcp/core/
├── __init__.py     # re-exports public names
├── regions.py      # Region
├── models.py       # Patient, Trend, GlucoseMeasurement, GlucoseMeasurementWithTrend
├── exceptions.py   # LibreLinkUpError hierarchy
└── client.py       # LibreLinkUpClient
```

### `regions.py`

`Region(StrEnum)` with members and base URLs:

| Member | URL |
|---|---|
| US | `https://api.libreview.io` |
| EU | `https://api-eu.libreview.io` |
| EU2 | `https://api-eu2.libreview.io` |
| AE | `https://api-ae.libreview.io` |
| AP | `https://api-ap.libreview.io` |
| AU | `https://api-au.libreview.io` |
| CA | `https://api-ca.libreview.io` |
| DE | `https://api-de.libreview.io` |
| FR | `https://api-fr.libreview.io` |
| JP | `https://api-jp.libreview.io` |
| LA | `https://api-la.libreview.io` |
| RU | `https://api.libreview.ru` |

`Region.from_name(name: str) -> Region`: case-insensitive member-name lookup,
raises `ValueError` otherwise. `config.py` uses this instead of
`APIUrl.from_string`; `Settings.region` becomes `Region`.

### `models.py`

Pydantic models reading the API's JSON keys; only fields the server uses.

- `Patient`: `id: UUID` (key `id`), `patient_id: UUID` (`patientId`),
  `first_name: str` (`firstName`), `last_name: str` (`lastName`). Whitespace
  stripped from names.
- `Trend(IntEnum)`: `UNKNOWN=0, DOWN_FAST=1, DOWN_SLOW=2, STABLE=3, UP_SLOW=4,
  UP_FAST=5`; property `indicator` → `? ↓ ↘ → ↗ ↑`. Any other integer, or a
  missing value, parses as `UNKNOWN`.
- `GlucoseMeasurement`: `timestamp: datetime` (`Timestamp`, naive local),
  `factory_timestamp: datetime` (`FactoryTimestamp`, tz-aware UTC),
  `value: float` (`Value`), `value_in_mg_per_dl: float` (`ValueInMgPerDl`),
  `glucose_units: int` (`GlucoseUnits`; 1 = mg/dL, 0 = mmol/L),
  `is_high: bool` (`isHigh`), `is_low: bool` (`isLow`). Timestamps parse
  with `%m/%d/%Y %I:%M:%S %p`.
- `GlucoseMeasurementWithTrend(GlucoseMeasurement)`: adds `trend: Trend`
  (`TrendArrow`).

Field names match the pylibrelinkup attributes the server already reads, so
`formatting.py` changes only its import.

### `exceptions.py`

```
LibreLinkUpError
├── AuthenticationError
├── RedirectError(region: str)          # upper-cased region name from the API
├── TermsOfUseError
├── PrivacyPolicyError
├── EmailVerificationError
├── RateLimitError(retry_after: int | None)
├── PatientNotFoundError
├── APIError(status: int)               # HTTP status or non-zero body status
├── NetworkError(kind: str)             # httpx2 transport error class name
└── ResponseShapeError(call: str)       # pydantic ValidationError, e.g. call="get_patients"
```

### `client.py`

```python
class LibreLinkUpClient:
    def __init__(self, email: str, password: str, region: Region = Region.US,
                 *, transport: httpx2.AsyncBaseTransport | None = None,
                 timeout: float = 15.0) -> None
    async def authenticate(self) -> None
    async def get_patients(self) -> list[Patient]
    async def latest(self, patient_id: UUID) -> GlucoseMeasurementWithTrend
    async def graph(self, patient_id: UUID) -> list[GlucoseMeasurement]
    async def logbook(self, patient_id: UUID) -> list[GlucoseMeasurement]
    async def aclose(self) -> None
    async def __aenter__(self) -> LibreLinkUpClient
    async def __aexit__(self, *exc) -> None
```

Module constants: `PRODUCT = "llu.android"`, `VERSION = "4.16.0"`.

Every request sends `accept-encoding: gzip`, `cache-control: no-cache`,
`content-type: application/json`, `product`, `version`. After login, also
`authorization: Bearer <token>` and `account-id: <sha256 hex of user id>`.

**Login** — `POST {region}/llu/auth/login`, JSON `{"email", "password"}`
(password sent verbatim). Checked in order:

1. httpx2 transport error / timeout → `NetworkError(<class name>)`.
2. HTTP 429 → `RateLimitError(int(Retry-After) if it is all digits else None)`.
3. HTTP 401 → `AuthenticationError`; other non-2xx → `APIError(http status)`.
4. `data.redirect` true → `RedirectError(data.region.upper())`.
5. `data.step.type` `tou` / `pp` / `verifyEmail` → `TermsOfUseError` /
   `PrivacyPolicyError` / `EmailVerificationError`.
6. Body `status` 2 (wrong email/password) → `AuthenticationError`; any other
   non-zero status (e.g. a minimum-app-version rejection) → `APIError(status)`.
7. Read `data.authTicket.token` and `data.user.id`; missing →
   `ResponseShapeError("authenticate")`. Store token and account-id hash.

**Data calls** — `GET {region}/llu/connections`,
`/llu/connections/{patient_id}/graph` (for `latest` and `graph`),
`/llu/connections/{patient_id}/logbook`.

1. No token → `AuthenticationError` without sending a request.
2. Transport error, 429, non-2xx as in login; HTTP 401 → `AuthenticationError`.
3. Body `status` non-zero: `error.message == "couldNotLoadPatient"` →
   `PatientNotFoundError`; otherwise `APIError(body status)`.
4. Parse: connections → `data` list of `Patient`; latest →
   `data.connection.glucoseMeasurement`; graph → `data.graphData` list;
   logbook → `data` list. Pydantic `ValidationError` or a missing key →
   `ResponseShapeError(<method name>)`.

## Changes to existing modules

- `config.py`: `Region` instead of `APIUrl`; error text unchanged.
- `formatting.py`: imports models from `librelinkup_mcp.core`.
- `service.py`: `LibreClient` Protocol becomes async; `asyncio.to_thread`
  removed; `_is_auth_failure` is `isinstance(exc, AuthenticationError)`;
  `_to_tool_error` maps the new exceptions:

| Exception | Message (unchanged unless noted) |
|---|---|
| `AuthenticationError` | "LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD." |
| `RedirectError` | "This account belongs to region {region}. Set LIBRELINKUP_REGION={region}." |
| `TermsOfUseError` / `PrivacyPolicyError` / `EmailVerificationError` | as before |
| `RateLimitError` | as before |
| `PatientNotFoundError` | as before |
| `APIError` | "LibreLinkUp API error {status}." |
| `NetworkError` | "Could not reach LibreLinkUp: {kind}." |
| `ResponseShapeError` | **new:** "LibreLinkUp returned unexpected data for {call}." |

- `server.py`: `build_client(settings) -> LibreLinkUpClient`; the
  `LoginArgs` workaround is removed. The client is not closed explicitly:
  `mcp.run()` owns and closes the event loop, and process exit releases the
  sockets. `aclose()` / `async with` exist for tests and other callers.
- `pyproject.toml`: remove `pylibrelinkup`; add `httpx2>=2.5,<3` and
  `pydantic>=2.12,<3`; re-lock.
- README: remove pylibrelinkup from the intro; add "API behaviour follows
  [pylibrelinkup](https://github.com/robberwick/pylibrelinkup)" credit.

## Testing

All offline except the existing live test.

- `tests/core/fixtures/*.json`: hand-written payloads in the API's shape —
  login ok, redirect, terms of use, privacy policy, email verification, bad
  credentials, connections, graph, logbook, patient not found.
- `tests/core/test_regions.py`: `from_name` case-insensitivity and error.
- `tests/core/test_models.py`: timestamp parsing, `Trend` unknown/missing →
  `UNKNOWN`, mmol/L fields, name stripping.
- `tests/core/test_client.py` with `httpx2.MockTransport`, asserting requests
  as well as responses: login URL per region, verbatim password in body,
  `product`/`version` headers, `authorization` and `account-id` on later
  calls; every login branch 1–7 and data-call branch 1–4; `aclose` closes the
  underlying client.
- Existing tests updated: factories build `core.models`; `FakeLibreClient`
  async (`asyncio.sleep` for the concurrent-login test); service error table
  uses core exceptions plus `ResponseShapeError`; `build_client` test checks
  type and region.
- `tests/test_no_pylibrelinkup.py`: fails if any file under `src/` imports
  `pylibrelinkup` or `requests`.

## Migration order

Each step leaves the suite green:

1. `core/regions.py`, `models.py`, `exceptions.py` + tests.
2. `core/client.py` login + tests.
3. `core/client.py` data calls + tests.
4. Switch `config`, `formatting`, `service`, `server` and existing tests to
   `core`; drop `pylibrelinkup`; re-lock; guard test; README.
