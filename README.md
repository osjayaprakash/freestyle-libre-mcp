# freestyle-libre-mcp

An MCP server that gives Claude (or any MCP client) read-only access to FreeStyle Libre
CGM glucose readings shared through LibreLinkUp. It talks to the LibreLinkUp API with its
own small async client (`librelinkup_mcp.core`); the API behaviour it relies on follows
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
sensor's local time), `timestamp_utc`, and `is_high`/`is_low` flags. The current reading
also has `age_minutes`, since LibreLinkUp returns the last known value when the sensor or
phone is out of range.

## Setup

For a step-by-step guide, including account setup and troubleshooting, see the
[installation guide](https://freestyle-libre-mcp.readthedocs.io/en/latest/install/).
Full documentation is at <https://freestyle-libre-mcp.readthedocs.io>.

You need a LibreLinkUp **follower** account: invite it from the LibreLink app, accept the
invite in the LibreLinkUp app, and accept any terms there before using this server.

```bash
git clone https://github.com/osjayaprakash/freestyle-libre-mcp.git && cd freestyle-libre-mcp
uv sync
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LIBRELINKUP_EMAIL` | yes | | Follower account email |
| `LIBRELINKUP_PASSWORD` | yes | | Follower account password |
| `LIBRELINKUP_REGION` | no | `US` | One of `US`, `EU`, `EU2`, `AE`, `AP`, `AU`, `CA`, `DE`, `FR`, `JP`, `LA`, `RU` |

If the region is wrong, the first tool call tells you which one to set.

### Run from PyPI

No clone needed; [uv](https://docs.astral.sh/uv/) fetches and runs the published package:

```bash
uvx freestyle-libre-mcp
```

In a client config, use `"command": "uvx", "args": ["freestyle-libre-mcp"]`.

### Run with Docker

The server speaks MCP over stdio, so keep `-i`:

```bash
docker run -i --rm \
  -e LIBRELINKUP_EMAIL -e LIBRELINKUP_PASSWORD -e LIBRELINKUP_REGION \
  ghcr.io/osjayaprakash/freestyle-libre-mcp:latest
```

In a client config, use `"command": "docker"` with those arguments, and pass the
variables through the client's `env` block.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "librelinkup": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/freestyle-libre-mcp", "run", "freestyle-libre-mcp"],
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
  -- uv --directory /absolute/path/to/freestyle-libre-mcp run freestyle-libre-mcp
```

## Langfuse tracing (optional)

Each tool call becomes a Langfuse trace, with a child span for the LibreLinkUp API call.
Install the extra and set the keys:

```bash
uv sync --extra langfuse
```

In the server command, use `run --extra langfuse freestyle-libre-mcp` instead of
`run freestyle-libre-mcp`.

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
