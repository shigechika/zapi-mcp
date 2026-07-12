# CLAUDE.md

## Overview

MCP (Model Context Protocol) server for the Zabbix API. Exposes a
`daily_brief` morning-patrol summary plus problem/host/item query and
acknowledgement tools to AI assistants via STDIO transport, built on the
official `mcp` Python SDK's `FastMCP`.

## Commands

```bash
uv sync --dev
uv run pytest -v                    # run all tests
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
```

This mirrors `.github/workflows/ci.yml` (separate `lint` and `test` jobs;
`test` runs on Python 3.10/3.12/3.13 on Linux plus one Windows 3.12 smoke job
to guard against stdio newline regressions).

## Architecture

- `zapi_mcp/server.py` — FastMCP server with 6 tools: `health_check`,
  `daily_brief`, `get_problems`, `get_hosts`, `get_host_items`,
  `acknowledge_problem`.
- `zapi_mcp/client.py` — backward-compatible re-export shim; the real
  `ZapiClient`/`ZapiError`/`tag_filter` now live in the separate `zapi-lib`
  package.
- `zapi_mcp/categories.py` — `Category` dataclass + `load_categories()` for
  the optional `ZABBIX_CATEGORIES_INI`-driven `daily_brief` sections.
- `zapi_mcp/__main__.py` — CLI entry point (`--version`/`--check`/`--brief`)
  and the `mcp.run()` stdio server start. The `mcp.run()` call is wrapped in
  `except (KeyboardInterrupt, asyncio.CancelledError)` → `os._exit(0)`: what
  escapes on ^C is Python-version-dependent (3.10 raises `CancelledError`,
  3.12/3.13 raise `KeyboardInterrupt`) and `os._exit(0)` suppresses anyio's
  teardown traceback (guarded by `test_main.py::test_sigint_exits_cleanly`).

## Release pipeline

Versions are owned by release-please, never hand-edited. A release PR bumps
the string in lockstep across `zapi_mcp/__init__.py` (`x-release-please-version`
marker), `server.json`'s `$.version` and `$.packages[0].version`, and
`.release-please-manifest.json` — the first three are declared in
`release-please-config.json`'s `extra-files`. On the published tag,
`.github/workflows/release.yml`'s `verify` job hard-fails on any mismatch
between the tag, `__init__.py`, and both `server.json` paths, then gates the
`build → testpypi → pypi → mcp-registry` publish chain.

## Conventions

- Python 3.10+, `requires-python = ">=3.10"`: native `X | Y` union syntax is
  used directly in annotations (no `from __future__ import annotations`
  needed, since 3.10 supports `|` at runtime).
- `ruff` lint rules: `E, F, I, W, UP`, line length 120.
- Tests mock Zabbix's JSON-RPC endpoint exclusively via `respx`
  (`tests/conftest.py`'s `make_router`); there is no `unittest.mock` usage in
  this suite. Tests call tools through `tests/test_server.py`'s `_call()`
  helper (`getattr(tool, "fn", tool)`) rather than calling the tool directly,
  so the suite keeps working whether `@mcp.tool()` returns the plain function
  (the current behavior, in this repo's pinned `mcp` version) or a wrapper
  exposing it via `.fn`.
