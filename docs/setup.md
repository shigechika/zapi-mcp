# Setup

## Install

```bash
uv pip install zapi-mcp
# or
pip install zapi-mcp
```

From source:

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp
uv sync          # or: pip install -e .
```

## Zabbix account

The API user needs **read permission on the host groups you query**, plus
acknowledge permission if you intend to use `acknowledge_problem`. Nothing else
is required — no super-admin role, no write access to configuration.

Creating a dedicated API user rather than reusing a person's account keeps the
audit trail readable and survives that person leaving.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `ZABBIX_URL` | Zabbix base URL (e.g. `https://zabbix.example.com`); `/api_jsonrpc.php` is appended if absent | *required* |
| `ZABBIX_USER` | Zabbix API user | *required* |
| `ZABBIX_PASSWORD` | Zabbix API password | *required* |
| `ZABBIX_CATEGORIES_INI` | Path to a categories INI for `daily_brief` | — |
| `ZABBIX_BRIEF_RECENT_HOURS` | `daily_brief` "recent" window in hours; older problems are folded to a count | `24` |
| `ZABBIX_BRIEF_PROBLEM_LIMIT` | Max active problems `daily_brief` fetches per call before counting the rest | `1000` |

!!! tip "Verify before wiring it into anything"
    ```bash
    zapi-mcp --check
    ```
    Exit `0` means the environment is complete and authentication succeeded;
    `1` is a config error, `2` an auth or connection error. Running this once
    turns "the tool returns nothing" into a question you have already answered.

## Register with an MCP client

### Claude Code

`.mcp.json`:

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

`claude_desktop_config.json`:

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

### Direct execution

```bash
export ZABBIX_URL=https://zabbix.example.com
export ZABBIX_USER=api-user
export ZABBIX_PASSWORD=your-password
zapi-mcp
```

## Zabbix version compatibility

Authentication is version-adaptive: the client detects the API version and
sends `user` + `auth` field against 6.0 LTS, or `username` +
`Authorization: Bearer` against 6.4 and 7.0. No configuration selects this —
an upgrade of the Zabbix server needs no change here.

`health_check` reports the detected version in `zabbix_api_version`, which is
the quickest way to confirm what the server actually answered with.

## Next

Add site-specific sections to the morning report:
[Categories for daily_brief](categories.md).
