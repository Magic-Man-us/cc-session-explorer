# cc-session-explorer

[![PyPI](https://img.shields.io/pypi/v/cc-session-explorer.svg)](https://pypi.org/project/cc-session-explorer/)
[![Python versions](https://img.shields.io/pypi/pyversions/cc-session-explorer.svg)](https://pypi.org/project/cc-session-explorer/)
[![CI](https://github.com/Magic-Man-us/cc-session-explorer/actions/workflows/publish.yml/badge.svg)](https://github.com/Magic-Man-us/cc-session-explorer/actions/workflows/publish.yml)
[![codecov](https://codecov.io/gh/Magic-Man-us/cc-session-explorer/branch/main/graph/badge.svg)](https://codecov.io/gh/Magic-Man-us/cc-session-explorer)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-brightgreen.svg)](https://github.com/Magic-Man-us/cc-session-explorer/blob/main/.github/dependabot.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Magic-Man-us/cc-session-explorer/blob/main/LICENSE)

Replays Claude Code session transcripts and Claude.ai exports as context-token
timelines, cost ledgers, and project breakdowns — a FastAPI dashboard, CLI tools,
and an MCP server built on [cc-session-core](https://github.com/Magic-Man-us/cc-session-core),
which owns the transcript parsing boundary. This package maps each typed record to
presentation-layer models and renders them.

## Layout

```
src/cc_session_explorer/   The Python package
  api/                     /timeline lens: context-token replay routes
  usage/                   /api lens: cost + token usage rollups
  ingest/                  Live transcript ingest (watchfiles -> SQLite)
  history/                 Historical ledger store + refresh CLI
  viz/                     Self-contained HTML reports (Sankey, cost ledger)
  mcp/                     Stdio MCP server over the same capabilities
  static/                  Built single-file SPA (output of frontend/app)
frontend/
  ui/                      @cc-session/dashboard-ui — the design-system components
  app/                     @cc-session/dashboard-app — the dashboard SPA (bundles ui from source)
systemd/                   Linux user services for the dashboard and the live watcher
launchd/                   macOS LaunchAgents for the dashboard and the live watcher
tests/
```

Persistent stores live under `~/.cc-session-explorer` (`transcripts.db`, `ledger.db`) — the
legacy data home, kept so existing installs and the systemd watcher carry over
(see [src/cc_session_explorer/paths.py](src/cc_session_explorer/paths.py)).

## Install

```sh
uv tool install cc-session-explorer
```

From a checkout (the sibling `cc-session-core` repo must sit next to this one —
`[tool.uv.sources]` wires it up editable for development):

```sh
uv sync --all-groups
```

## Run

| Command | What it does |
| --- | --- |
| `cc-session-explorer` | FastAPI dashboard: SPA at `/`, cost lens at `/api/*`, context lens at `/timeline/*`, on 127.0.0.1:9821 |
| `cc-session-watch` | Live transcript watcher; ingests `~/.claude/projects` into SQLite |
| `cc-session-history` | Refreshes the historical usage ledger |
| `cc-session-sankey` | Per-session token-flow Sankey as a self-contained HTML page |
| `cc-session-ledger` | Directory-wide cost ledger as a self-contained HTML page |
| `cc-session-explorer-mcp` | Stdio MCP server exposing the explorer's capabilities as tools |

Configuration comes from `CC_SESSION_EXPLORER_*` env vars (or a `.env`):
`CC_SESSION_EXPLORER_HOME_DIR` (defaults to your home directory) and
`CC_SESSION_EXPLORER_EXPORT_PATH` (a Claude.ai account export zip, only needed
for the export timeline).

## MCP server

Register `cc-session-explorer-mcp` in a Claude Code `.mcp.json`:

```json
{
  "mcpServers": {
    "cc-session-explorer": {
      "command": "cc-session-explorer-mcp"
    }
  }
}
```

## Frontend

The SPA is built from `frontend/app`, which bundles the `frontend/ui` design system
directly from source (a Vite alias — no publish step). `frontend/` is an npm workspace
(`app` + `ui`) so both share one hoisted `node_modules` — install once at the workspace
root. The build emits one self-contained `index.html` into `src/cc_session_explorer/static/`,
where the FastAPI app serves it as package data.

```sh
cd frontend && npm install
cd app && npm run build      # regenerates src/cc_session_explorer/static/index.html
npm run typecheck            # tsc --noEmit across the app (and, from frontend/ui, the design system)
npm run dev                  # dev server proxying to a running dashboard on :9821
```

## Background services (optional)

`bin/cc-session-explorer-startup` installs and starts the dashboard and the transcript
watcher as background services, dispatching to the right one for your OS. It's idempotent
(safe to run on every plugin load, and picks up unit changes automatically) and is what the
plugin's `dashboard-uptime` monitor calls on your behalf — running it by hand is only needed
outside the Claude Code plugin context.

### Linux: systemd

User units live in `systemd/`. The dashboard is socket-activated (`cc-session-explorer.socket`
holds the port; `cc-session-explorer.service` starts on demand and exits after an idle
period); the watcher is a plain always-on service. Manual install, if not running via the
startup script above:

```sh
cp systemd/*.service systemd/*.socket ~/.config/systemd/user/
# edit ExecStart in each unit if you run from a checkout rather than `uv tool install`
systemctl --user daemon-reload
systemctl --user enable --now cc-session-explorer.socket cc-session-watch.service
```

### macOS: launchd

LaunchAgents live in `launchd/`. launchd has no environment-variable-based socket-activation
protocol a plain Python process can read (systemd's `LISTEN_FDS` has no macOS equivalent
without private-API C bindings), so both the dashboard and the watcher run always-on here —
the app already supports this directly (`SystemdActivation` degrades to a plain
`uvicorn.run()` when no systemd env vars are present). Manual install, if not running via the
startup script above:

```sh
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/cc-session-explorer
sed -e "s|@PLUGIN_ROOT@|$(pwd)|g" -e "s|@HOME@|$HOME|g" \
  launchd/com.cc-session-explorer.dashboard.plist > ~/Library/LaunchAgents/com.cc-session-explorer.dashboard.plist
sed -e "s|@PLUGIN_ROOT@|$(pwd)|g" -e "s|@HOME@|$HOME|g" \
  launchd/com.cc-session-explorer.watch.plist > ~/Library/LaunchAgents/com.cc-session-explorer.watch.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.cc-session-explorer.dashboard.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.cc-session-explorer.watch.plist
```

Logs: `~/Library/Logs/cc-session-explorer/{dashboard,watch}.log`.

## Development

```sh
uv run pytest
uv run ruff check
uv run pyright
```

Publishing order: `cc-session-core` goes to PyPI first; this package depends on
`cc-session-core>=0.1.0,<0.2.0`.

## License

MIT
