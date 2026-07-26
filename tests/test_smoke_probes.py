"""Every registered tool must carry a smoke-test probe spec.

This is the CI half of the smoke test: the live run (scripts/smoke_test.py)
needs a reachable Zabbix, but the *coverage* question — did someone add a tool
without deciding how we would know it works? — is answerable offline, so it is
enforced here on every push.
"""

import asyncio
import re
import sys
from pathlib import Path

from zapi_mcp.server import mcp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import smoke_probes  # noqa: E402 - needs the sys.path line above
from smoke_harness import Probe  # noqa: E402

#: Literal shapes that would tie this public repository to one installation.
#: Named by shape rather than by value: spelling out the domain in order to
#: forbid it would put that domain here, which is what the check prevents.
#:
#: The IPv6 pattern covers both the fully written form and the compressed one.
#: A compressed match requires a hex group to the left of "::" so that a clock
#: time (12:34:56) and a Python slice (a[::2]) do not read as addresses, and
#: loopback/unspecified forms (::1, ::) are not matched at all — they identify
#: no site.
ADDRESS_SHAPES = {
    "email address": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "URL": r"https?://",
    # {1,} not {2,}: a bare two-label domain (example.com) is the common case
    # and was slipping through when this required a subdomain.
    "hostname": r"\b(?:[a-z0-9-]+\.){1,}(?:jp|com|org|net|edu|ac|co|io|dev)\b",
    "IPv4 address": r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    "IPv6 address": (
        r"(?i)\b[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){7}\b"
        r"|\b[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*::(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?"
    ),
}

#: Tool parameters whose value names something in the monitored estate. A
#: Zabbix host, group or tag value is usually a bare word ("core-switch-01",
#: "Core Routers") with no dot, TLD or address shape in it, so the patterns
#: above cannot see it — hence a second, key-based guard: these arguments must
#: come from an args_factory at run time, never from a literal in the specs.
IDENTIFIER_ARGS = {"host", "group", "tag_name", "tag_value", "role"}

#: Tools that change state. The smoke test must never call these.
STATE_CHANGING = {"acknowledge_problem"}


def _registered_tool_names() -> set[str]:
    """Tool names from the live registry (no Zabbix connection needed).

    ``asyncio.run`` rather than an async test: this suite has no async plugin,
    and the registry read is the only awaitable involved.
    """

    async def _names() -> set[str]:
        return {tool.name for tool in await mcp.list_tools()}

    return asyncio.run(_names())


def test_every_registered_tool_has_a_probe():
    registered = _registered_tool_names()
    missing = sorted(registered - set(smoke_probes.PROBES))
    assert not missing, (
        f"Tool(s) registered with no smoke-test probe: {missing}. "
        "Add an entry to scripts/smoke_probes.py — arguments plus what a working "
        "answer looks like, or an explicit skip= reason."
    )


def test_no_probe_targets_a_removed_tool():
    registered = _registered_tool_names()
    stale = sorted(set(smoke_probes.PROBES) - registered)
    assert not stale, f"Probe spec(s) for tools that are no longer registered: {stale}"


def test_state_changing_tools_are_skipped():
    """A smoke test that acknowledges a live alert is worse than no smoke test."""
    registered = _registered_tool_names()
    for name in sorted(STATE_CHANGING & registered):
        probe = smoke_probes.PROBES[name]
        assert probe.skip, f"{name} changes state and must be skipped, not exercised"


def test_probes_are_probe_instances():
    for name, probe in smoke_probes.PROBES.items():
        assert isinstance(probe, Probe), f"{name} is not a Probe"


def test_tools_with_a_limit_are_probed_with_one():
    """A scheduled probe must not lean on a listing tool's interactive default.

    A tool takes a ``limit`` because its result set can be large; the default
    is sized for a human asking once, not for something that runs unattended
    every day. Any such tool must therefore be probed with an explicit, small
    value — found here from the source so a new one cannot be added without the
    same decision.
    """
    # encoding pinned: the default is the locale's, which is cp1252 on the
    # Windows CI runner and cannot decode this source.
    source = (Path(__file__).resolve().parent.parent / "zapi_mcp" / "server.py").read_text(encoding="utf-8")
    # A signature-shape heuristic, not a general "can this return a lot?"
    # analysis: it finds the tools that declare a limit parameter. A tool that
    # returns an unbounded result without offering a limit would not be caught
    # here, so treat this as a tripwire for the known shape rather than a proof.
    bounded: list[str] = []
    for chunk in source.split("@mcp.tool()")[1:]:
        match = re.search(r"^def ([a-z_0-9]+)\(", chunk, re.MULTILINE)
        if not match:
            continue
        signature = chunk.split(") ->", 1)[0]
        if re.search(r"\blimit\s*:", signature):
            bounded.append(match.group(1))

    assert bounded, "expected at least one tool taking a limit; has the signature changed?"
    for name in bounded:
        probe = smoke_probes.PROBES.get(name)
        assert probe is not None, f"{name} takes a limit and has no probe spec"
        if probe.skip:
            continue
        limit = probe.args.get("limit")
        assert isinstance(limit, int) and 0 < limit <= 50, (
            f"{name} accepts a limit, so its probe must pass a small explicit one "
            f"(got {limit!r}). Proving the tool works needs a sample, not the "
            "whole result set."
        )


def test_every_exercised_probe_asserts_something():
    """A probe that asserts nothing reports a broken tool as OK."""
    offenders = [
        name
        for name, probe in smoke_probes.PROBES.items()
        if not probe.skip
        and not probe.must_match
        and not probe.min_chars
        and not probe.require_keys
        and not probe.min_values
    ]
    assert not offenders, (
        f"probes with nothing to assert: {offenders}. These tools answer with "
        "formatted text, so pin the header line they must produce (must_match) "
        "or at least a minimum length."
    )


def test_address_shapes_catch_what_they_claim_to():
    """The guard below is only as good as these patterns, so pin them.

    IPv6 in particular is easy to get wrong in both directions: miss the
    compressed form, or swallow anything with two colons in it.
    """
    leaks = [
        "user@example.org",
        "https://sso.example.ac.jp",
        "sso.example.ac.jp",
        "example.com",  # a bare two-label domain is the common shape
        "example.io",
        "192.0.2.10",
        "2001:db8::1",
        "fe80::1",
        "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
    ]
    for value in leaks:
        assert any(re.search(p, value) for p in ADDRESS_SHAPES.values()), f"missed: {value}"

    innocuous = [
        "12:34:56",  # a clock time
        "values[::2]",  # a Python slice
        "::1",  # loopback identifies no site
        r"^Hosts \(\d+\):",  # a probe pattern
        "min_severity=2",
    ]
    for value in innocuous:
        matched = [label for label, p in ADDRESS_SHAPES.items() if re.search(p, value)]
        assert not matched, f"false positive on {value!r}: {matched}"


def test_no_site_identifying_arguments_are_hardcoded():
    """Arguments that name part of the estate must be discovered, not written down.

    This is the half of the "no site-specific values" rule that the shape scan
    below cannot do: a host, group or tag value is typically a bare word with
    no address shape to recognise. Rather than trying to tell a real host name
    from an invented one, this refuses the *parameters* outright — they come
    from an args_factory or they do not appear.
    """
    # encoding pinned: the default is the locale's, which is cp1252 on the
    # Windows CI runner and cannot decode this source.
    source = (Path(__file__).resolve().parent.parent / "zapi_mcp" / "server.py").read_text(encoding="utf-8")
    stale = sorted(k for k in IDENTIFIER_ARGS if not re.search(rf"^\s+{k}: ", source, re.MULTILINE))
    assert not stale, (
        f"IDENTIFIER_ARGS names parameters no tool takes any more: {stale}. "
        "A renamed parameter silently empties this guard, so keep the set in "
        "step with the tool signatures."
    )

    offenders = [
        (name, key) for name, probe in smoke_probes.PROBES.items() for key in probe.args if key in IDENTIFIER_ARGS
    ]
    assert not offenders, (
        f"site-identifying arguments hardcoded in smoke_probes.py: {offenders}. "
        "Discover them at run time (args_factory); this repository is public."
    )

    # The check above reads the specs as data, which an args_factory sidesteps:
    # a factory returning {"host": "core-switch-01"} would satisfy it while
    # committing the very literal it exists to prevent. So read the file as
    # text too and refuse one of these keys paired with a string literal
    # anywhere in it — a discovered value is an expression (match.group(1)),
    # never a quote.
    spec_source = (Path(__file__).resolve().parent.parent / "scripts" / "smoke_probes.py").read_text(encoding="utf-8")
    literals = sorted(key for key in IDENTIFIER_ARGS if re.search(rf'["\']{key}["\']\s*:\s*["\']', spec_source))
    assert not literals, (
        f"site-identifying arguments written as literals in smoke_probes.py: {literals}. "
        "Return them from a discovery call instead of writing the value down."
    )


def test_no_site_specific_literals_in_specs():
    """This repository is public: probes must not name the site they run against.

    The complement of the check above: it bans the parameters that carry a name
    from the estate, this one bans anything address-shaped anywhere in the file
    — a URL, a mail address, an IP. The patterns are deliberately generic:
    spelling out the installation's own domain in order to forbid it would put
    that domain in a public repository, which is the very thing this test
    exists to prevent.
    """
    source = (Path(__file__).resolve().parent.parent / "scripts" / "smoke_probes.py").read_text(encoding="utf-8")
    hits = [label for label, pattern in ADDRESS_SHAPES.items() if re.search(pattern, source)]
    assert not hits, (
        f"address-like literals in smoke_probes.py: {hits}. Discover such arguments "
        "at run time (args_factory) rather than hardcoding them."
    )
