<!-- mcp-name: io.github.shigechika/zapi-mcp -->

# zapi-mcp

English | [日本語](README.ja.md)

MCP (Model Context Protocol) server for the [Zabbix](https://www.zabbix.com/) API.

Built for network operations: a single `daily_brief` call summarizes active
problems plus site-specific categories (DHCP pool usage, SNAT session usage,
core-network problems, …), and individual tools query problems, hosts, and item
values. Organization-specific tags live in a config file, not the code, so the
server stays generic.

Version-adaptive auth: works against Zabbix 6.0 LTS (`user` + `auth` field) and
forward-compatible with 6.4 / 7.0 (`username` + `Authorization: Bearer`).

## Features

| Tool | Description |
|------|-------------|
| `health_check` | Server version, Zabbix connectivity/auth, detected API version, and configured `daily_brief` categories — call at session start or after a timeout |
| `daily_brief` | Morning patrol: active problems (Warning+) plus one section per configured category |
| `get_problems` | Active problems by severity and tag, newest-first with age; header shows the true total (`showing N of TOTAL` when capped); output includes `eventid` |
| `get_hosts` | List hosts filtered by role/tag/group, with IP and tags |
| `get_host_items` | Current item values for a host (server-side host filter) |
| `acknowledge_problem` | Acknowledge problems and add a message (does not close them) |

## Setup

```bash
# uv
uv pip install zapi-mcp

# pip
pip install zapi-mcp
```

Or from source:

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp

# uv
uv sync

# pip
pip install -e .
```

## Configuration

Set the following environment variables:

| Variable | Description | Default |
|---|---|---|
| `ZABBIX_URL` | Zabbix base URL (e.g. `https://zabbix.example.com`); `/api_jsonrpc.php` is appended if absent | *required* |
| `ZABBIX_USER` | Zabbix API user | *required* |
| `ZABBIX_PASSWORD` | Zabbix API password | *required* |
| `ZABBIX_CATEGORIES_INI` | Path to a categories INI file for `daily_brief` (optional) | — |
| `ZABBIX_BRIEF_RECENT_HOURS` | `daily_brief` "recent" window in hours; problems older than this are folded to a count | `24` |
| `ZABBIX_BRIEF_PROBLEM_LIMIT` | Max active problems `daily_brief` fetches per call before counting the rest | `1000` |

The API user needs read permission for the host groups you query, plus
acknowledge permission if you use `acknowledge_problem`.

### Active problems in `daily_brief`

Problems are grouped by severity and listed **newest-first**, each annotated with
its age (e.g. `3h ago`). Problems older than the recent window
(`ZABBIX_BRIEF_RECENT_HOURS`, default 24h) are folded to a single
`… and N older (stale; oldest …)` line — so a backlog of alerts that Zabbix
keeps active because their recovery is never auto-confirmed (ICMP ping down, RDP
down, …) doesn't bury what just happened. Section headers carry the true total
and show `showing N of TOTAL` when the fetch is capped, never a silent truncation.

### Categories for `daily_brief` (optional)

`daily_brief` always lists active problems. To add site-specific sections —
DHCP pool exhaustion, SNAT session usage, core-network problems — point
`ZABBIX_CATEGORIES_INI` at an INI file. Each `[section]` is one category:

```ini
[dhcp]
name = DHCP Pool Usage
tag = dhcp-pool-usage      ; Zabbix host tag identifying the group
item_key = usage           ; report current values for this exact item key
threshold = 80             ; flag values >= this

[snat]
name = SNAT Session Pool
tag = snat-pool-usage
item_key_search = .usage   ; substring match (catches pool.node0.usage etc.)
threshold = 80

[core]
name = Core Network
tag = role
tag_value = main           ; tag must equal this value
                           ; no item key -> report active problems instead
```

- `tag` (required): host tag identifying the category. With `tag_value`, the tag
  must equal it (Equal); without, any host carrying the tag matches (Exists).
- `item_key` / `item_key_search`: when either is set, the section reports current
  item values sorted high-to-low. `item_key` matches the key exactly; use
  `item_key_search` for keys that embed an id (e.g. `.usage` catches
  `pool.node0.usage`). When neither is set, it reports active problems for the tag.
- `threshold`: optional; values at or above it are flagged.

See [`categories.ini.example`](categories.ini.example). When the variable is
unset or the file is missing, `daily_brief` reports active problems only.

## Usage

### Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "zapi-mcp": {
      "type": "stdio",
      "command": "zapi-mcp",
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_USER": "api-user",
        "ZABBIX_PASSWORD": "",
        "ZABBIX_CATEGORIES_INI": "/path/to/categories.ini"
      }
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "zapi-mcp": {
      "command": "zapi-mcp",
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_USER": "api-user",
        "ZABBIX_PASSWORD": ""
      }
    }
  }
}
```

### Direct Execution

```bash
export ZABBIX_URL=https://zabbix.example.com
export ZABBIX_USER=api-user
export ZABBIX_PASSWORD=your-password
zapi-mcp
```

### CLI Options

```bash
zapi-mcp --version   # Print version and exit
zapi-mcp --check     # Verify environment variables and authentication, then exit
zapi-mcp --brief     # Print the daily_brief to stdout and exit (handy for cron)
zapi-mcp             # Start MCP server (STDIO, default)
```

`--check` exit codes: `0` success, `1` config error, `2` auth/connection error.

`--brief` exit codes: `0` success, `1` a section failed (auth, the active-problems
fetch, or category loading — see the embedded `Error:` line in the output).

## Development

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp

# uv
uv sync --dev
uv run pytest -v
uv run ruff check .

# pip
python3 -m venv .venv
.venv/bin/pip install -e . && .venv/bin/pip install pytest pytest-cov respx ruff
.venv/bin/pytest -v
.venv/bin/ruff check .
```

## Releasing

Releases are automated with [release-please](https://github.com/googleapis/release-please).
Merging [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, …)
to `main` keeps a release PR open with the next version and changelog. Merging
that PR tags `vX.Y.Z` and publishes a GitHub Release, whose `release: published`
event triggers the `release` workflow to build and publish to PyPI and the MCP
Registry. release-please owns the version in `zapi_mcp/__init__.py` and
`server.json` (do not bump them by hand).

> [!IMPORTANT]
> The release-please workflow should be given a repository secret
> `RELEASE_PLEASE_TOKEN` (a PAT with `contents: write` + `pull-requests: write`).
> The default `GITHUB_TOKEN` cannot create the Release that triggers the
> downstream `release` workflow (GitHub blocks workflow runs triggered by
> `GITHUB_TOKEN`), so without the PAT nothing gets published. The workflow falls
> back to `GITHUB_TOKEN` when the secret is unset so PR CI keeps working on forks.

## Roadmap

- Streamable HTTP transport + OAuth2 for remote / mobile use
- Visual rendering of key metrics

## License

MIT
