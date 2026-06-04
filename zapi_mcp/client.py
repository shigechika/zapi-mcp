"""Backward-compatible shim — the Zabbix client now lives in zapi-lib.

``ZapiClient`` and friends were spun out into the standalone `zapi-lib` package
so consumers that only need the API client (speedtest-z, pyez/srx) can depend on
it without pulling in the MCP server stack. This module re-exports them so that
existing ``from zapi_mcp.client import ZapiClient`` imports keep working.
"""

from zapi_lib.client import (
    DEFAULT_TIMEOUT,
    TAG_OP_EQUAL,
    TAG_OP_EXISTS,
    ZapiAuthError,
    ZapiClient,
    ZapiError,
    tag_filter,
)

__all__ = [
    "ZapiClient",
    "ZapiError",
    "ZapiAuthError",
    "tag_filter",
    "TAG_OP_EQUAL",
    "TAG_OP_EXISTS",
    "DEFAULT_TIMEOUT",
]
