# librelinkup-mcp history recording — Design

Date: 2026-09-26
Status: Draft for review
Builds on: `2026-09-26-librelinkup-mcp-design.md` and
`2026-09-26-core-client-design.md` (both still apply).

## Goal

LibreLinkUp only serves ~12 hours of continuous readings. Let the user build
a long-term local history (weeks to months) by recording readings on demand,
and let Claude read that history back.

Success: after `record_glucose` has been called at least every 12 hours for a
month, `get_glucose_history` answers questions about any day in that month
with real readings.

## Decisions

- A `record_glucose` MCP tool and a `librelinkup-mcp record` CLI command,
  sharing one function. No background loop or scheduler is shipped; the CLI
  makes one possible later (cron/launchd).
- `record` saves the 12-hour graph plus the current reading, for every
  followed patient by default or one named patient.
- Storage: JSON Lines, one reading per line, one file per local day:
  `<history_dir>/<patient_id>/YYYY/MM/YYYY-MM-DD.jsonl`.
- A day is midnight–midnight in `LIBRELINKUP_TIMEZONE` (default
  `America/Los_Angeles`, i.e. PDT/PST with DST), computed from `timestamp_utc`.
- `get_glucose_history(patient?, start_date, end_date?, every_minutes=5)`
  returns real readings (no averages), optionally thinned, capped at 2,000
  readings per call.
- Still "readings only": no computed statistics.
- Gaps when `record` is not called for >12 hours are accepted; the API cannot
  return them later.

## Out of scope

Shipping a scheduler, retention/cleanup, logbook events, statistics, import of
LibreView CSV exports, locking on Windows.

## Configuration (new)

| Variable | Default | Meaning |
|---|---|---|
| `LIBRELINKUP_TIMEZONE` | `America/Los_Angeles` | IANA zone that defines a "day" for file names and history date ranges |
| `LIBRELINKUP_HISTORY_DIR` | `~/.librelinkup-mcp/history` | Root folder for history files (`~` expanded) |

`Settings` gains `timezone: ZoneInfo` and `history_dir: Path`. An unknown
zone raises `ConfigError("Invalid LIBRELINKUP_TIMEZONE 'X'. Use an IANA name
such as America/Los_Angeles.")`. Dependency added:
`tzdata; sys_platform == "win32"` (Windows has no system zone database).

## Storage format

- Path: `<history_dir>/<patient_id>/<YYYY>/<MM>/<YYYY-MM-DD>.jsonl`, where the
  date is `timestamp_utc` converted to the configured zone.
- `<patient_id>` is the LibreLinkUp `patientId` UUID, never a name.
- Each line is `formatting.measurement_to_dict(m)`: `timestamp`,
  `timestamp_utc`, `value`, `value_mg_dl`, `unit`, `is_high`, `is_low`, and
  `trend`/`trend_arrow` when the reading has a trend. UTF-8, `\n`-terminated,
  keys in that order.
- Within a patient, lines are appended in increasing `timestamp_utc` order.

## `history.py` (new)

File-system only; never imports the LibreLinkUp client.

```python
MAX_READINGS = 2000

class HistoryError(Exception): ...          # bad range / too many readings

@dataclass(frozen=True)
class HistoryResult:
    readings: list[dict[str, Any]]
    skipped_lines: int

class HistoryStore:
    def __init__(self, root: Path, tz: ZoneInfo) -> None
    def append(self, patient_id: UUID, readings: Iterable[dict[str, Any]]) -> int
    def read(self, patient_id: UUID, start: date, end: date, every_minutes: int) -> HistoryResult
```

**`append`** (synchronous; callers run it via `asyncio.to_thread`):

1. Create `<root>/<patient_id>/` if needed and hold an exclusive
   `fcntl.flock` on `<root>/<patient_id>/.lock` for the whole call (POSIX
   only; where `fcntl` is unavailable, no lock — `read` de-duplicates anyway).
2. Find the latest stored `timestamp_utc`: the newest day file by path order,
   last parseable line. None if no files.
3. Drop incoming readings whose `timestamp_utc` is not strictly newer; drop
   duplicates within the batch; sort the rest by `timestamp_utc`.
4. Append each to its local-date file (creating year/month folders).
5. Return the number of lines written.

**`read`**:

1. `start > end` → `HistoryError("start_date must not be after end_date.")`;
   `every_minutes` outside 1–1440 → `HistoryError("every_minutes must be
   between 1 and 1440.")`.
2. For each date in `[start, end]` (inclusive), read the file if it exists.
3. Unparseable lines (bad JSON, missing `timestamp_utc`) are skipped and
   counted in `skipped_lines`.
4. De-duplicate by `timestamp_utc`, sort ascending.
5. Thin: keep the first reading, then each reading at least `every_minutes`
   after the last kept one.
6. More than `MAX_READINGS` after thinning → `HistoryError("That range has N
   readings; the limit is 2000. Narrow the dates or raise every_minutes (e.g.
   60 for one reading per hour).")`.

## Service (`service.py`)

```python
@dataclass(frozen=True)
class RecordOutcome:
    patient: Patient
    added: int
    error: str | None       # ToolError message when this patient failed

async def record(self, patient: str | None) -> list[RecordOutcome]
```

- `patient` given → resolve as other tools (errors raise ToolError);
  omitted → every followed patient.
- Per patient: fetch `graph` and `latest` through the existing
  `_request` path (login, re-login, error mapping, tracing), convert with
  `measurement_to_dict`, `await asyncio.to_thread(store.append, …)`.
- A ToolError for one patient is captured in that outcome's `error`; other
  patients continue.
- `GlucoseService(client, store: HistoryStore | None = None)`; `record` and
  `history` raise `RuntimeError` if no store was given.

```python
async def history(self, patient: str | None, start: date, end: date,
                  every_minutes: int) -> tuple[Patient, HistoryResult]
```

Resolves the patient (same rules), runs `store.read` in a thread,
`HistoryError` → `ToolError` with the same message.

## Tools (`server.py`)

`record_glucose(patient: str | None = None)` — annotations
`readOnlyHint=False, destructiveHint=False, idempotentHint=True`.
Docstring: saves the last ~12 hours of readings to local history; call at
least every 12 hours to avoid gaps. Returns:

```json
{"recorded": [{"patient": {…}, "added": 12}, {"patient": {…}, "added": 0, "error": "…"}]}
```

(`error` key present only on failure.)

`get_glucose_history(patient=None, start_date: str, end_date: str | None = None,
every_minutes: int = 5)` — read-only. Dates are `YYYY-MM-DD` in
`LIBRELINKUP_TIMEZONE`; `end_date` defaults to `start_date`. Invalid date text
→ ToolError "Dates must be YYYY-MM-DD." Returns:

```json
{"patient": {…}, "start_date": "…", "end_date": "…", "timezone": "America/Los_Angeles",
 "every_minutes": 60, "count": 24, "skipped_lines": 0, "readings": [ … ]}
```

With `count == 0`, adds `"hint": "No recorded readings in this range. Call
record_glucose to start recording; history only covers times it was called
within 12 hours of."`

Server `instructions` mention the two tools and that history dates use
`LIBRELINKUP_TIMEZONE`. Both tools are wrapped in `tracing.traced` like the
others.

## CLI

`main(argv: list[str] | None = None)` parses arguments with `argparse`
(`None` → `sys.argv[1:]`). `librelinkup-mcp` with no arguments runs the stdio
server (unchanged). The CLI builds its client through `build_client(settings)`
so tests can monkeypatch it with the fake client.
`librelinkup-mcp record [--patient NAME_OR_ID]`:

- Loads settings (ConfigError → stderr, exit 1), configures tracing, builds
  client, store and service, runs `service.record(patient)` with
  `asyncio.run`.
- Prints one line per patient to stdout:
  `Ann Lee (<patient_id>): 12 new readings` or
  `Ann Lee (<patient_id>): failed: <message>`.
- A ToolError before any patient is processed (e.g. login failed) → message
  on stderr, exit 1. Any per-patient failure → exit 1. Otherwise exit 0.

## Docs

README tools table and env table gain the new tool/variables; INSTALL.md
gains a "Recording history" section (call `record_glucose` or run
`librelinkup-mcp record`; optional crontab example
`0 */4 * * * cd /path && uv run librelinkup-mcp record`; set the two new
variables in the client config's `env`).

## Testing

All offline.

- `tests/test_history.py` (`tmp_path`):
  - append writes to `<id>/YYYY/MM/YYYY-MM-DD.jsonl` by local date;
    a reading at 06:30 UTC lands on the previous Pacific day;
  - DST fall-back day (2026-11-01) — readings split correctly, 25-hour file;
  - second append with overlapping readings adds only newer ones and returns
    the count; duplicates inside one batch written once;
  - read across days, missing days skipped, inclusive end;
  - thinning at 60 minutes keeps real readings ~1 hour apart;
  - cap exceeded → HistoryError naming the count;
  - corrupt / half-written line skipped and counted;
  - duplicate lines in files de-duplicated on read;
  - bad range / every_minutes → HistoryError;
  - lock file created; two concurrent appends (threads) produce no duplicates.
- `tests/test_config.py`: timezone default, custom, invalid; history dir
  default and `~` expansion.
- `tests/test_service.py`: record all patients / one patient; per-patient
  error captured while others succeed; history resolves patient and maps
  HistoryError; RuntimeError without a store.
- `tests/test_server.py`: `record_glucose` schema + annotations (not
  read-only); `get_glucose_history` schema, defaults, bad date text, empty
  range hint, thinning end to end with the fake client and `tmp_path` store.
- `tests/test_cli.py`: `main(["record"])` with a fake service prints per-patient
  lines and exit codes 0/1; missing credentials → exit 1.
