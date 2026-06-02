"""Tests for MCP tool output (server.py)."""

import json
from datetime import datetime

import httpx
import respx
from freezegun import freeze_time

from tests.conftest import ENDPOINT, SAMPLE_HOST, SAMPLE_ITEM, SAMPLE_PROBLEM, make_router
from zapi_mcp import server

# A fixed instant so time-dependent assertions (age, recent/stale split) are
# deterministic regardless of when/where the suite runs.
FROZEN_NOW = "2026-06-01 12:00:00"


def _call(tool):
    """FastMCP wraps functions; call the underlying fn."""
    return getattr(tool, "fn", tool)


def _frozen_now_ts() -> int:
    """The epoch the server derives under freeze (matches datetime.now().astimezone())."""
    return int(datetime.now().astimezone().timestamp())


# ---- get_problems ---------------------------------------------------------


def test_get_problems_lists_eventid_for_acknowledgement():
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        out = _call(server.get_problems)()
    assert "eventid=5001" in out
    assert "High CPU on core-rt1" in out
    assert "[High]" in out
    assert "role=main" in out


def test_get_problems_empty():
    with make_router(results={"problem.get": []}):
        out = _call(server.get_problems)()
    assert out == "No active problems."


def test_get_problems_min_severity_filter():
    r = make_router(results={"problem.get": [SAMPLE_PROBLEM]})
    with r:
        _call(server.get_problems)(min_severity=4)
    call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "problem.get")
    assert call["params"]["severities"] == [4, 5]


def test_get_problems_out_of_range_severity_returns_none_not_all():
    """min_severity > 5 must short-circuit, not fall through to all severities."""
    r = make_router(results={"problem.get": [SAMPLE_PROBLEM]})
    with r:
        out = _call(server.get_problems)(min_severity=6)
    assert "No problems at/above" in out
    assert not any(x["payload"]["method"] == "problem.get" for x in r.captured)


def test_get_problems_acked_indicator_uses_acknowledged_field():
    acked = dict(SAMPLE_PROBLEM, acknowledged="1", acknowledges="0")
    with make_router(results={"problem.get": [acked]}):
        out = _call(server.get_problems)()
    assert "[ack]" in out


@freeze_time(FROZEN_NOW)
def test_get_problems_lists_newest_first_with_age():
    """get_problems lists newest-first (by clock) and annotates each row with its age."""
    now = _frozen_now_ts()
    # eventid is inversely correlated with recency (the older problem has the higher
    # eventid), so newest-first ordering can only come from sorting on clock.
    older = dict(SAMPLE_PROBLEM, eventid="9", name="Older one", clock=str(now - 7200))  # 2h
    newer = dict(SAMPLE_PROBLEM, eventid="2", name="Newer one", clock=str(now - 600))  # 10m
    with make_router(results={"problem.get": [older, newer]}):
        out = _call(server.get_problems)()
    assert out.index("Newer one") < out.index("Older one")  # re-sorted by clock, not eventid
    assert "10m ago)" in out and "2h ago)" in out
    assert "Active Problems (2):" in out  # not capped (default limit 50 > 2)


@freeze_time(FROZEN_NOW)
def test_get_problems_shows_total_when_capped():
    """A user limit that caps the result reports 'showing N of TOTAL' via a real count query."""
    now = _frozen_now_ts()
    p1 = dict(SAMPLE_PROBLEM, eventid="1", clock=str(now - 60))
    p2 = dict(SAMPLE_PROBLEM, eventid="2", clock=str(now - 120))
    r = make_router(results={"problem.get": [p1, p2]})
    with r:
        out = _call(server.get_problems)(limit=1)
    assert "Active Problems (showing 1 of 2):" in out
    # The total must come from an actual countOutput query carrying the same filter.
    count_calls = [
        x["payload"]
        for x in r.captured
        if x["payload"]["method"] == "problem.get" and x["payload"]["params"].get("countOutput")
    ]
    assert len(count_calls) == 1
    assert count_calls[0]["params"]["severities"] == [2, 3, 4, 5]


def test_get_problems_zabbix_error_resets_client():
    def handler(request):
        payload = json.loads(request.content)
        m = payload["method"]
        if m in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if m == "apiinfo.version" else "tok", "id": 1})
        return httpx.Response(200, json={"error": {"message": "boom"}, "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.get_problems)()
    assert "Zabbix error" in out
    assert server._CLIENT is None  # reset after error


# ---- get_hosts ------------------------------------------------------------


def test_get_hosts_shows_ip_and_tags():
    with make_router(results={"host.get": [SAMPLE_HOST]}):
        out = _call(server.get_hosts)(role="main")
    assert "pool-a" in out
    assert "192.0.2.1" in out


def test_get_hosts_role_builds_equal_filter():
    r = make_router(results={"host.get": [SAMPLE_HOST]})
    with r:
        _call(server.get_hosts)(role="main")
    call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "host.get")
    assert {"tag": "role", "value": "main", "operator": "1"} in call["params"]["tags"]


def test_get_hosts_empty():
    with make_router(results={"host.get": []}):
        out = _call(server.get_hosts)()
    assert out == "No hosts found."


# ---- get_host_items -------------------------------------------------------


def test_get_host_items_uses_server_side_host_filter():
    r = make_router(results={"host.get": [SAMPLE_HOST], "item.get": [SAMPLE_ITEM]})
    with r:
        out = _call(server.get_host_items)("pool-a")
    assert "usage" in out
    host_call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "host.get")
    assert host_call["params"]["filter"] == {"host": "pool-a"}


def test_get_host_items_host_not_found():
    with make_router(results={"host.get": []}):
        out = _call(server.get_host_items)("ghost")
    assert "not found" in out


# ---- acknowledge_problem --------------------------------------------------


def test_acknowledge_parses_comma_separated_ids():
    r = make_router()
    with r:
        out = _call(server.acknowledge_problem)("5001, 5002", "ack msg")
    call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "event.acknowledge")
    assert call["params"]["eventids"] == ["5001", "5002"]
    assert "Acknowledged 2" in out


def test_acknowledge_empty_ids():
    with make_router():
        out = _call(server.acknowledge_problem)("  ", "msg")
    assert out == "No event IDs provided."


# ---- health_check ---------------------------------------------------------


def test_health_check_reports_version_and_backend(monkeypatch):
    from zapi_mcp import __version__

    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    with make_router(version="6.0.42"):
        out = _call(server.health_check)()
    assert out["status"] == "healthy"
    assert out["service"] == "zapi-mcp"
    assert out["version"] == __version__
    assert out["zabbix_api_version"] == "6.0.42"
    assert out["auth"] == "ok"
    assert out["categories"] == []  # none configured = healthy, empty list


def test_health_check_lists_configured_categories(monkeypatch, tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\nname = DHCP Pool Usage\ntag = dhcp-pool-usage\nitem_key = usage\nthreshold = 80\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    with make_router():
        out = _call(server.health_check)()
    assert out["status"] == "healthy"
    assert out["categories"] == ["DHCP Pool Usage"]


def test_health_check_missing_env_is_error(monkeypatch):
    """A missing connection env var yields status=error, not a crash."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.delenv("ZABBIX_URL", raising=False)
    out = _call(server.health_check)()  # no router: must not reach the network
    assert out["status"] == "error"
    assert out["auth"] == "missing-env"
    assert "ZABBIX_URL" in out["detail"]
    assert out["version"]  # version is still reported even when the backend is down
    assert out["zabbix_api_version"] is None  # fixed shape: key present, no value yet


def test_health_check_backend_error_is_degraded(monkeypatch):
    """A Zabbix auth/connection failure yields degraded + auth=error, client reset."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)

    def handler(request):
        payload = json.loads(request.content)
        if payload["method"] == "apiinfo.version":
            return httpx.Response(200, json={"result": "6.0.0", "id": 1})
        return httpx.Response(200, json={"error": {"message": "Incorrect user name or password"}, "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.health_check)()
    assert out["status"] == "degraded"
    assert out["auth"] == "error"
    assert "Zabbix error" in out["detail"]
    assert server._CLIENT is None  # reset after error so the next call re-auths


def test_health_check_bad_categories_is_degraded(monkeypatch, tmp_path):
    """A malformed categories INI degrades status but leaves the backend healthy."""
    p = tmp_path / "bad.ini"
    p.write_text("this is not a valid ini\nno section header here\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    with make_router():
        out = _call(server.health_check)()
    assert out["status"] == "degraded"
    assert out["categories"] == []
    assert "categories_error" in out
    assert out["auth"] == "ok"  # backend reachable; only category parsing failed


# ---- daily_brief ----------------------------------------------------------


def test_daily_brief_no_categories(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        out = _call(server.daily_brief)()
    assert "# Daily Brief" in out
    assert "Active Problems" in out
    assert "No categories configured" in out


def test_daily_brief_item_category(monkeypatch, tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\nname = DHCP Pool Usage\ntag = dhcp-pool-usage\nitem_key = usage\nthreshold = 80\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    results = {"problem.get": [], "host.get": [SAMPLE_HOST], "item.get": [SAMPLE_ITEM]}
    with make_router(results=results):
        out = _call(server.daily_brief)()
    assert "DHCP Pool Usage" in out
    assert "85.5" in out
    assert "⚠️" in out  # 85.5 >= threshold 80


def test_daily_brief_item_category_search_key_and_rounds(monkeypatch, tmp_path):
    """SNAT-style keys (pool.node0.usage) are matched by substring; values rounded."""
    p = tmp_path / "cats.ini"
    p.write_text("[snat]\nname = SNAT\ntag = snat\nitem_key_search = .usage\nthreshold = 80\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    item = dict(
        SAMPLE_ITEM,
        name="EDUROAM-SNAT-CSTS-pool.node0.usage",
        key_="EDUROAM-SNAT-CSTS-pool.node0.usage",
        lastvalue="92.345",
    )
    r = make_router(results={"problem.get": [], "host.get": [SAMPLE_HOST], "item.get": [item]})
    with r:
        out = _call(server.daily_brief)()
    # value rounded to 1 decimal, item name shown (label != bare key), flagged
    assert "92.3" in out
    assert "92.345" not in out
    assert "EDUROAM-SNAT-CSTS-pool.node0.usage" in out
    assert "⚠️" in out
    # client must have searched the key, not filtered exactly
    call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "item.get")
    assert call["params"]["search"] == {"key_": ".usage"}


def test_fmt_value_rounds_and_handles_empty():
    assert server._fmt_value({"lastvalue": "70.40816"}) == "70.4"
    assert server._fmt_value({"lastvalue": ""}) == "—"
    assert server._fmt_value({"lastvalue": None}) == "—"
    assert server._fmt_value({"lastvalue": "up"}) == "up"


def test_daily_brief_problem_category(monkeypatch, tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[core]\nname = Core Network\ntag = role\ntag_value = main\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    results = {"problem.get": [SAMPLE_PROBLEM], "host.get": [SAMPLE_HOST]}
    with make_router(results=results):
        out = _call(server.daily_brief)()
    assert "Core Network" in out


def test_daily_brief_missing_env(monkeypatch):
    monkeypatch.delenv("ZABBIX_URL", raising=False)
    out = _call(server.daily_brief)()
    assert "Missing environment variable" in out
    monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")


# ---- daily_brief: recency & truncation (issues #1, #2) --------------------


@freeze_time(FROZEN_NOW)
def test_daily_brief_lists_recent_problem_with_age(monkeypatch):
    """A problem within the recent window is listed in full with its age."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.delenv("ZABBIX_BRIEF_RECENT_HOURS", raising=False)
    recent = dict(SAMPLE_PROBLEM, clock=str(_frozen_now_ts() - 3600))  # 1h ago
    with make_router(results={"problem.get": [recent]}):
        out = _call(server.daily_brief)()
    assert "High CPU on core-rt1" in out
    assert "1h ago)" in out  # age annotation present
    assert "stale" not in out
    assert "### High (1, 1 in last 24h)" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_folds_stale_problems(monkeypatch):
    """Fossil problems (older than the window) are folded to a count, not listed."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.delenv("ZABBIX_BRIEF_RECENT_HOURS", raising=False)
    # SAMPLE_PROBLEM clock is 2023 -> stale relative to the frozen 2026 'now'.
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        out = _call(server.daily_brief)()
    assert "… and 1 older (stale; oldest 2023-" in out
    assert "High CPU on core-rt1" not in out  # folded, not listed individually
    assert "### High (1, 0 in last 24h)" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_shows_total_when_truncated(monkeypatch):
    """Capping the fetch must report 'showing N of TOTAL', not a silent cut."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "1")
    now = _frozen_now_ts()
    p1 = dict(SAMPLE_PROBLEM, eventid="1", clock=str(now - 60))
    p2 = dict(SAMPLE_PROBLEM, eventid="2", clock=str(now - 120))
    with make_router(results={"problem.get": [p1, p2]}):
        out = _call(server.daily_brief)()
    assert "## Active Problems (showing 1 of 2)" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_recent_hours_env_widens_window(monkeypatch):
    """ZABBIX_BRIEF_RECENT_HOURS controls what counts as recent (issue #1 option)."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.setenv("ZABBIX_BRIEF_RECENT_HOURS", "1000000")  # ~114y: everything recent
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        out = _call(server.daily_brief)()
    assert "High CPU on core-rt1" in out
    assert "stale" not in out
    assert "in last 1000000h" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_problem_category_recent_and_severity(monkeypatch, tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[core]\nname = Core Network\ntag = role\ntag_value = main\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    monkeypatch.delenv("ZABBIX_BRIEF_RECENT_HOURS", raising=False)
    recent = dict(SAMPLE_PROBLEM, clock=str(_frozen_now_ts() - 600))
    results = {"problem.get": [recent], "host.get": [SAMPLE_HOST]}
    with make_router(results=results):
        out = _call(server.daily_brief)()
    assert "Core Network (1 active problem)" in out  # singular for a count of 1
    assert "[High] High CPU on core-rt1" in out  # category rows carry severity


@freeze_time(FROZEN_NOW)
def test_daily_brief_buckets_by_severity(monkeypatch):
    """Each severity gets its own bucket header with the right total/recent split."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.delenv("ZABBIX_BRIEF_RECENT_HOURS", raising=False)
    now = _frozen_now_ts()
    problems = [
        dict(SAMPLE_PROBLEM, eventid="1", name="Disaster now", severity="5", clock=str(now - 300)),
        dict(SAMPLE_PROBLEM, eventid="2", name="High recent", severity="4", clock=str(now - 600)),
        dict(SAMPLE_PROBLEM, eventid="3", name="High fossil", severity="4", clock="1700000000"),
        dict(SAMPLE_PROBLEM, eventid="4", name="Average recent", severity="3", clock=str(now - 900)),
    ]
    with make_router(results={"problem.get": problems}):
        out = _call(server.daily_brief)()
    assert "## Active Problems (4)" in out
    assert "### Disaster (1, 1 in last 24h)" in out
    assert "### High (2, 1 in last 24h)" in out
    assert "### Average (1, 1 in last 24h)" in out
    assert "Disaster now" in out and "High recent" in out and "Average recent" in out
    assert "High fossil" not in out  # stale -> folded, not listed
    assert "… and 1 older (stale" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_truncation_total_respects_severity(monkeypatch):
    """The 'showing N of TOTAL' total must reflect the severity filter, not all rows."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "1")
    now = _frozen_now_ts()
    warn_plus = [
        dict(SAMPLE_PROBLEM, eventid="1", severity="4", clock=str(now - 60)),
        dict(SAMPLE_PROBLEM, eventid="2", severity="3", clock=str(now - 120)),
    ]
    below = dict(SAMPLE_PROBLEM, eventid="3", severity="1", clock=str(now - 180))  # below Warning
    with make_router(results={"problem.get": warn_plus + [below]}):
        out = _call(server.daily_brief)()
    # The Information-level row is excluded from the warning+ total -> 2, not 3.
    assert "## Active Problems (showing 1 of 2)" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_survives_count_failure(monkeypatch):
    """If only the secondary count query fails, the section still renders (falls back)."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "1")
    now = _frozen_now_ts()

    def handler(request):
        payload = json.loads(request.content)
        m = payload["method"]
        if m in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if m == "apiinfo.version" else "tok", "id": 1})
        if m == "problem.get":
            if payload["params"].get("countOutput"):
                return httpx.Response(200, json={"result": "oops", "id": 1})  # malformed count
            return httpx.Response(200, json={"result": [dict(SAMPLE_PROBLEM, clock=str(now - 60))], "id": 1})
        return httpx.Response(200, json={"result": [], "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.daily_brief)()
    assert "## Active Problems (1)" in out  # count failed -> fell back to the fetched floor
    assert "High CPU on core-rt1" in out  # section rendered, not replaced by an error


# ---- helpers --------------------------------------------------------------


def test_fmt_age_buckets():
    now = 1_000_000
    assert server._fmt_age(now - 30, now) == "<1m ago"  # sub-minute
    assert server._fmt_age(now - 120, now) == "2m ago"
    assert server._fmt_age(now - 7200, now) == "2h ago"
    assert server._fmt_age(now - 2 * 86400, now) == "2d ago"
    assert server._fmt_age(0, now) == "?"  # unknown onset
    assert server._fmt_age(now + 100, now) == "<1m ago"  # future clamps to 0


def test_window_label():
    assert server._window_label(24 * 3600) == "24h"
    assert server._window_label(90 * 60) == "90m"
    assert server._window_label(30) == "30s"


def test_recent_window_seconds_env(monkeypatch):
    monkeypatch.setenv("ZABBIX_BRIEF_RECENT_HOURS", "48")
    assert server._recent_window_seconds() == 48 * 3600
    monkeypatch.setenv("ZABBIX_BRIEF_RECENT_HOURS", "bad")  # malformed -> default
    assert server._recent_window_seconds() == 24 * 3600
    monkeypatch.delenv("ZABBIX_BRIEF_RECENT_HOURS", raising=False)
    assert server._recent_window_seconds() == 24 * 3600


def test_count_fragment():
    assert server._count_fragment(5, 5) == "5"
    assert server._count_fragment(5, 20) == "showing 5 of 20"


def test_brief_problem_limit_env(monkeypatch):
    monkeypatch.delenv("ZABBIX_BRIEF_PROBLEM_LIMIT", raising=False)
    assert server._brief_problem_limit() == 1000  # default
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "250")
    assert server._brief_problem_limit() == 250
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "10.5")  # decimal truncates, not reverts
    assert server._brief_problem_limit() == 10
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "bad")  # malformed -> default
    assert server._brief_problem_limit() == 1000
    monkeypatch.setenv("ZABBIX_BRIEF_PROBLEM_LIMIT", "0")  # floored at 1
    assert server._brief_problem_limit() == 1


def test_clock_handles_bad_input():
    assert server._clock({"clock": "1700000000"}) == 1700000000
    assert server._clock({}) == 0
    assert server._clock({"clock": "x"}) == 0


def test_fmt_time_handles_bad_input():
    assert server._fmt_time(None) == "—"
    assert server._fmt_time(0) == "—"
    assert server._fmt_time("0") == "—"  # Zabbix sends string "0" for "never"
    assert server._fmt_time("not-a-number") == "—"


def test_severity_name():
    assert server._severity_name("4") == "High"
    assert server._severity_name(99) == "99"
    assert server._severity_name(None) == "None"  # must not crash


def test_client_is_cached_across_calls():
    """The singleton logs in once and is reused across tool calls."""
    r = make_router(results={"problem.get": [], "host.get": []})
    with r:
        _call(server.get_problems)()
        _call(server.get_hosts)()
    logins = [x for x in r.captured if x["payload"]["method"] == "user.login"]
    assert len(logins) == 1
