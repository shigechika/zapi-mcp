"""Tests for MCP tool output (server.py)."""

import json
import time
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


# ---- set_maintenance -------------------------------------------------------


def _sequenced_maintenance_get_router(captured, *, first_result, second_result, extra_results=None):
    """A handler distinguishing zapi-lib's own idempotency-check maintenance.get
    (call 1) from server.py's post-write verification maintenance.get (call 2) --
    make_router's static per-method table can't do this, and without it, tests
    for the "freshly created, confirmed till" branch silently exercise the
    "(unconfirmed)" fallback instead (both calls would hit the same canned []).
    ``captured`` (a list the caller owns) collects each request's payload,
    mirroring conftest.make_router's own captured-list convention.
    """
    call_count = {"maintenance.get": 0}
    table = dict(extra_results or {})

    def handler(request):
        payload = json.loads(request.content)
        captured.append(payload)
        method = payload["method"]
        if method in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if method == "apiinfo.version" else "tok", "id": 1})
        if method == "maintenance.get":
            call_count["maintenance.get"] += 1
            result = first_result if call_count["maintenance.get"] == 1 else second_result
            return httpx.Response(200, json={"result": result, "id": 1})
        return httpx.Response(200, json={"result": table.get(method, []), "id": 1})

    return handler


def test_set_maintenance_by_location():
    captured = []
    handler = _sequenced_maintenance_get_router(
        captured,
        first_result=[],  # zapi-lib's idempotency check: no existing window
        second_result=[{"maintenanceid": "1", "active_till": "1786435200"}],  # our verification, post-create
        extra_results={"maintenance.create": {"maintenanceids": ["1"]}, "host.get": [{"hostid": "10"}]},
    )
    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT")
    create_call = next(p for p in captured if p["method"] == "maintenance.create")
    assert create_call["params"]["tags"] == [{"tag": "location", "operator": "0", "value": "CIT"}]
    assert "location='CIT'" in out
    assert "maintenance id(s): 1" in out
    assert "(unconfirmed)" not in out  # the confirmed-till branch, not the fallback


def test_set_maintenance_by_hosts():
    captured = []
    handler = _sequenced_maintenance_get_router(
        captured,
        first_result=[],
        second_result=[{"maintenanceid": "2", "active_till": "1786435200"}],
        extra_results={
            "maintenance.create": {"maintenanceids": ["2"]},
            "host.get": [{"hostid": "11", "host": "cit-sw-to16"}, {"hostid": "12", "host": "cit-sw-ke22"}],
        },
    )
    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.set_maintenance)(
            "2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", hosts="cit-sw-to16, cit-sw-ke22"
        )
    create_call = next(p for p in captured if p["method"] == "maintenance.create")
    assert "tags" not in create_call["params"]
    assert sorted(create_call["params"]["hostids"]) == ["11", "12"]
    assert "hosts=cit-sw-to16, cit-sw-ke22" in out
    assert "(unconfirmed)" not in out


def test_set_maintenance_reports_actual_window_till_not_caller_input():
    # Idempotent short-circuit: a window with this name+since already
    # exists. The tool must report the window's REAL active_till (queried
    # fresh via maintenance.get), not blindly echo the caller's till --
    # which, on this branch, may not match what Zabbix actually has.
    real_till_dt = datetime.strptime("2026/08/10 13:00:00", "%Y/%m/%d %H:%M:%S")
    real_till_epoch = int(time.mktime(real_till_dt.timetuple()))
    r = make_router(results={"maintenance.get": [{"maintenanceid": "42", "active_till": str(real_till_epoch)}]})
    with r:
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 18:00:00", "MW-", "desc", location="CIT")
    assert "maintenance id(s): 42" in out
    assert "to 2026/08/10 13:00:00" in out  # the window's real till
    assert "18:00:00" not in out  # not the caller's (stale, on this branch) input


def test_set_maintenance_verification_failure_does_not_report_overall_failure():
    # R4F1: the write itself (idempotency lookup finding an existing window,
    # in this case) already succeeded -- a transient failure in the
    # follow-up best-effort verification read must not be reported as an
    # overall "Zabbix error" when the maintenance window is, in fact, active.
    call_count = {"maintenance.get": 0}

    def handler(request):
        payload = json.loads(request.content)
        method = payload["method"]
        if method in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if method == "apiinfo.version" else "tok", "id": 1})
        if method == "maintenance.get":
            call_count["maintenance.get"] += 1
            if call_count["maintenance.get"] == 1:
                return httpx.Response(200, json={"result": [{"maintenanceid": "42"}], "id": 1})  # zapi-lib's own check
            return httpx.Response(200, json={"error": {"message": "temporary glitch"}, "id": 1})  # our verification
        return httpx.Response(200, json={"result": [], "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT")
    assert "Zabbix error" not in out
    assert "maintenance id(s): 42" in out
    assert "(unconfirmed)" in out


def test_set_maintenance_verification_resets_client_on_zapi_error():
    # R5F2: unlike the write's own ZapiError handler (which may fire on pure
    # local validation with no network touched), the verification read is
    # always a real API call -- a failure there should reset the cached
    # client so the *next* tool call re-authenticates instead of reusing a
    # possibly-dead session.
    call_count = {"maintenance.get": 0}

    def handler(request):
        payload = json.loads(request.content)
        method = payload["method"]
        if method in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if method == "apiinfo.version" else "tok", "id": 1})
        if method == "maintenance.get":
            call_count["maintenance.get"] += 1
            if call_count["maintenance.get"] == 1:
                return httpx.Response(200, json={"result": [{"maintenanceid": "42"}], "id": 1})
            return httpx.Response(200, json={"error": {"message": "session expired"}, "id": 1})
        return httpx.Response(200, json={"result": [], "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT")
    assert "Zabbix error" not in out
    assert "(unconfirmed)" in out
    assert server._CLIENT is None  # reset so the next call re-authenticates


def test_set_maintenance_verification_malformed_till_does_not_raise():
    # R5F1: a non-numeric active_till in the verification response must not
    # let int() raise past the best-effort handler -- the write already
    # succeeded, so this must degrade to unconfirmed, not crash.
    r = make_router(results={"maintenance.get": [{"maintenanceid": "42", "active_till": "not-a-number"}]})
    with r:
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT")
    assert "Zabbix error" not in out
    assert "maintenance id(s): 42" in out
    assert "(unconfirmed)" in out


def test_set_maintenance_verification_out_of_range_till_does_not_raise():
    # A numeric-but-out-of-range active_till (e.g. corrupted response) makes
    # int() succeed but datetime.fromtimestamp() raise (ValueError/OSError/
    # OverflowError, platform-dependent) -- the broad `except Exception`
    # around this best-effort step must catch all of them, not just the
    # non-numeric-string case above.
    r = make_router(results={"maintenance.get": [{"maintenanceid": "42", "active_till": "99999999999999"}]})
    with r:
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT")
    assert "Zabbix error" not in out
    assert "maintenance id(s): 42" in out
    assert "(unconfirmed)" in out


def test_set_maintenance_rejects_comma_only_hosts():
    # hosts="," survives the whitespace-strip (non-empty after strip()) but
    # reduces to zero real names once split -- must be rejected here, not
    # left to reach zapi-lib's local ZapiError and get mislabeled "Zabbix
    # error:" even though it never touched Zabbix.
    with make_router():
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", hosts=",,,")
    assert "at least one non-empty host name" in out
    assert "Zabbix error" not in out


def test_set_maintenance_rejects_neither_location_nor_hosts():
    with make_router():
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc")
    assert "Specify exactly one" in out


def test_set_maintenance_rejects_whitespace_only_location():
    # bool("   ") is True, so without stripping first this would sail past
    # the "exactly one" check and reach Zabbix with a nonsense tag value.
    with make_router():
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="   ")
    assert "Specify exactly one" in out


def test_set_maintenance_rejects_whitespace_only_hosts():
    with make_router():
        out = _call(server.set_maintenance)("2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", hosts="   ")
    assert "Specify exactly one" in out


def test_set_maintenance_rejects_both_location_and_hosts():
    with make_router():
        out = _call(server.set_maintenance)(
            "2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", location="CIT", hosts="cit-sw-to16"
        )
    assert "Specify exactly one" in out


def test_set_maintenance_reports_unresolved_host_as_zabbix_error():
    r = make_router(results={"maintenance.get": [], "host.get": []})
    with r:
        out = _call(server.set_maintenance)(
            "2026/08/10 11:00:00", "2026/08/10 13:00:00", "MW-", "desc", hosts="cit-sw-typo"
        )
    assert out.startswith("Zabbix error:")
    assert "cit-sw-typo" in out


# ---- _window_state (pure logic) --------------------------------------------


def test_window_state_active_one_time():
    now = 1_000_000
    w = {
        "active_since": str(now - 100),
        "active_till": str(now + 100),
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now - 100), "period": "200"}],
    }
    assert server._window_state(w, now) == ("active", False)


def test_window_state_upcoming_outer_frame():
    now = 1_000_000
    w = {"active_since": str(now + 100), "active_till": str(now + 200), "timeperiods": []}
    assert server._window_state(w, now) == ("upcoming", False)


def test_window_state_expired_outer_frame():
    now = 1_000_000
    w = {"active_since": str(now - 200), "active_till": str(now - 100), "timeperiods": []}
    assert server._window_state(w, now) == ("expired", False)


def test_window_state_malformed_till_with_valid_since_is_not_silently_expired():
    # A corrupted/unparseable active_till on an otherwise-real, ongoing
    # window must not make it vanish from the default (non-expired) view --
    # that would defeat the point of surfacing maintenance context at all
    # (regression found by /code-review on PR#63).
    now = 1_000_000
    w = {"active_since": str(now - 200), "active_till": "not-a-number", "timeperiods": []}
    assert server._window_state(w, now) == ("active", False)


def test_window_state_one_time_not_yet_started_within_outer_frame():
    # The outer frame (active_since/active_till) is already open, but the
    # window's own one-time period hasn't started -- must not report active.
    now = 1_000_000
    w = {
        "active_since": str(now - 100),
        "active_till": str(now + 1000),
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now + 500), "period": "100"}],
    }
    assert server._window_state(w, now) == ("upcoming", False)


def test_window_state_one_time_already_ended_within_outer_frame():
    now = 1_000_000
    w = {
        "active_since": str(now - 1000),
        "active_till": str(now + 100),
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now - 1000), "period": "500"}],
    }
    assert server._window_state(w, now) == ("expired", False)


def test_window_state_recurring_period_uses_outer_frame():
    now = 1_000_000
    w = {
        "active_since": str(now - 100),
        "active_till": str(now + 100),
        "timeperiods": [{"timeperiod_type": "2", "start_time": "0", "period": "3600"}],
    }
    assert server._window_state(w, now) == ("active", True)


def test_window_state_gap_between_two_one_time_periods_is_upcoming_not_expired():
    # One period already ended, a second hasn't started yet, "now" sits in
    # the gap between them -- must report the still-upcoming period, not
    # "expired" just because an earlier period is done (regression for
    # ai-review R1F1 on PR#63).
    now = 1_000_000
    w = {
        "active_since": str(now - 10_000),
        "active_till": str(now + 10_000),
        "timeperiods": [
            {"timeperiod_type": "0", "start_date": str(now - 2000), "period": "500"},  # already ended
            {"timeperiod_type": "0", "start_date": str(now + 2000), "period": "500"},  # still to come
        ],
    }
    assert server._window_state(w, now) == ("upcoming", False)


def test_window_state_all_one_time_periods_ended_is_expired():
    now = 1_000_000
    w = {
        "active_since": str(now - 10_000),
        "active_till": str(now + 10_000),
        "timeperiods": [
            {"timeperiod_type": "0", "start_date": str(now - 3000), "period": "500"},
            {"timeperiod_type": "0", "start_date": str(now - 2000), "period": "500"},
        ],
    }
    assert server._window_state(w, now) == ("expired", False)


# ---- _window_upcoming_start (pure logic) -----------------------------------


def test_window_upcoming_start_before_outer_frame_opens():
    now = 1_000_000
    w = {"active_since": str(now + 500), "active_till": str(now + 1500), "timeperiods": []}
    assert server._window_upcoming_start(w, now) == now + 500


def test_window_upcoming_start_before_outer_frame_opens_but_period_starts_later():
    # The outer frame opens later today, but the window's actual one-time
    # period doesn't start until 9 days after that -- the effective start
    # must be the period's own start, not active_since (regression: the
    # earlier fix only handled "frame already open, period not yet started";
    # this is the "frame not open yet either" half of the same bug, found by
    # /code-review on PR#63 after the R1F2 ledger entry stayed open).
    now = 1_000_000
    since = now + 500
    period_start = since + 9 * 86_400
    w = {
        "active_since": str(since),
        "active_till": str(period_start + 100_000),
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(period_start), "period": "600"}],
    }
    assert server._window_upcoming_start(w, now) == period_start


def test_window_upcoming_start_uses_period_start_not_active_since():
    # Outer frame already opened (active_since is in the past), but the
    # window's own one-time period doesn't start until later -- the "starts
    # today" check must use that later moment, not active_since (regression
    # for ai-review R1F2 on PR#63).
    now = 1_000_000
    w = {
        "active_since": str(now - 100_000),
        "active_till": str(now + 100_000),
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now + 3600), "period": "600"}],
    }
    assert server._window_upcoming_start(w, now) == now + 3600


def test_window_upcoming_start_picks_earliest_future_period():
    now = 1_000_000
    w = {
        "active_since": str(now - 100_000),
        "active_till": str(now + 100_000),
        "timeperiods": [
            {"timeperiod_type": "0", "start_date": str(now + 7200), "period": "600"},
            {"timeperiod_type": "0", "start_date": str(now + 3600), "period": "600"},
        ],
    }
    assert server._window_upcoming_start(w, now) == now + 3600


def test_epoch_to_local_date_handles_out_of_range():
    # A timestamp large enough to overflow datetime.fromtimestamp() must
    # degrade to None, not raise (regression for ai-review R2F1 on PR#63).
    assert server._epoch_to_local_date(99999999999999) is None


# ---- _window_hosts / _fmt_window_hosts (pure formatting) -------------------


def test_window_hosts_reads_groups_or_hostgroups_key():
    # get_maintenances() returns "groups" pre-6.4 and "hostgroups" >=6.4 for
    # the selected host-group data -- a group-only window must not read blank
    # just because the caller's Zabbix generation used the other key.
    pre_64 = {"hosts": [], "groups": [{"groupid": "1", "name": "Group A"}]}
    assert server._window_hosts(pre_64) == ([], ["Group A"])
    post_64 = {"hosts": [], "hostgroups": [{"groupid": "1", "name": "Group A"}]}
    assert server._window_hosts(post_64) == ([], ["Group A"])


def test_window_hosts_separates_hosts_from_groups():
    m = {
        "hosts": [{"hostid": "1", "host": "host-a"}],
        "hostgroups": [{"groupid": "1", "name": "Routers"}],
    }
    assert server._window_hosts(m) == (["host-a"], ["Routers"])


def test_fmt_window_hosts_truncates_and_pluralizes():
    assert server._fmt_window_hosts([], [], 8) == "no hosts"
    assert server._fmt_window_hosts(["a"], [], 8) == "1 host: a"
    names = [f"h{i}" for i in range(10)]
    assert server._fmt_window_hosts(names, [], 8) == "10 hosts: h0, h1, h2, h3, h4, h5, h6, h7, … and 2 more"


def test_fmt_window_hosts_reports_groups_separately_not_as_a_host():
    # A host-group-only window must not be reported as "1 host: group:X" --
    # the group's member count isn't known here, so it's a group, not a host
    # (regression for ai-review R1F3 on PR#63).
    assert server._fmt_window_hosts([], ["Routers"], 8) == "1 group: Routers"
    assert server._fmt_window_hosts(["host-a"], ["Routers"], 8) == "1 host: host-a; 1 group: Routers"


# ---- get_maintenance_windows ------------------------------------------------


def _one_time_window(*, maintenanceid, name, since_offset, till_offset, hosts=None, maintenance_type="0"):
    """A maintenance.get row with one one-time period matching its outer frame
    exactly -- the shape set_maintenance/set_maintenance_for_hosts always create."""
    now = _frozen_now_ts()
    since, till = now + since_offset, now + till_offset
    return {
        "maintenanceid": maintenanceid,
        "name": name,
        "active_since": str(since),
        "active_till": str(till),
        "maintenance_type": maintenance_type,
        "description": "planned outage",
        "hosts": hosts if hosts is not None else [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(since), "period": str(till - since)}],
        "tags": [],
    }


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_shows_active_window():
    w = _one_time_window(maintenanceid="1", name="MW-1", since_offset=-3600, till_offset=3600)
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "Maintenance Windows (1 active, 0 upcoming):" in out
    assert "## Active" in out
    assert "MW-1" in out
    assert "1 host: host-a" in out
    assert "planned outage" in out


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_shows_upcoming_window():
    w = _one_time_window(maintenanceid="2", name="MW-2", since_offset=3600, till_offset=7200)
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "Maintenance Windows (0 active, 1 upcoming):" in out
    assert "## Upcoming" in out
    assert "## Active" not in out


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_excludes_expired_by_default():
    w = _one_time_window(maintenanceid="3", name="MW-3", since_offset=-7200, till_offset=-3600)
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert out == "No maintenance windows."


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_include_expired_shows_expired():
    w = _one_time_window(maintenanceid="3", name="MW-3", since_offset=-7200, till_offset=-3600)
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)(include_expired=True)
    assert "## Expired (1)" in out
    assert "MW-3" in out


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_recurring_window_labeled():
    now = _frozen_now_ts()
    w = {
        "maintenanceid": "5",
        "name": "MW-5",
        "active_since": str(now - 3600),
        "active_till": str(now + 3600 * 24 * 30),
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "2", "start_time": "0", "period": "3600"}],
        "tags": [],
    }
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "Maintenance Windows (1 active, 0 upcoming):" in out
    assert "(recurring)" in out


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_truncates_long_host_list():
    hosts = [{"hostid": str(i), "host": f"host-{i}", "name": f"Host {i}"} for i in range(10)]
    w = _one_time_window(maintenanceid="6", name="MW-6", since_offset=-60, till_offset=3600, hosts=hosts)
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "… and 2 more" in out


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_no_data_collection_label():
    w = _one_time_window(maintenanceid="7", name="MW-7", since_offset=-60, till_offset=3600, maintenance_type="1")
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "[no data collection]" in out


def test_get_maintenance_windows_empty():
    with make_router(results={"maintenance.get": []}):
        out = _call(server.get_maintenance_windows)()
    assert out == "No maintenance windows."


def test_get_maintenance_windows_zabbix_error_resets_client():
    def handler(request):
        payload = json.loads(request.content)
        m = payload["method"]
        if m in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if m == "apiinfo.version" else "tok", "id": 1})
        return httpx.Response(200, json={"error": {"message": "boom"}, "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        out = _call(server.get_maintenance_windows)()
    assert "Zabbix error" in out
    assert server._CLIENT is None


def test_get_maintenance_windows_calls_maintenance_get_once():
    w = _one_time_window(maintenanceid="1", name="MW-1", since_offset=-60, till_offset=60)
    r = make_router(results={"maintenance.get": [w]})
    with r:
        _call(server.get_maintenance_windows)()
    calls = [x for x in r.captured if x["payload"]["method"] == "maintenance.get"]
    assert len(calls) == 1


@freeze_time(FROZEN_NOW)
def test_get_maintenance_windows_period_gap_shows_as_upcoming():
    # End-to-end check for the R1F1 fix: a window between two one-time
    # periods must appear under Upcoming, not be silently dropped as expired.
    now = _frozen_now_ts()
    w = {
        "maintenanceid": "8",
        "name": "MW-8",
        "active_since": str(now - 10_000),
        "active_till": str(now + 10_000),
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [
            {"timeperiod_type": "0", "start_date": str(now - 2000), "period": "500"},
            {"timeperiod_type": "0", "start_date": str(now + 2000), "period": "500"},
        ],
        "tags": [],
    }
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "Maintenance Windows (0 active, 1 upcoming):" in out
    assert "## Upcoming" in out
    assert "MW-8" in out


def test_get_maintenance_windows_host_group_reported_as_group_not_host():
    w = _one_time_window(
        maintenanceid="9",
        name="MW-9",
        since_offset=-60,
        till_offset=60,
        hosts=[],
    )
    w["hostgroups"] = [{"groupid": "1", "name": "Routers"}]
    with make_router(results={"maintenance.get": [w]}):
        out = _call(server.get_maintenance_windows)()
    assert "1 group: Routers" in out
    assert "1 host:" not in out


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


def test_daily_brief_bad_categories_reports_error_and_flags(monkeypatch, tmp_path):
    """A malformed categories INI degrades the brief instead of crashing, and
    signals the failure via the (text, had_error) tuple the --brief CLI uses
    for its exit code."""
    p = tmp_path / "bad.ini"
    p.write_text("this is not a valid ini\nno section header here\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    with make_router(results={"problem.get": []}):
        text, had_error = server._daily_brief_text()
    assert had_error is True
    assert "Categories not loaded" in text


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
        name="Node 0 Usage",
        key_="pool.node0.usage",
        lastvalue="92.345",
    )
    r = make_router(results={"problem.get": [], "host.get": [SAMPLE_HOST], "item.get": [item]})
    with r:
        out = _call(server.daily_brief)()
    # value rounded to 1 decimal, item name shown (label != bare key), flagged
    assert "92.3" in out
    assert "92.345" not in out
    assert "Node 0 Usage" in out
    assert "⚠️" in out
    # client must have searched the key, not filtered exactly
    call = next(x["payload"] for x in r.captured if x["payload"]["method"] == "item.get")
    assert call["params"]["search"] == {"key_": ".usage"}


def test_daily_brief_below_threshold_flags_low_values(monkeypatch, tmp_path):
    """direction=below flags values <= threshold (e.g. speed dropping) and
    surfaces the lowest first (speedtest-style)."""
    p = tmp_path / "cats.ini"
    p.write_text(
        "[speedtest]\nname = Speedtest\ntag = speedtest-z\n"
        "item_key_search = download\nthreshold = 100\ndirection = below\n"
    )
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    slow = dict(SAMPLE_ITEM, name="cloudflare.download", key_="cloudflare.download", lastvalue="42.0")
    fast = dict(SAMPLE_ITEM, name="ookla.download", key_="ookla.download", lastvalue="950.0")
    r = make_router(results={"problem.get": [], "host.get": [SAMPLE_HOST], "item.get": [fast, slow]})
    with r:
        out = _call(server.daily_brief)()
    assert "Speedtest" in out
    # Located by item name, not by value: the brief opens with a timestamped
    # header, so "42" matches "13:42" on any run started in the 42nd minute of
    # an hour and the header is then asserted on instead of the item row.
    slow_line = next(ln for ln in out.splitlines() if "cloudflare.download" in ln)
    fast_line = next(ln for ln in out.splitlines() if "ookla.download" in ln)
    assert "42" in slow_line
    assert "950" in fast_line
    assert "⚠️" in slow_line  # 42 <= threshold 100 -> flagged
    assert "⚠️" not in fast_line  # 950 > 100 -> not flagged
    # below surfaces the lowest first
    assert out.index("cloudflare.download") < out.index("ookla.download")


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


# ---- daily_brief: In Maintenance -------------------------------------------


@freeze_time(FROZEN_NOW)
def test_daily_brief_shows_active_maintenance_section(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    w = _one_time_window(maintenanceid="1", name="MW-1", since_offset=-3600, till_offset=3600)
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance (1 window)" in out
    assert "MW-1" in out
    # Section sits between Active Problems and the category area, not before/after both.
    assert out.index("## Active Problems") < out.index("## In Maintenance") < out.index("No categories configured")


@freeze_time(FROZEN_NOW)
def test_daily_brief_marks_recurring_window_in_maintenance_line():
    # get_maintenance_windows shows "(recurring)" for a non-one-time period;
    # the brief's In-Maintenance line must show the same caveat, not present
    # an unqualified line that reads as an exact, precisely-evaluated window
    # (regression found by /code-review on PR#63).
    now = _frozen_now_ts()
    w = {
        "maintenanceid": "20",
        "name": "MW-20",
        "active_since": str(now - 3600),
        "active_till": str(now + 3600 * 24 * 30),
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "2", "start_time": "0", "period": "3600"}],
        "tags": [],
    }
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance (1 window)" in out
    assert "MW-20 (recurring)" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_omits_maintenance_section_for_future_day_upcoming(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    # Starts tomorrow (frozen "now" is 2026-06-01 12:00), not today.
    w = _one_time_window(maintenanceid="2", name="MW-2", since_offset=3600 * 30, till_offset=3600 * 32)
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance" not in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_shows_todays_upcoming_maintenance(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    # Starts later today (frozen "now" is 12:00; +3h keeps the same calendar day).
    w = _one_time_window(maintenanceid="3", name="MW-3", since_offset=3 * 3600, till_offset=5 * 3600)
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance (1 window)" in out
    assert "Starting today: MW-3" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_uses_period_start_not_outer_frame_for_todays_check(monkeypatch):
    # The outer frame opened yesterday, but the window's own one-time period
    # doesn't start until later today -- the brief must key off that actual
    # start (regression for ai-review R1F2 on PR#63; a naive active_since
    # check would both miss this case and, in the mirror scenario, wrongly
    # label a window "starting today" when only its outer frame does).
    now = _frozen_now_ts()
    w = {
        "maintenanceid": "10",
        "name": "MW-10",
        "active_since": str(now - 86_400),  # opened yesterday
        "active_till": str(now + 86_400),
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now + 3600), "period": "600"}],
        "tags": [],
    }
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance (1 window)" in out
    assert "Starting today: MW-10" in out


@freeze_time(FROZEN_NOW)
def test_daily_brief_does_not_label_tomorrows_period_as_starting_today(monkeypatch):
    # Mirror of the case above: the outer frame opens today, but the window's
    # own one-time period doesn't start until tomorrow -- must NOT be shown
    # (a naive active_since check would falsely label this "starting today").
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    now = _frozen_now_ts()
    w = {
        "maintenanceid": "11",
        "name": "MW-11",
        "active_since": str(now - 3600),  # outer frame opened today
        "active_till": str(now + 100_000),
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "0", "start_date": str(now + 30 * 3600), "period": "600"}],  # tomorrow
        "tags": [],
    }
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance" not in out


def test_daily_brief_survives_out_of_range_period_start(monkeypatch):
    # An absurd/corrupted start_date must degrade this one window's "starts
    # today" check, not crash datetime.fromtimestamp() and take down the
    # entire brief (regression for ai-review R2F1 on PR#63).
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    w = {
        "maintenanceid": "12",
        "name": "MW-12",
        "active_since": "1000",
        "active_till": "99999999999999",
        "maintenance_type": "0",
        "description": "",
        "hosts": [{"hostid": "1", "host": "host-a", "name": "Host A"}],
        "timeperiods": [{"timeperiod_type": "0", "start_date": "99999999999999", "period": "600"}],
        "tags": [],
    }
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()  # must not raise
    assert "# Daily Brief" in out
    assert "## In Maintenance" not in out  # malformed window can't be confirmed as "today"


@freeze_time(FROZEN_NOW)
def test_daily_brief_omits_maintenance_section_when_none_active_or_upcoming_today(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    w = _one_time_window(maintenanceid="4", name="MW-4", since_offset=-7200, till_offset=-3600)  # expired
    with make_router(results={"problem.get": [], "maintenance.get": [w]}):
        out = _call(server.daily_brief)()
    assert "## In Maintenance" not in out


def test_daily_brief_survives_maintenance_fetch_failure(monkeypatch):
    """A maintenance.get failure must not abort the rest of the brief."""
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)

    def handler(request):
        payload = json.loads(request.content)
        m = payload["method"]
        if m in ("apiinfo.version", "user.login"):
            return httpx.Response(200, json={"result": "6.0.0" if m == "apiinfo.version" else "tok", "id": 1})
        if m == "maintenance.get":
            return httpx.Response(200, json={"error": {"message": "boom"}, "id": 1})
        return httpx.Response(200, json={"result": [], "id": 1})

    with respx.mock(assert_all_called=False) as router:
        router.post(ENDPOINT).mock(side_effect=handler)
        text, had_error = server._daily_brief_text()
    assert "## In Maintenance\nError: maintenance.get failed:" in text
    assert "boom" in text
    assert "No categories configured" in text  # brief continues past the failure
    assert had_error is True
    # A stale/poisoned session must not be reused by the category loop that
    # follows (regression: the original handler forgot reset_client() here,
    # unlike every other except-ZapiError branch in this module).
    assert server._CLIENT is None


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


def test_fmt_time_handles_out_of_range_epoch():
    # datetime.fromtimestamp() raises ValueError (not just OverflowError/
    # OSError) for a timestamp whose year is outside 1..9999 -- get_maintenances()
    # can surface one of these from a malformed maintenance window (ai-review
    # R2F1 on PR#63 found this same gap in the sibling _epoch_to_local_date).
    assert server._fmt_time("99999999999999") == "99999999999999"


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
