# Repository overview

`zapi-mcp` is an MCP (Model Context Protocol) server exposing the Zabbix API
(active problems, hosts, item values, a `daily_brief` morning-patrol
summary) to AI assistants over **stdio transport**. Built on the official
`mcp` Python SDK's `FastMCP` (`zapi_mcp/server.py`). The actual Zabbix HTTP
client (`ZapiClient`, auth, pagination) lives in the separate `zapi-lib`
package; `zapi_mcp/client.py` is only a backward-compatible re-export shim.

See `CLAUDE.md` for the authoritative command list and architecture notes —
read it before reviewing changes to `server.py` or `categories.py`.

# Build & validate

```bash
uv sync --dev
uv run pytest -v                    # all tests
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
```

This mirrors `.github/workflows/ci.yml`: a `lint` job (`ruff check` +
`ruff format --check`) and a separate `test` job (`pytest -v`) on Python
3.10/3.12/3.13 on Linux, plus one Windows 3.12 job specifically to catch
stdio newline regressions (`modelcontextprotocol/python-sdk#2433`). Both
lint and test are real CI gates here — unlike some sibling MCP repos in this
family, don't assume lint is unenforced.

# What to focus review on in this repo

## 1. This is a stdio MCP server — stdout is a JSON-RPC channel, not a log

Any `print()` or library logging that writes to stdout (instead of stderr)
corrupts the protocol stream for the connected client. As of now this
codebase has no `logging` usage at all, and every `print()` call in
`__main__.py` sits in a branch that calls `sys.exit()` *before* `mcp.run()`
is reached — the `--version` branch, the missing-env-var check,
and the `--check` / `--brief` branches — so none of them ever run
concurrently with the live stdio server. Flag any new code path that adds a
`print()`, or a logger without an explicit stderr handler, that could
execute while `mcp.run()` is active — that would be a new failure mode, not a
fix to an existing one.

## 2. FastMCP already wraps tool returns — don't ask for manual envelope code

`server.py`'s `@mcp.tool()`-decorated functions return plain `str`/`dict`
values (e.g. `daily_brief` returns `str`, `health_check` returns `dict`);
FastMCP handles the MCP content-envelope wrapping itself. Do **not** suggest
a tool handler manually construct `{"content": [...], "isError": ...}` —
that pattern is relevant to hand-rolled stdio servers elsewhere in this
repo's family, not here.

## 3. Error-handling convention: catch `KeyError`/`ZapiError`, don't raise

Every existing tool (`get_problems`, `get_hosts`, `get_host_items`,
`acknowledge_problem`, `health_check`, and `daily_brief` via
`_daily_brief_text`) catches `KeyError` (missing `ZABBIX_*` env var) and
`ZapiError` (Zabbix API/auth failure) and converts them to a plain
string/dict result (e.g. `"Zabbix error: {e}"`) rather than letting them
propagate. Most of these `ZapiError` catches also call `reset_client()` so
the next call re-authenticates instead of reusing a broken session — the one
existing exception is the per-category loop inside `_daily_brief_text`,
which reports the category's error inline but does not reset the client (a
single category's failure doesn't invalidate the shared session serving the
other categories/the problems section). A new tool that lets `ZapiError` or
`KeyError` escape uncaught, or that catches `ZapiError` without calling
`reset_client()`, is deviating from the dominant pattern — worth a comment,
though not automatically wrong if there's a stated reason.

## 4. Secrets and adversarial tool inputs

- `ZABBIX_USER` / `ZABBIX_PASSWORD` are read from the environment
  (`__main__.py`, `server.py`'s `_client()`). Flag any diff that logs or
  returns either, or a Zabbix auth token/session id, in a tool response or
  error string. `ZABBIX_URL` is read from the same place but is **not** a
  secret here: `health_check` deliberately returns it as the documented,
  always-present `zabbix_url` key, so don't flag that existing behavior —
  flag only a diff that newly exposes the *credentials* or a token/session
  id.
- Tool inputs (`event_ids`, `host`, `tag_name`/`tag_value`, `search`) come
  from an LLM acting on a user's behalf — treat them as adversarial.
  `acknowledge_problem`'s `event_ids` parsing (split on `,`, strip, drop
  empties) is the main free-text input; check any new tool with a
  similar comma/delimited string parameter handles empty/malformed input
  the same defensive way rather than passing it straight to the API call.
- A new `@mcp.tool()`'s name and docstring are what the calling model uses
  to decide whether/how to invoke it — flag a vague name or a docstring
  that omits a parameter format the LLM would otherwise have to guess
  (e.g. `get_problems`' `min_severity` scale, `acknowledge_problem`'s
  comma-separated `event_ids`).

## 5. Test conventions

- All HTTP-level mocking goes through `respx` via `tests/conftest.py`'s
  `make_router()`, which dispatches Zabbix's single JSON-RPC endpoint by the
  request's `method` field. It is **not** a dumb stub: it emulates the
  server-side semantics the count/cap logic depends on — `severities`
  filtering, `countOutput` returning the match count as a numeric string, and
  `limit` truncation after an eventid-DESC sort. `_fetch_problems_with_total`'s
  "showing N of TOTAL" logic is only meaningfully tested because the mock
  mirrors real `problem.get`/`event.get` behavior, so a change to the mock
  that diverges from real Zabbix would let wrong count/limit logic pass
  silently — review mock edits with that fidelity in mind. There is no
  `unittest.mock` usage anywhere in this suite — a new test that hand-mocks
  `httpx`/`ZapiClient` instead of using `make_router` is inconsistent with the
  existing suite.
- `tests/test_server.py` calls tools through a `_call()` helper
  (`getattr(tool, "fn", tool)`) rather than calling `server.get_problems(...)`
  etc. directly, so tests keep working regardless of whether the installed
  `mcp` version's `@mcp.tool()` returns the plain function or a wrapper
  object exposing it via `.fn` (currently the former in this repo's pinned
  version, but that's exactly what the helper is guarding against changing).
  A new test that calls a tool function directly instead of through
  `_call()` isn't broken today, but is inconsistent with the suite's
  convention — prefer `_call()` for consistency and version resilience.
- `tests/test_stdio_smoke.py` asserts every registered tool has a
  non-empty `description` and that the known tool names are present. A new
  `@mcp.tool()` without a docstring will fail that smoke test, not just
  lose review credit.
- Time-dependent tests (age formatting, recent/stale bucketing) use
  `freezegun`'s `@freeze_time` rather than real sleeps or a tolerance
  window — follow that pattern for anything depending on "now".

## 6. Version bumps belong to release-please — the version lands in 4 places

The version string is owned by release-please, not hand-edited. It lives in
four spots kept in lockstep: `zapi_mcp/__init__.py`'s `__version__` (marked
`# x-release-please-version`), `server.json`'s `$.version` and
`$.packages[0].version`, and `.release-please-manifest.json` — the three
files are wired into `release-please-config.json`'s `extra-files` so one
release PR bumps them together. On the release PR's tag, `release.yml`'s
`verify` job hard-fails if `__init__.py`, either `server.json` path, or the
tag disagree, gating the `build → testpypi → pypi → mcp-registry` publish
chain. So don't flag those files' version updates in a release PR; **do**
flag a hand-edited version string outside a release PR, or a new file that
embeds the version without being added to `extra-files` (it would drift and
the `verify` job wouldn't catch it).

## 7. SIGINT shutdown in `__main__.py` is intentional, not an anti-pattern

`mcp.run()` is wrapped in `except (KeyboardInterrupt, asyncio.CancelledError)`
that calls `os._exit(0)`. This is deliberate: what escapes `mcp.run()` on ^C
is Python-version-dependent (bare `KeyboardInterrupt` on 3.12/3.13,
`asyncio.CancelledError` on 3.10), and `os._exit(0)` suppresses anyio's
teardown traceback. Don't suggest narrowing the catch to `KeyboardInterrupt`
only or swapping `os._exit` for `sys.exit`/a bare `return` — either would
break 3.10 or reintroduce the traceback. The behavior is guarded by
`tests/test_main.py::test_sigint_exits_cleanly` (skipped on Windows).

# Out of scope for review comments

- `release-please.yml`'s use of `secrets.RELEASE_PLEASE_TOKEN` instead of
  `GITHUB_TOKEN` is intentional (a `GITHUB_TOKEN`-authored release doesn't
  trigger the downstream `release` workflow); it falls back to
  `GITHUB_TOKEN` when the secret is unset so PR CI still passes on forks —
  don't suggest reverting it.
- The `zapi-lib` dependency (the actual Zabbix HTTP client, auth, and
  pagination) is out of scope here; it's reviewed in its own repository.
