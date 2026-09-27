# librelinkup-mcp — Design

Date: 2026-09-26
Status: Draft for review

## Goal

A Python MCP server that lets an MCP client (Claude Desktop, Claude Code) read
FreeStyle Libre CGM data from a LibreLinkUp follower account, built directly on
[pylibrelinkup](https://github.com/robberwick/pylibrelinkup).

Uses: personal questions ("what's my glucose now?"), caregiver check-ins on a
followed person, and longer-range review of recent history.

Success: user adds the server to their MCP client config with credentials in
env vars, asks "what's my glucose right now?" or "show me last night's
readings", and gets correct answers with no further setup.

## Decisions

- Server returns **readings only**. No server-side statistics (averages,
  time-in-range, GMI) and no pattern detection; the model reasons over raw data.
- **Multiple followed patients** supported; the only patient is the default.
- **stdio transport**, local process.
- **Credentials from environment variables only**, never tool arguments.
- **Read-only.**
- **Official `mcp` Python SDK, FastMCP API.** Not the low-level `Server` API,
  not the standalone `fastmcp` v2 package.
- **Optional Langfuse tracing**, metadata-only by default, readings captured
  only when explicitly enabled.

## Out of scope (v1)

Computed statistics, pattern detection, HTTP/SSE transport, write operations,
caching of readings, automatic retry on rate limits, automatic region switching.

## Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LIBRELINKUP_EMAIL` | yes | — | Follower account email |
| `LIBRELINKUP_PASSWORD` | yes | — | Follower account password |
| `LIBRELINKUP_REGION` | no | `US` | `APIUrl` member name, case-insensitive (`US`, `EU`, `EU2`, `AE`, `AP`, `AU`, `CA`, `DE`, `FR`, `JP`, `LA`, `RU`) |
| `LANGFUSE_PUBLIC_KEY` | no | — | Enables tracing when set together with secret key |
| `LANGFUSE_SECRET_KEY` | no | — | See above |
| `LANGFUSE_HOST` | no | Langfuse SDK default | Self-hosted or regional Langfuse URL |
| `LANGFUSE_CAPTURE_DATA` | no | `false` | `true`/`1`/`yes` → include tool inputs/outputs and error messages in traces |

## Architecture

```
librelinkup-mcp/
├── pyproject.toml
├── README.md
├── .gitignore
├── src/librelinkup_mcp/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py
│   ├── config.py
│   ├── service.py
│   ├── formatting.py
│   └── tracing.py
└── tests/
```

Data flow: MCP client → FastMCP tool (`server.py`) → `traced` span
(`tracing.py`) → `GlucoseService` (`service.py`) → `asyncio.to_thread` →
pylibrelinkup → LibreLinkUp API. Results pass through `formatting.py` and are
returned as JSON-serialisable dicts/lists.

### `config.py`

- `Settings` frozen dataclass: `email`, `password`, `region: APIUrl`,
  `langfuse_enabled: bool`, `langfuse_capture_data: bool`.
- `load_settings(env: Mapping[str, str] = os.environ) -> Settings`.
- Raises `ConfigError` with a human-readable message on missing credentials or
  invalid region (message lists valid regions).
- `langfuse_enabled` is true iff both Langfuse keys are non-empty.
- No I/O other than reading the mapping.

### `service.py`

The only module that imports `pylibrelinkup`.

- `GlucoseService(client: PyLibreLinkUpLike)`; client is injected (a
  `Protocol` with `authenticate`, `get_patients`, `latest`, `graph`,
  `logbook`). Production code constructs `PyLibreLinkUp(email, password,
  api_url=region)`.
- Async public methods:
  - `list_patients() -> list[Patient]`
  - `current(patient: str | None) -> tuple[Patient, GlucoseMeasurementWithTrend]`
  - `graph(patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]`
  - `logbook(patient: str | None) -> tuple[Patient, list[GlucoseMeasurement]]`
- All sync client calls run via `asyncio.to_thread`.
- **Lazy authentication:** first call authenticates. An `asyncio.Lock` guards
  authentication and the patient cache so concurrent first calls authenticate
  once.
- **Re-auth:** if a data call raises `AuthenticationError`, re-authenticate once
  and retry the call once. A second failure is surfaced.
- **Patient cache:** fetched once per process. On a name/UUID miss, refetch
  once before reporting not-found.
- **Patient resolution** for the `patient` argument:
  1. `None`: exactly one patient → use it; zero → error "No patients followed
     by this account"; several → error listing `first last (patient_id)` for
     each.
  2. Parses as UUID → match against `patient_id` or `id`.
  3. Otherwise case-insensitive match on `"first last"`; if no full-name match,
     case-insensitive match on first name. Exactly one match → use it; several
     → "ambiguous" error listing candidates; none → "not found" error listing
     candidates.
- **Error mapping** to `mcp.server.fastmcp.exceptions.ToolError`:

| Upstream exception | Message |
|---|---|
| `AuthenticationError` (after retry) | "LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD." |
| `RedirectError` | "This account belongs to region {region.name}. Set LIBRELINKUP_REGION={region.name}." |
| `TermsOfUseError`, `PrivacyPolicyError` | "Open the LibreLinkUp app and accept the updated terms of use / privacy policy, then retry." |
| `EmailVerificationError` | "Verify the account email address in the LibreLinkUp app, then retry." |
| `LLUAPIRateLimitError` | "Rate limited by LibreLinkUp. Try again in {retry_after} seconds." (or "later" when `retry_after` is None) |
| `PatientNotFoundError` | "LibreLinkUp reports patient not found." |
| other `LLUAPIError` | "LibreLinkUp API error {response_code}." |
| `requests.RequestException` | "Could not reach LibreLinkUp: {exception class name}." |

### `formatting.py`

Pure functions:

- `patient_to_dict(p) -> {"patient_id", "id", "first_name", "last_name"}` (UUIDs as strings).
- `measurement_to_dict(m) -> {"timestamp", "value", "value_mg_dl", "unit", "is_high", "is_low"}`
  - `timestamp`: ISO 8601 of `m.timestamp`.
  - `unit`: `"mg/dL"` when `glucose_units == 1`, else `"mmol/L"`.
  - If `m` has `trend`: adds `"trend"` (enum name, e.g. `"UP_SLOW"`) and `"trend_arrow"` (e.g. `"↗"`).
- `readings_response(patient, measurements) -> {"patient": ..., "count": n, "readings": [...]}` sorted by timestamp ascending.

The `glucose_units` mapping is taken from pylibrelinkup's test fixtures:
`GlucoseUnits: 1` accompanies integer values (e.g. 115, mg/dL) and
`GlucoseUnits: 0` accompanies decimal values (e.g. 8.8, mmol/L).

### `tracing.py`

- `configure(settings)` called once at startup.
- `traced(name: str)` decorator for async functions:
  - Disabled, or `langfuse` not importable → returns the function unchanged.
  - Enabled → wraps with Langfuse v3 `observe(name=name, capture_input=capture, capture_output=capture)`.
  - Always records metadata: tool name, resolved patient UUID (when known),
    outcome. On error, marks the observation `level="ERROR"` with the exception
    type; `status_message` includes the exception message only when capture is on.
- The upstream API call inside `GlucoseService` is a child span named
  `librelinkup.<method>`.
- `shutdown()` flushes the Langfuse client; registered with `atexit`.
- Nothing in this module writes to stdout. Langfuse SDK logging is routed to
  stderr.

### `server.py`

- `mcp = FastMCP("librelinkup")`.
- Four tools, each a thin call to the service followed by formatting:

| Tool | Args | Returns | Docstring gist |
|---|---|---|---|
| `list_patients` | — | `{"patients": [...]}` | People this LibreLinkUp account follows |
| `get_current_glucose` | `patient: str \| None = None` | `{"patient", "reading"}` with trend | Most recent reading and trend |
| `get_glucose_graph` | `patient: str \| None = None` | `readings_response` | ~last 12 hours, ~15-min interval |
| `get_glucose_logbook` | `patient: str \| None = None` | `readings_response` | Logged events, ~last 2 weeks |

- `main()`: `load_settings()`; on `ConfigError` print to stderr and
  `sys.exit(1)`; `tracing.configure(settings)`; build service; `mcp.run()`
  (stdio). The service instance is module-level state set by `main()` and
  replaceable in tests.

### `__main__.py`

Calls `server.main()`.

## Testing

pytest + pytest-asyncio. No network in the default suite.

- `test_config.py`: required vars, default and case-insensitive region,
  invalid region message, Langfuse enabled only with both keys, capture flag
  parsing.
- `test_formatting.py`: build real pylibrelinkup models from fixture JSON
  (adapted from pylibrelinkup's test data); assert dict shape, ISO timestamps,
  unit mapping, trend fields present only on trend measurements, sort order.
- `test_service.py` with `FakeLibreClient`:
  - authenticate called exactly once across calls, including concurrent first calls;
  - `AuthenticationError` → one re-auth + retry → success; second failure → ToolError;
  - each exception row in the mapping table → expected message;
  - every patient-resolution branch;
  - patient-cache refresh on miss.
- `test_tracing.py`: passthrough when disabled; passthrough when `langfuse`
  import fails (monkeypatched); capture flag forwarded to a fake `observe`.
- `test_server.py`: in-memory FastMCP client session against a fake service;
  `list_tools` returns the four tools with expected schemas; each tool returns
  expected JSON; ToolError surfaces as a tool error result.
- `test_live.py`: `@pytest.mark.live`, skipped unless `LIBRELINKUP_EMAIL` and
  `LIBRELINKUP_PASSWORD` are set; calls `list_patients` and
  `get_current_glucose` only.

## Packaging

- `pyproject.toml`, hatchling build backend, `requires-python = ">=3.11"`.
- Dependencies: `mcp`, `pylibrelinkup`.
- Optional extra `langfuse`: `langfuse>=3`.
- Dev dependency group: `pytest`, `pytest-asyncio`, `ruff`.
- Console script: `librelinkup-mcp = "librelinkup_mcp.server:main"`.
- README: env vars, regions, Claude Desktop JSON config, `claude mcp add`
  command for Claude Code, Langfuse setup, privacy note on
  `LANGFUSE_CAPTURE_DATA` (glucose readings and names are health data).
- `.gitignore` for Python/uv artifacts and `.env`.
