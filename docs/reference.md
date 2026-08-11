# Reference

## Tools

### `health_check()`

These keys are present on every path, so judging health never requires probing
for their existence — read `status` and the rest is there:

| Key | Meaning |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | Always `zapi-mcp` |
| `version` | Package version |
| `zabbix_url` | Configured URL (empty string when unset) |
| `zabbix_api_version` | Detected API version; `null` until a backend connection succeeds |
| `auth` | `ok` / `error` / `missing-env` |
| `categories` | Names of the loaded `daily_brief` categories |

Two further keys appear only when they have something to say:

| Key | Appears when |
|---|---|
| `detail` | A backend problem occurred: a missing environment variable (`status=error`, `auth=missing-env`) or a Zabbix error (`status=degraded`, `auth=error`) |
| `categories_error` | The category file failed to parse (`status=degraded`) |

The two are independent. A run whose only fault is an unparsable category file
reports `status=degraded` with `categories_error` and **no** `detail`, because
the backend itself was fine.

Lightweight by design: it authenticates once (reusing the cached session) and
reads the API version. It does not scan problems or items, so it is safe to
call at session start or after a tool-call timeout.

### `daily_brief()`

The morning report. Structure:

```text
# Daily Brief — 2026-08-06 09:00

## Active Problems (showing 50 of 97)

### High (23, 2 in last 24h)
- Unavailable by ICMP ping  eventid=18813696  (2026-08-06 07:12, 2h ago)
- … and 21 older (stale; oldest 2024-10-04 10:39)

## In Maintenance (1 window)
- Legal-inspection-2608110900h  until 2026-08-11 17:00:00  (12 hosts: sw-01, sw-02, … and 10 more)

## DHCP Pool Usage (2 hosts)
- POOL-A: 100.0 %  ⚠️  (2026-08-06 09:00:00)
- POOL-B: 82.3 %  (2026-08-06 09:00:00)
```

Problems are Warning and above, newest-first, each with its `eventid`, onset
time and age. The severity heading carries both the bucket size and how many of
those are recent. Anything older than `ZABBIX_BRIEF_RECENT_HOURS` is folded into
the `… and N older` line — note that the severity name is not repeated on each
row, since the heading already states it.

Right after Active Problems, `## In Maintenance` lists hosts under a
maintenance window that's active right now, plus any window starting later
today — cross-check these before treating another tool's finding about the
same hosts as a new incident. The section is **omitted entirely** when
there's nothing to show; a brief with no such section means no host is
currently (or about to be, today) under a registered window. See
`get_maintenance_windows()` below for windows starting further out, or for
expired ones.

Category sections follow, one per configured `[section]`, with `⚠️` marking
values past the threshold.

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

**The only tool that writes** (besides `set_maintenance`). Acknowledges the
given comma-separated event IDs and attaches a message. It does not close the
problems. An acknowledgement is visible to every operator of that Zabbix and
cannot be quietly undone, which is why the live smoke test skips this tool by
name and a unit test enforces the skip.

### `get_maintenance_windows(include_expired=False)`

The read counterpart to `set_maintenance`. Lists Zabbix maintenance windows,
grouped Active / Upcoming (and Expired when `include_expired=True`):

```text
Maintenance Windows (1 active, 1 upcoming):

## Active
- Legal-inspection-2608110900h  2026-08-11 09:00:00 → 2026-08-11 17:00:00
  Annual legal inspection
  12 hosts: sw-01, sw-02, rt-01, rt-02, ap-01, ap-02, fw-01, fw-02, … and 4 more

## Upcoming
- UPS-check-2608150900h  2026-08-15 09:00:00 → 2026-08-15 12:00:00  [no data collection]
  UPS battery replacement
  2 hosts: b-sw-01, b-sw-02
```

"Active" means the current time falls inside the window's own time period,
not just its outer `active_since`/`active_till` frame — exact for a one-time
window (the kind `set_maintenance`/`set_maintenance_for_hosts` create). A
window with a recurring time period (set up outside this server, e.g. via the
Zabbix UI) is instead evaluated against its outer frame only and labeled
`(recurring)`. `[no data collection]` marks a window that also suspends data
collection, not just alerting. Expired windows accumulate over time since
`set_maintenance` never deletes them, so they're excluded unless
`include_expired=True` is passed. Empty result: `No maintenance windows.`

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
| `--brief` | success | missing environment variables, **or** a section failed | — |

`--brief` returning non-zero is what distinguishes "nothing is wrong" from "we
could not ask", which the text alone does not.

!!! warning "Do not detect failure by grepping stdout"
    Exit 1 covers two cases that look different in the output. Missing
    environment variables are reported on **stderr** and stdout stays empty —
    there is no brief and no `Error:` line to find. A backend failure does print
    a brief, but the embedded line reads `Zabbix error: …` or
    `Missing environment variable: …` rather than starting with `Error:`. A
    monitor that only looks for `Error:` in stdout misses both. Check the exit
    status.

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
