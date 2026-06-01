"""Tests for the CLI entry point (__main__.main)."""

import sys

import pytest

from tests.conftest import SAMPLE_PROBLEM, make_router
from zapi_mcp.__main__ import main


def test_version(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["zapi-mcp", "--version"])
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 0
    assert "zapi-mcp" in capsys.readouterr().out


def test_missing_env_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["zapi-mcp", "--check"])
    for var in ("ZABBIX_URL", "ZABBIX_USER", "ZABBIX_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1
    assert "missing environment variables" in capsys.readouterr().err


def test_check_ok(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["zapi-mcp", "--check"])
    monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")
    monkeypatch.setenv("ZABBIX_USER", "u")
    monkeypatch.setenv("ZABBIX_PASSWORD", "p")
    with make_router(version="6.0.42"):
        with pytest.raises(SystemExit) as e:
            main()
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "Zabbix API 6.0.42" in out
    assert "auth field" in out  # legacy path for 6.0


def test_brief_prints_daily_brief(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["zapi-mcp", "--brief"])
    monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")
    monkeypatch.setenv("ZABBIX_USER", "u")
    monkeypatch.setenv("ZABBIX_PASSWORD", "p")
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        with pytest.raises(SystemExit) as e:
            main()
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "# Daily Brief" in out
    assert "Active Problems" in out
