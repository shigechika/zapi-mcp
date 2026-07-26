"""Probe specs for this server's tools — the Zabbix-specific half of the smoke test.

Every registered tool needs an entry here (the harness fails on a tool with no
spec), so adding a tool forces a decision: how would we know it works?

Three constraints shape everything below.

**Read-only.** These tools drive the production monitoring system. The one tool
that writes — acknowledging a problem — is skipped by name and must stay
skipped: an acknowledgement is visible to every operator and cannot be quietly
undone.

**No site-specific values in this file.** This repository is public, so a probe
may not name a host, host group, tag value or URL from the installation it runs
against. Where a tool needs one, an ``args_factory`` discovers it at run time.

**Bounded.** A probe runs on a schedule, so anything with a size argument gets a
small explicit one rather than the tool's interactive default.

Assertions are shape-first: these tools answer with formatted text whose empty
case is a sentence ("No active problems."), not an error, so a probe pins the
header line it must produce. An empty answer is a real observation here — a
monitoring system with nothing wrong is the goal, not a malfunction — so the
probes accept it and assert the envelope instead.
"""

import re
from typing import Any

from smoke_harness import Caller, Probe, SkipProbe


async def _first_host(call: Caller) -> dict[str, Any]:
    """Discover a monitored host name at run time for the per-host tools."""
    payload = await call("get_hosts", {})
    text = payload if isinstance(payload, str) else str(payload)
    # "Hosts (N):" then one indented "  <name>  <ip>  [tags]" per host — take
    # the first listed name. The header line is not indented, so it cannot be
    # mistaken for an entry.
    match = re.search(r"^ {2}(\S+)", text, re.MULTILINE)
    if not match:
        raise SkipProbe("get_hosts returned no host to probe with")
    return {"host": match.group(1)}


PROBES: dict[str, Probe] = {
    # -- server / backend health ------------------------------------------
    "health_check": Probe(
        require_keys=("status", "service", "auth", "zabbix_api_version"),
        must_match=(r'"auth": "ok"', r'"status": "(healthy|degraded)"'),
        allow_empty=True,
    ),
    # -- problems ----------------------------------------------------------
    # A quiet monitoring system is the desired state, so "no problems" passes;
    # what must hold is that the tool rendered one of its known answers.
    "get_problems": Probe(
        args={"min_severity": 2, "limit": 5},
        must_match=(
            r"^Active Problems \(showing \d+ of \d+\):"
            r"|^Active Problems \(\d+\):"
            r"|^No (active problems|problems at/above)",
        ),
        # The tool renders backend failures as ordinary text rather than raising.
        must_not_match=(r"^(Zabbix error|Missing environment variable)",),
    ),
    # -- inventory ---------------------------------------------------------
    "get_hosts": Probe(
        must_match=(r"^Hosts \(\d+\):|^No hosts found\.",),
        must_not_match=(r"^(Zabbix error|Missing environment variable)",),
    ),
    "get_host_items": Probe(
        args_factory=_first_host,
        args={"search": "icmp"},
        must_match=(r"^Items for \S+ \(\d+\):|^No items found for",),
        # The host came from get_hosts a moment earlier, so "not found" is not
        # an acceptable answer here: it would mean the name the one tool prints
        # is not the name the other looks up.
        must_not_match=(
            r"^(Zabbix error|Missing environment variable)",
            r"^Host '.*' not found\.",
        ),
    ),
    # -- morning patrol ----------------------------------------------------
    # The brief is a document, not a list: assert its frame (title + the one
    # section that is always emitted) rather than any particular finding.
    "daily_brief": Probe(
        must_match=(r"^# Daily Brief — \d{4}-\d{2}-\d{2}", r"^## Active Problems\b"),
        must_not_match=(
            r"^(Zabbix error|Missing environment variable)",
            # Per-section backend failures are rendered inline as "Error: ...",
            # and a category that stopped loading is exactly what this run is
            # meant to notice.
            r"^Error: ",
            r"^\(Categories not loaded:",
        ),
        timeout=300,
    ),
    # -- state-changing tools: never exercised ----------------------------
    "acknowledge_problem": Probe(skip="writes to Zabbix: an acknowledgement is visible to every operator"),
}
