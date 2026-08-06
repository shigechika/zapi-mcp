# zapi-mcp

MCP server for the [Zabbix](https://www.zabbix.com/) API.

Built for network operations: a single `daily_brief` call summarizes active
problems plus site-specific categories (DHCP pool usage, SNAT session usage,
core-network problems, …), and individual tools query problems, hosts and item
values.

## Tools

| Tool | Description |
|---|---|
| `health_check` | Server version, Zabbix connectivity/auth, detected API version, and the configured `daily_brief` categories — call at session start or after a timeout |
| `daily_brief` | Morning patrol: active problems (Warning and above) plus one section per configured category |
| `get_problems` | Active problems by severity and tag, newest-first with age; output includes `eventid` |
| `get_hosts` | Hosts filtered by role / tag / group, with IP and tags |
| `get_host_items` | Current item values for one host |
| `acknowledge_problem` | Acknowledge problems and add a message (does not close them) |

Everything except `acknowledge_problem` is read-only.

## Design notes

**Organization-specific knowledge lives in a config file, not the code.** Which
host tags mean "DHCP pool" or "core network", which item keys carry usage
percentages, and what threshold matters — all of it comes from
`ZABBIX_CATEGORIES_INI`. The server itself knows nothing about any particular
installation, so the same package works unmodified elsewhere. See
[Categories for daily_brief](categories.md).

**A backlog must not bury what just happened.** Zabbix keeps problems active
until their recovery is confirmed, so an installation accumulates alerts that
have been "active" for years (an ICMP ping down on a decommissioned host, an
RDP service nobody restarted). `daily_brief` lists problems newest-first with
their age and folds anything older than the recent window into a single
`… and N older (stale; oldest …)` line.

**Counts are never silently truncated.** Section headers carry the true total
and show `showing N of TOTAL` when the fetch hits its cap. A capped listing
that printed only its own length would read as the complete picture, which is
exactly the failure this avoids.

**Auth adapts to the server version.** Zabbix 6.0 LTS expects `user` plus an
`auth` field; 6.4 and 7.0 expect `username` plus an `Authorization: Bearer`
header. The client detects the API version and uses the right form, so the same
package works across an upgrade.

## Next steps

- [Setup](setup.md) — install, environment variables, MCP client registration
- [Categories for daily_brief](categories.md) — the INI that shapes the morning report
- [Reference](reference.md) — tools, CLI, exit codes, output formats
