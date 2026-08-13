# Review rules for this repository

Review rules on top of the reviewer's default focus. Three things:
which findings are blocking here, which classes to report that the
default focus would otherwise skip, and which are noise. The reasoning
behind the rules lives in `.github/copilot-instructions.md` (its
numbered focus items are cited below) and `CLAUDE.md`, which the
reviewer also receives.

## Always blocking

- **A credential or session token reaching a tool response, an error
  string or a log line (§4).** `ZABBIX_USER`, `ZABBIX_PASSWORD`, or a
  Zabbix auth token / session id. `ZABBIX_URL` is **not** a secret
  here — `health_check` returns it deliberately as the documented,
  always-present `zabbix_url` key — so this rule is about the
  credentials and tokens only.
- **A hand-edited version string outside a release PR (§6), or a new
  file embedding the version without being added to
  `release-please-config.json`'s `extra-files`.** The version lives in
  four places kept in lockstep, and `release.yml`'s `verify` job
  hard-fails on disagreement before the publish chain runs — but it
  only checks the files it knows about, so an unregistered one drifts
  silently.

## Report even though the default focus would not

- **A new `@mcp.tool()`'s name and docstring (§4).** The calling model
  decides whether and how to invoke a tool by reading them, so a vague
  name, or a docstring omitting a parameter format it would otherwise
  guess — `get_problems`' `min_severity` scale, `acknowledge_problem`'s
  comma-separated `event_ids` — is a functional defect here. Report it
  even though docstring accuracy is normally out of scope when
  reviewing code.
- **A tool that lets `ZapiError` or `KeyError` escape uncaught, or that
  catches `ZapiError` without calling `reset_client()` (§3)**, as
  advisory. Every existing tool converts both to a plain string or dict
  result, and resets the client so the next call re-authenticates
  rather than reusing a broken session. Not automatically wrong with a
  stated reason — the one existing exception is the per-category loop
  in `_daily_brief_text`, which reports a category's error inline
  without resetting, since one category failing does not invalidate the
  session serving the others.
- **A change to `tests/conftest.py`'s `make_router()` that diverges
  from real Zabbix semantics (§5)**, as advisory. That mock is not a
  dumb stub: it emulates `severities` filtering, `countOutput`
  returning the match count as a numeric string, and `limit` truncation
  after an eventid-DESC sort. `_fetch_problems_with_total`'s "showing N
  of TOTAL" logic is only meaningfully tested because of that fidelity,
  so a mock that drifts would let wrong count or limit logic pass
  silently.
- **A delimited free-text tool input parsed without the existing
  defensive shape (§4)**, as advisory. `acknowledge_problem`'s
  `event_ids` (split on `,`, strip, drop empties) is the pattern;
  passing such a value straight to the API call is the finding.

## Never report

- The SIGINT handling in `__main__.py` (§7): `mcp.run()` wrapped in
  `except (KeyboardInterrupt, asyncio.CancelledError)` calling
  `os._exit(0)`. What escapes `mcp.run()` on ^C is Python-version
  dependent, and `os._exit(0)` suppresses anyio's teardown traceback.
  Narrowing the catch or swapping in `sys.exit` would break 3.10 or
  bring the traceback back;
  `tests/test_main.py::test_sigint_exits_cleanly` guards it.
- Version updates to `__init__.py`, `server.json` or
  `.release-please-manifest.json` **inside a release PR**. Those are
  release-please's own, and the hand-edit rule above covers the case
  that actually matters.
- Anything about `zapi-lib`. The Zabbix HTTP client, auth and
  pagination live in their own repository and are reviewed there.
- Suggestions to hand-build an MCP content envelope
  (`{"content": [...], "isError": ...}`) inside a tool handler. FastMCP
  wraps returned values already.
- Anything CI already fails on, restated as a review comment. `ruff
  check .` and `ruff format --check .` both gate this repository, and
  `tests/test_smoke_probes.py` already fails the build for a registered
  tool with no probe spec. This does **not** extend to that file's
  site-specific-literal assertion — an address, host or tag value
  leaking into a public repository is worth catching twice.
- Suggestions to *replace* `release-please.yml`'s
  `secrets.RELEASE_PLEASE_TOKEN` with `GITHUB_TOKEN`. Preferring the
  dedicated token is deliberate, because a `GITHUB_TOKEN`-authored
  release does not trigger the downstream `release` workflow. (The line
  falls back to `GITHUB_TOKEN` when the secret is unset, so a finding
  about the fallback arm itself is still fair game.)
