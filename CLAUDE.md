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
  and the `mcp.run()` stdio server start.

## Conventions

- Python 3.10+, `requires-python = ">=3.10"`: native `X | Y` union syntax is
  used directly in annotations (no `from __future__ import annotations`
  needed, since 3.10 supports `|` at runtime).
- `ruff` lint rules: `E, F, I, W, UP`, line length 120.
- Tests mock Zabbix's JSON-RPC endpoint exclusively via `respx`
  (`tests/conftest.py`'s `make_router`); there is no `unittest.mock` usage in
  this suite. FastMCP-wrapped tool functions are called via their `.fn`
  attribute in tests (see `tests/test_server.py`'s `_call` helper).
