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
  ZABBIX_API_TOKEN      Zabbix API token (Zabbix 5.4+), or instead:
  ZABBIX_USER           Zabbix API user
  ZABBIX_PASSWORD       Zabbix API password
  ZABBIX_CATEGORIES_INI Path to categories INI for --brief (optional)
  ZABBIX_READ_ONLY      true/1/yes/on: do not register acknowledge_problem and
                        set_maintenance (optional; any other non-false value is
                        also treated as read-only)
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

    from zapi_mcp.server import CredentialConflict, MissingEnv, zabbix_credentials

    try:
        credentials = zabbix_credentials()
    except CredentialConflict as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except MissingEnv as e:
        print(f"Error: missing environment variables: {e}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        try:
            client = ZapiClient(**credentials)
            auth = "Bearer header" if client._bearer else "auth field"
            kind = "API token" if "api_token" in credentials else "user/password"
            print(f"OK — Zabbix API {client.version} ({kind}, auth: {auth})")
        except ZapiError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)
        from zapi_mcp.server import WRITE_TOOLS, read_only_mode

        read_only, read_only_error = read_only_mode()
        if read_only:
            print(f"Read-only: write tools not registered ({', '.join(WRITE_TOOLS)})")
        else:
            print(f"Write tools registered: {', '.join(WRITE_TOOLS)}")
        if read_only_error:
            print(f"Error: {read_only_error}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

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
