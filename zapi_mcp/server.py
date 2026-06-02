"""Zabbix API MCP Server — tools."""

import os
from datetime import datetime

from mcp.server.fastmcp import FastMCP

from zapi_mcp.categories import Category, load_categories
from zapi_mcp.client import ZapiClient, ZapiError, tag_filter

mcp = FastMCP("zapi-mcp")

_SEVERITY = {
    0: "Not classified",
    1: "Information",
    2: "Warning",
    3: "Average",
    4: "High",
    5: "Disaster",
}

# Zabbix severity levels (Warning and above = the ones worth a morning glance)
SEVERITY_WARNING_AND_ABOVE = [2, 3, 4, 5]
MAX_SEVERITY = 5

# How many item rows to show per brief category (plus any over threshold)
BRIEF_ITEM_LIMIT = 12

# How many active problems to fetch for the brief by default. Large enough to
# cover a real warning+ backlog in one call; if the cap is hit we query an
# accurate total separately so the count is never silently truncated. Tunable
# via ZABBIX_BRIEF_PROBLEM_LIMIT.
DEFAULT_BRIEF_PROBLEM_LIMIT = 1000

# Default "recent" window: problems newer than this are listed in full, older
# ("stale") ones are folded to a count. Tunable via ZABBIX_BRIEF_RECENT_HOURS so
# a morning patrol can focus on what just happened, not year-old fossils that
# Zabbix keeps active because their recovery is never auto-confirmed.
DEFAULT_RECENT_HOURS = 24

# Cached client: a stdio server is long-lived and single-user, so we build and
# authenticate once, reusing the httpx pool and Zabbix session across calls.
_CLIENT: ZapiClient | None = None


def _client() -> ZapiClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = ZapiClient(
            os.environ["ZABBIX_URL"],
            os.environ["ZABBIX_USER"],
            os.environ["ZABBIX_PASSWORD"],
        )
    return _CLIENT


def reset_client() -> None:
    """Drop the cached client so the next call re-authenticates (token refresh)."""
    global _CLIENT
    if _CLIENT is not None:
        try:
            _CLIENT.close()
        except Exception:
            pass
        _CLIENT = None


def _fmt_time(epoch: int | str | None) -> str:
    try:
        e = int(epoch)
    except (TypeError, ValueError):
        return "—"
    if e == 0:
        return "—"
    try:
        return datetime.fromtimestamp(e).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError):
        return str(epoch)


def _severity_name(sev: int | str | None) -> str:
    try:
        return _SEVERITY.get(int(sev), str(sev))
    except (TypeError, ValueError):
        return str(sev)


def _fmt_tags(tags: list[dict]) -> str:
    return ", ".join(f"{t['tag']}={t['value']}" if t.get("value") else t["tag"] for t in tags)


def _is_acked(problem: dict) -> bool:
    """True when the problem's `acknowledged` boolean field is set."""
    return str(problem.get("acknowledged", "0")) == "1"


def _item_value(item: dict) -> float:
    try:
        return float(item.get("lastvalue") or 0)
    except (ValueError, TypeError):
        return 0.0


def _fmt_value(item: dict) -> str:
    """Round numeric values to 1 decimal; pass non-numeric through; — for empty."""
    raw = item.get("lastvalue")
    if raw in (None, ""):
        return "—"
    try:
        return f"{float(raw):.1f}"
    except (ValueError, TypeError):
        return str(raw)


def _clock(problem: dict) -> int:
    """Problem onset epoch as int (0 when missing or unparseable)."""
    try:
        return int(problem.get("clock") or 0)
    except (TypeError, ValueError):
        return 0


def _fmt_age(epoch: int, now_ts: int) -> str:
    """Coarse human age from `epoch` to `now_ts`, e.g. '<1m ago', '5m ago', '3h ago', '47d ago'."""
    if epoch <= 0:
        return "?"
    secs = max(0, now_ts - epoch)
    if secs < 60:
        return "<1m ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _recent_window_seconds() -> int:
    """Seconds of the 'recent' window (env ZABBIX_BRIEF_RECENT_HOURS, default 24h)."""
    try:
        hours = float(os.environ.get("ZABBIX_BRIEF_RECENT_HOURS", DEFAULT_RECENT_HOURS))
    except (TypeError, ValueError):
        hours = float(DEFAULT_RECENT_HOURS)
    return int(max(0.0, hours) * 3600)


def _brief_problem_limit() -> int:
    """Problem fetch cap for the brief (env ZABBIX_BRIEF_PROBLEM_LIMIT, default 1000).

    Parsed via float() then int() so a stray decimal (e.g. "10.5") truncates to a
    usable value rather than silently reverting to the default, matching how
    _recent_window_seconds tolerates fractional input.
    """
    try:
        limit = int(float(os.environ.get("ZABBIX_BRIEF_PROBLEM_LIMIT", DEFAULT_BRIEF_PROBLEM_LIMIT)))
    except (TypeError, ValueError):
        limit = DEFAULT_BRIEF_PROBLEM_LIMIT
    return max(1, limit)


def _window_label(seconds: int) -> str:
    """Human label for the recent window, e.g. '24h', '90m', '30s'.

    Rounds to whole minutes above a minute so a fractional ZABBIX_BRIEF_RECENT_HOURS
    (e.g. 1.001 -> 3603s) still reads as a clean duration rather than raw seconds.
    """
    if seconds < 60:
        return f"{seconds}s"
    minutes = round(seconds / 60)
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _count_fragment(shown: int, total: int) -> str:
    """'5' when the listing is complete, 'showing 5 of 20' when capped."""
    return f"showing {shown} of {total}" if total > shown else f"{total}"


def _problem_line(problem: dict, now_ts: int, *, with_severity: bool = False) -> str:
    """One problem row: name, optional severity, eventid, onset time and age."""
    ack = " [ack]" if _is_acked(problem) else ""
    sev = f"[{_severity_name(problem['severity'])}] " if with_severity else ""
    clock = _clock(problem)
    return (
        f"- {sev}{problem['name']}{ack}  "
        f"eventid={problem.get('eventid', '?')}  ({_fmt_time(clock)}, {_fmt_age(clock, now_ts)})"
    )


def _emit_problem_bucket(
    lines: list[str],
    problems: list[dict],
    now_ts: int,
    recent_window: int,
    *,
    with_severity: bool = False,
) -> None:
    """Append problem rows newest-first: recent ones in full, stale ones folded to a count."""
    ordered = sorted(problems, key=_clock, reverse=True)
    recent = [p for p in ordered if now_ts - _clock(p) <= recent_window]
    stale = [p for p in ordered if now_ts - _clock(p) > recent_window]
    for p in recent:
        lines.append(_problem_line(p, now_ts, with_severity=with_severity))
    if stale:
        oldest = min(_clock(p) for p in stale)
        lines.append(f"- … and {len(stale)} older (stale; oldest {_fmt_time(oldest)})")


def _fetch_problems_with_total(
    client: ZapiClient,
    *,
    severities: list[int] | None = None,
    tags: list[dict] | None = None,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    """Fetch problems (capped at `limit`) plus the accurate total.

    `limit` defaults to the brief's configurable cap (ZABBIX_BRIEF_PROBLEM_LIMIT);
    callers that honour a user-supplied limit pass it explicitly. When the fetch
    hits the cap, the total is queried via countOutput so callers can report
    'showing N of TOTAL' rather than silently truncating. If only the (secondary)
    count query fails, we keep the fetched rows and fall back to their count
    rather than discarding everything.
    """
    if limit is None:
        limit = _brief_problem_limit()
    problems = client.get_problems(severities=severities, tags=tags, limit=limit)
    if len(problems) < limit:
        return problems, len(problems)
    try:
        total = client.count_problems(severities=severities, tags=tags)
    except ZapiError:
        total = len(problems)
    return problems, max(total, len(problems))


# ------------------------------------------------------------------
# daily_brief — category-driven morning patrol
# ------------------------------------------------------------------
def _brief_item_category(client: ZapiClient, cat: Category) -> list[str]:
    hosts = client.get_hosts(tags=[tag_filter(cat.tag, cat.tag_value)])
    lines = [f"\n## {cat.name} ({len(hosts)} hosts)"]
    if not hosts:
        lines.append("No hosts found for this category.")
        return lines
    host_ids = [h["hostid"] for h in hosts]
    host_name = {h["hostid"]: h["host"] for h in hosts}
    items = client.get_items(host_ids, key=cat.item_key, key_search=cat.item_key_search)
    if not items:
        which = cat.item_key or cat.item_key_search
        lines.append(f"No items matching '{which}' found.")
        return lines

    ranked = sorted(items, key=_item_value, reverse=True)
    over = [it for it in ranked if cat.threshold is not None and _item_value(it) >= cat.threshold]
    # Show every item at/over threshold, then fill to the cap with the highest.
    shown = ranked[: max(BRIEF_ITEM_LIMIT, len(over))]

    for item in shown:
        host = host_name.get(item.get("hostid", ""), "")
        name = item.get("name", "")
        # For per-host gauges (item name == the configured key) the host already
        # identifies the row; otherwise include the item name to disambiguate.
        label = host
        if name and name != cat.item_key:
            label = f"{host} {name}".strip()
        flag = "  ⚠️" if cat.threshold is not None and _item_value(item) >= cat.threshold else ""
        units = item.get("units") or ""
        unit_str = f" {units}" if units else ""
        lines.append(f"- {label}: {_fmt_value(item)}{unit_str}{flag}  ({_fmt_time(item.get('lastclock'))})")

    remaining = len(ranked) - len(shown)
    if remaining > 0:
        lines.append(f"- … and {remaining} more (≤ {_fmt_value(shown[-1])})")
    return lines


def _brief_problem_category(client: ZapiClient, cat: Category, now_ts: int, recent_window: int) -> list[str]:
    problems, total = _fetch_problems_with_total(client, tags=[tag_filter(cat.tag, cat.tag_value)])
    noun = "problem" if total == 1 else "problems"
    lines = [f"\n## {cat.name} ({_count_fragment(len(problems), total)} active {noun})"]
    if not problems:
        lines.append("No active problems.")
        return lines
    _emit_problem_bucket(lines, problems, now_ts, recent_window, with_severity=True)
    return lines


@mcp.tool()
def health_check() -> dict:
    """Report server version, Zabbix connectivity, and configured categories.

    Call this at session start (or after a tool-call timeout) to confirm the MCP
    is up, see which version is running, verify the Zabbix backend is reachable
    and authenticated, and list the daily_brief categories that are loaded.
    Lightweight: it authenticates once (reusing the cached session) and reads the
    detected API version — it does NOT scan problems or items.

    Returns ``status`` (healthy / degraded / error), ``service``, ``version``,
    ``zabbix_url``, ``zabbix_api_version``, ``auth`` (ok / error / missing-env),
    and ``categories`` (the configured daily_brief section names).
    """
    from zapi_mcp import __version__

    result: dict = {
        "status": "healthy",
        "service": "zapi-mcp",
        "version": __version__,
    }

    # Category loading is local (no network), so report it regardless of whether
    # the Zabbix backend is reachable. A genuine parse error degrades the server;
    # an empty list (nothing configured) is a healthy, expected state.
    try:
        result["categories"] = [c.name for c in load_categories()]
    except Exception as e:  # noqa: BLE001 — surface config errors, don't sink the check
        result["status"] = "degraded"
        result["categories"] = []
        result["categories_error"] = str(e)

    # Backend: building the client detects the API version (apiinfo.version, no
    # auth) and logs in. Reuse the cached singleton so this is one cheap round trip.
    try:
        client = _client()
        result["zabbix_url"] = os.environ.get("ZABBIX_URL", "")
        result["zabbix_api_version"] = client.version
        result["auth"] = "ok"
    except KeyError as e:
        result["status"] = "error"
        result["auth"] = "missing-env"
        result["detail"] = f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        result["status"] = "degraded"
        result["auth"] = "error"
        result["detail"] = f"Zabbix error: {e}"

    return result


@mcp.tool()
def daily_brief() -> str:
    """Morning patrol summary.

    Reports active problems (Warning and above), then one section per category
    configured via ZABBIX_CATEGORIES_INI (e.g. DHCP pool usage, SNAT session
    usage, core-network problems). Item-based categories show current values
    sorted high-to-low; problem-based categories list active problems.

    Problems are listed newest-first with their age; those older than the recent
    window (ZABBIX_BRIEF_RECENT_HOURS, default 24h) are folded to a count so a
    long-standing backlog of un-recovered fossils doesn't bury today's events.
    Section headers show the true total ('showing N of TOTAL' when capped).
    """
    try:
        client = _client()
    except KeyError as e:
        return f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        return f"Zabbix error: {e}"

    now_dt = datetime.now().astimezone()
    now_ts = int(now_dt.timestamp())
    recent_window = _recent_window_seconds()
    window_label = _window_label(recent_window)
    lines = [f"# Daily Brief — {now_dt.strftime('%Y-%m-%d %H:%M')}"]

    # Active problems (Warning and above), newest first; stale ones folded away.
    try:
        problems, total = _fetch_problems_with_total(client, severities=SEVERITY_WARNING_AND_ABOVE)
        lines.append(f"\n## Active Problems ({_count_fragment(len(problems), total)})")
        if not problems:
            lines.append("No active problems.")
        else:
            by_sev: dict[int, list] = {}
            for p in problems:
                by_sev.setdefault(int(p["severity"]), []).append(p)
            for sev in sorted(by_sev, reverse=True):
                bucket = by_sev[sev]
                n_recent = sum(1 for p in bucket if now_ts - _clock(p) <= recent_window)
                lines.append(f"\n### {_severity_name(sev)} ({len(bucket)}, {n_recent} in last {window_label})")
                _emit_problem_bucket(lines, bucket, now_ts, recent_window)
    except ZapiError as e:
        # First real call failed (often a stale token); drop the client so the
        # next invocation re-authenticates.
        reset_client()
        lines.append(f"\n## Active Problems\nError: {e}")
        return "\n".join(lines)

    # Per-category sections
    categories = load_categories()
    if not categories:
        lines.append(
            "\n(No categories configured. Set ZABBIX_CATEGORIES_INI to add "
            "DHCP / SNAT / core-network sections — see categories.ini.example.)"
        )
    for cat in categories:
        try:
            if cat.kind == "items":
                lines.extend(_brief_item_category(client, cat))
            else:
                lines.extend(_brief_problem_category(client, cat, now_ts, recent_window))
        except ZapiError as e:
            lines.append(f"\n## {cat.name}\nError: {e}")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Problems
# ------------------------------------------------------------------
@mcp.tool()
def get_problems(
    min_severity: int = 2,
    tag_name: str | None = None,
    tag_value: str | None = None,
    limit: int = 50,
) -> str:
    """Get active Zabbix problems, newest first.

    Problems are listed newest-first and annotated with their age. The header
    shows the true total ('showing N of TOTAL' when the result is capped by
    `limit`), so a capped listing is never mistaken for the full picture.

    Args:
        min_severity: Minimum severity (0=Not classified, 1=Info, 2=Warning, 3=Average, 4=High, 5=Disaster)
        tag_name: Filter by tag name (optional)
        tag_value: Filter by tag value (optional, requires tag_name)
        limit: Maximum number of problems to return (floored at 1; when the result
            hits this cap a second count query is issued to report the true total)
    """
    if min_severity > MAX_SEVERITY:
        return "No problems at/above the requested severity."
    try:
        client = _client()
        severities = list(range(max(min_severity, 0), 6))
        tags = [tag_filter(tag_name, tag_value)] if tag_name else None
        problems, total = _fetch_problems_with_total(client, severities=severities, tags=tags, limit=max(1, limit))
    except KeyError as e:
        return f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        return f"Zabbix error: {e}"
    if not problems:
        return "No active problems."
    now_ts = int(datetime.now().astimezone().timestamp())
    problems = sorted(problems, key=_clock, reverse=True)
    lines = [f"Active Problems ({_count_fragment(len(problems), total)}):"]
    for p in problems:
        lines.append(_problem_line(p, now_ts, with_severity=True))
        tag_str = _fmt_tags(p.get("tags", []))
        if tag_str:
            lines.append(f"  tags: {tag_str}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Hosts
# ------------------------------------------------------------------
@mcp.tool()
def get_hosts(
    role: str | None = None,
    tag_name: str | None = None,
    tag_value: str | None = None,
    group: str | None = None,
) -> str:
    """List Zabbix hosts filtered by tag or group.

    Args:
        role: Filter by role tag value (e.g. 'main', 'edge')
        tag_name: Filter by arbitrary tag name
        tag_value: Filter by tag value (requires tag_name)
        group: Filter by host group name
    """
    try:
        client = _client()
        tags = []
        if role:
            tags.append(tag_filter("role", role))
        if tag_name:
            tags.append(tag_filter(tag_name, tag_value))
        hosts = client.get_hosts(tags=tags or None, group=group)
    except KeyError as e:
        return f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        return f"Zabbix error: {e}"
    if not hosts:
        return "No hosts found."
    lines = [f"Hosts ({len(hosts)}):"]
    for h in sorted(hosts, key=lambda x: x["host"]):
        tag_str = _fmt_tags(h.get("tags", []))
        interfaces = h.get("interfaces") or [{}]
        ip = interfaces[0].get("ip", "—")
        lines.append(f"  {h['host']}  {ip}  [{tag_str}]")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Items (current values)
# ------------------------------------------------------------------
@mcp.tool()
def get_host_items(host: str, search: str | None = None) -> str:
    """Get current item values for a host.

    Args:
        host: Hostname (exact match)
        search: Filter items by name (partial match)
    """
    try:
        client = _client()
        hosts = client.get_hosts(host=host)
        if not hosts:
            return f"Host '{host}' not found."
        items = client.get_items([hosts[0]["hostid"]], name_search=search)
    except KeyError as e:
        return f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        return f"Zabbix error: {e}"
    if not items:
        return f"No items found for '{host}'."
    lines = [f"Items for {host} ({len(items)}):"]
    for item in sorted(items, key=lambda x: x["name"]):
        ts = _fmt_time(item.get("lastclock"))
        val = item.get("lastvalue") or "—"
        lines.append(f"  {item['name']}: {val} {item.get('units', '')}  ({ts})")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Acknowledge
# ------------------------------------------------------------------
@mcp.tool()
def acknowledge_problem(event_ids: str, message: str) -> str:
    """Acknowledge Zabbix problems and add a message (does not close them).

    Args:
        event_ids: Comma-separated event IDs (from get_problems output)
        message: Acknowledgement message
    """
    ids = [eid.strip() for eid in event_ids.split(",") if eid.strip()]
    if not ids:
        return "No event IDs provided."
    try:
        client = _client()
        result = client.acknowledge_problem(ids, message)
    except KeyError as e:
        return f"Missing environment variable: {e}"
    except ZapiError as e:
        reset_client()
        return f"Zabbix error: {e}"
    return f"Acknowledged {len(ids)} event(s): {result}"
