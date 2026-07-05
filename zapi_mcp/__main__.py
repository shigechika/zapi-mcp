"""Entry point for zapi-mcp."""

import argparse
import asyncio
import os
import sys

from zapi_mcp import __version__
from zapi_mcp.client import ZapiClient, ZapiError


def main():
    parser = argparse.ArgumentParser(
        description="Zabbix API MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Required environment variables:
  ZABBIX_URL            Zabbix frontend URL (e.g. https://zabbix.example.com)
  ZABBIX_USER           Zabbix API user
  ZABBIX_PASSWORD       Zabbix API password
  ZABBIX_CATEGORIES_INI Path to categories INI for --brief (optional)
""",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    parser.add_argument("--check", action="store_true", help="Verify connection and exit")
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Print the daily_brief to stdout and exit (handy for cron / smoke tests)",
    )
    args = parser.parse_args()

    if args.version:
        print(f"zapi-mcp {__version__}")
        sys.exit(0)

    url = os.environ.get("ZABBIX_URL")
    user = os.environ.get("ZABBIX_USER")
    password = os.environ.get("ZABBIX_PASSWORD")

    if not all([url, user, password]):
        pairs = [("ZABBIX_URL", url), ("ZABBIX_USER", user), ("ZABBIX_PASSWORD", password)]
        missing = [v for v, k in pairs if not k]
        print(f"Error: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        try:
            client = ZapiClient(url, user, password)
            auth = "Bearer header" if client._bearer else "auth field"
            print(f"OK — Zabbix API {client.version} (auth: {auth})")
            sys.exit(0)
        except ZapiError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)

    if args.brief:
        from zapi_mcp.server import _daily_brief_text

        text, had_error = _daily_brief_text()
        print(text)
        sys.exit(1 if had_error else 0)

    from zapi_mcp.server import mcp

    try:
        mcp.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        # anyio's teardown on SIGINT dumps a 20-80 line traceback. What it
        # raises out of mcp.run() is Python-version-dependent: a bare
        # KeyboardInterrupt on 3.12/3.13, but asyncio.CancelledError on 3.10
        # (asyncio.Runner.run() re-raises CancelledError instead of letting
        # KeyboardInterrupt propagate — verified against this repo's own CI
        # matrix). Catch both and exit clean like the sibling fleet MCP
        # servers (junos-mcp, eos-mcp, aruba-central-mcp, keycloak-mcp).
        os._exit(0)


if __name__ == "__main__":
    main()
