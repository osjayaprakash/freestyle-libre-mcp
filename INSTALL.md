# Installing librelinkup-mcp

This guide takes you from nothing to asking Claude "what's my glucose right now?". It
takes about 15 minutes, most of it spent on the LibreLinkUp account.

## 1. Prerequisites

- **A FreeStyle Libre sensor** whose readings are shared through the LibreLink app.
- **A LibreLinkUp follower account.** This server logs in as a *follower*, not as the
  person wearing the sensor (see step 2).
- **[uv](https://docs.astral.sh/uv/)**, which installs Python 3.11+ and the dependencies
  for you:

  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # or, with Homebrew
  brew install uv
  ```

  ```powershell
  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

- **An MCP client**, such as Claude Desktop or Claude Code.

## 2. Set up the LibreLinkUp follower account

1. In the **LibreLink** app (on the phone that reads the sensor), open *Connected Apps* →
   *LibreLinkUp* and invite the email address you want to use as the follower.
2. Install the **LibreLinkUp** app, sign up with that email address, and accept the
   invitation.
3. Accept every terms-of-use and privacy prompt the app shows, and verify the email
   address if asked. The server can't accept these for you and fails until they are
   done.
4. Check that you can see the readings in the LibreLinkUp app.

Note the email, password, and region (the country the account was created in). If you
aren't sure of the region, leave it as `US`; the first tool call tells you the right one.

Valid regions: `US`, `EU`, `EU2`, `AE`, `AP`, `AU`, `CA`, `DE`, `FR`, `JP`, `LA`, `RU`.

## 3. Download and install

```bash
git clone <this repo URL> librelinkup-mcp
cd librelinkup-mcp
uv sync
```

Note the full path of this folder; you'll need it below:

```bash
pwd
```

## 4. Check your credentials

Before connecting a client, confirm the server can log in and read data:

```bash
LIBRELINKUP_EMAIL='you@example.com' \
LIBRELINKUP_PASSWORD='your-password' \
LIBRELINKUP_REGION='US' \
uv run pytest -m live -q
```

`1 passed` means it works. If it fails, the error message tells you what to fix; see
[Troubleshooting](#troubleshooting).

On Windows (PowerShell), set the variables first:

```powershell
$env:LIBRELINKUP_EMAIL = "you@example.com"
$env:LIBRELINKUP_PASSWORD = "your-password"
$env:LIBRELINKUP_REGION = "US"
uv run pytest -m live -q
```

## 5. Connect your client

### Claude Desktop

1. Find the full path to `uv`. Claude Desktop doesn't always see your shell's `PATH`, so
   use the absolute path:

   ```bash
   which uv        # macOS / Linux, e.g. /Users/you/.local/bin/uv
   where uv        # Windows
   ```

2. Open the config file (*Settings* → *Developer* → *Edit Config*), or open it directly:

   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

3. Add the server under `mcpServers`, keeping any servers already there:

   ```json
   {
     "mcpServers": {
       "librelinkup": {
         "command": "/Users/you/.local/bin/uv",
         "args": ["--directory", "/Users/you/librelinkup-mcp", "run", "librelinkup-mcp"],
         "env": {
           "LIBRELINKUP_EMAIL": "you@example.com",
           "LIBRELINKUP_PASSWORD": "your-password",
           "LIBRELINKUP_REGION": "US"
         }
       }
     }
   }
   ```

   On Windows, double every backslash in paths, for example
   `"C:\\Users\\you\\librelinkup-mcp"`.

4. Quit Claude Desktop completely and reopen it. The `librelinkup` tools should appear in
   the tools menu.

### Claude Code

```bash
claude mcp add librelinkup \
  -e LIBRELINKUP_EMAIL=you@example.com \
  -e LIBRELINKUP_PASSWORD=your-password \
  -e LIBRELINKUP_REGION=US \
  -- uv --directory /Users/you/librelinkup-mcp run librelinkup-mcp
```

This adds the server to the current project only. Add `--scope user` after `add` to make
it available in every project. Check it with `claude mcp list`.

### Other MCP clients

Run this command with the three environment variables set; it speaks MCP over stdio:

```bash
uv --directory /path/to/librelinkup-mcp run librelinkup-mcp
```

## 6. Try it

Ask Claude:

- "What's my glucose right now?"
- "Show me my readings from the last 12 hours."
- "Were there any lows this week?"

If the account follows more than one person, name who you mean ("What's Ann's glucose?"),
or ask Claude to list the patients first.

Check `age_minutes` on a "current" reading: if the phone or sensor is out of range,
LibreLinkUp returns the last known value, which can be hours old.

## Optional: Langfuse tracing

To send a trace of each tool call to [Langfuse](https://langfuse.com):

1. Install the extra: `uv sync --extra langfuse`.
2. In the client config, change `run librelinkup-mcp` to
   `run --extra langfuse librelinkup-mcp`.
3. Add `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the server's `env`, plus
   `LANGFUSE_BASE_URL` if you don't use Langfuse Cloud.

By default, traces hold only tool names, timings, patient UUIDs and error class names.
`LANGFUSE_CAPTURE_DATA=true` also sends glucose readings and patient names; only turn it
on with a Langfuse instance you trust, such as a self-hosted one.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing required environment variable(s): …` | The client isn't passing the credentials. Check the `env` block (Claude Desktop) or `-e` flags (Claude Code). |
| `Invalid LIBRELINKUP_REGION …` | Use one of the region names listed in step 2. |
| `This account belongs to region X. Set LIBRELINKUP_REGION=X.` | Change the region to `X` and restart the client. |
| `LibreLinkUp login failed. Check LIBRELINKUP_EMAIL and LIBRELINKUP_PASSWORD.` | Log in to the LibreLinkUp app with the same email and password to confirm them. Passwords are used exactly as typed, including spaces. |
| `Open the LibreLinkUp app and accept the updated terms of use…` (or privacy policy) | Open the LibreLinkUp app, accept the prompt, then retry. |
| `Verify the account email address…` | Click the verification link LibreLinkUp emailed you. |
| `No patients are followed by this LibreLinkUp account.` | The invitation from step 2 hasn't been accepted, or was sent to a different email. |
| `Rate limited by LibreLinkUp…` | Wait for the time shown, then retry. |
| `LibreLinkUp API error 4xx/9xx` on every call | Abbott may have raised the minimum app version. Check for an update to this project. |
| `LibreLinkUp returned unexpected data for …` | The API's response format changed or the sensor has no data. Open an issue with the tool name. |
| Tools don't appear in Claude Desktop | Use the absolute path to `uv`, check the JSON is valid, and fully quit and reopen Claude Desktop. Logs are in `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs\` (Windows). |

## Updating

```bash
cd /path/to/librelinkup-mcp
git pull
uv sync
```

Then restart your MCP client.

## Uninstalling

1. Remove the `librelinkup` entry from `claude_desktop_config.json`, or run
   `claude mcp remove librelinkup`.
2. Delete the `librelinkup-mcp` folder.

## A note on your password

The client config stores the LibreLinkUp password in plain text, readable by anyone who
can read that file. Use a follower account with its own password, not one you use
elsewhere.
