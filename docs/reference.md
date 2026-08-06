# Reference

## Tools

### `health_check()`

Returns a fixed set of keys on every path, so a caller never has to branch on
their presence:

| Key | Meaning |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | Always `zapi-mcp` |
| `version` | Package version |
| `zabbix_url` | Configured URL (empty string when unset) |
| `zabbix_api_version` | Detected API version; `null` until a backend connection succeeds |
| `auth` | `ok` / `error` / `missing-env` |
| `categories` | Names of the loaded `daily_brief` categories |
| `detail` | Present on degraded/error: the reason |
| `categories_error` | Present when the category file failed to parse |

Lightweight by design: it authenticates once (reusing the cached session) and
reads the API version. It does not scan problems or items, so it is safe to
call at session start or after a tool-call timeout.

### `daily_brief()`

The morning report. Structure:

```text
# Daily Brief — 2026-08-06 09:00

## Active Problems (showing 50 of 97)
### High
  [High] Unavailable by ICMP ping  eventid=...  (2026-08-06 07:12, 2h ago)
  … and 14 older (stale; oldest 2024-10-04)

## DHCP Pool Usage
  100.0%  POOL-A   usage
   82.3%  POOL-B   usage
```

Problems are Warning and above, newest-first, each with its age. Anything older
than `ZABBIX_BRIEF_RECENT_HOURS` is folded into the `… and N older` line.
Category sections follow, one per configured `[section]`.

### `get_problems(min_severity=2, tag_name=None, tag_value=None, limit=50)`

Active problems, newest-first with age. The header reads
`Active Problems (showing N of TOTAL)` when the result is capped by `limit`,
and `Active Problems (N)` when it is not — a second count query is issued so
the total is accurate rather than assumed. Output includes `eventid`, which is
what `acknowledge_problem` takes.

Severity: `0` Not classified, `1` Information, `2` Warning, `3` Average,
`4` High, `5` Disaster.

### `get_hosts(role=None, tag_name=None, tag_value=None, group=None)`

Hosts with IP and tags. `role` is shorthand for the `role` tag.

### `get_host_items(host, search=None)`

Current item values for one host (exact hostname). `search` filters item names
by substring.

### `acknowledge_problem(event_ids, message)`

**The only tool that writes.** Acknowledges the given comma-separated event IDs
and attaches a message. It does not close the problems. An acknowledgement is
visible to every operator of that Zabbix and cannot be quietly undone, which is
why the live smoke test skips this tool by name and a unit test enforces the
skip.

## CLI

```bash
zapi-mcp            # start the MCP server (stdio; default)
zapi-mcp --version  # print version and exit
zapi-mcp --check    # verify environment and authentication, then exit
zapi-mcp --brief    # print daily_brief to stdout and exit (handy for cron)
```

Exit codes:

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `--check` | success | config error | auth / connection error |
| `--brief` | success | a section failed (see the `Error:` line in the output) | — |

`--brief` returning non-zero is what distinguishes "nothing is wrong" from "we
could not ask", which the text alone does not.

## Reading capped counts

Both `daily_brief` and `get_problems` may hit their fetch limit
(`ZABBIX_BRIEF_PROBLEM_LIMIT`, `limit`). When they do, the header says
`showing N of TOTAL` — `N` is what you can see, `TOTAL` is what exists. Compare
`TOTAL` against `TOTAL`, never `N` against a previous `TOTAL`.

## Stale problems

Zabbix keeps a problem active until its recovery is confirmed, so long-dead
alerts stay in the list indefinitely. `daily_brief` folds problems older than
the recent window into one line rather than dropping them, so the backlog stays
visible as a number without competing with today's events for attention. Raise
`ZABBIX_BRIEF_RECENT_HOURS` after a multi-day absence to widen what counts as
recent.
