"""Tests for the CLI entry point (__main__.main)."""

import os
import signal
import subprocess
import sys
import time

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


def test_brief_exits_1_on_bad_categories(monkeypatch, capsys, tmp_path):
    """A malformed categories.ini must surface as a non-zero exit code so cron
    failure monitoring catches it, even though the brief itself doesn't crash."""
    monkeypatch.setattr(sys, "argv", ["zapi-mcp", "--brief"])
    monkeypatch.setenv("ZABBIX_URL", "https://zabbix.example.com")
    monkeypatch.setenv("ZABBIX_USER", "u")
    monkeypatch.setenv("ZABBIX_PASSWORD", "p")
    p = tmp_path / "bad.ini"
    p.write_text("this is not a valid ini\nno section header here\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    with make_router(results={"problem.get": [SAMPLE_PROBLEM]}):
        with pytest.raises(SystemExit) as e:
            main()
    assert e.value.code == 1
    out = capsys.readouterr().out
    assert "Categories not loaded" in out


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT semantics differ on Windows")
def test_sigint_exits_cleanly():
    """^C must exit 0 with no anyio teardown traceback (issue #11)."""
    env = dict(os.environ, ZABBIX_URL="https://zabbix.example.com", ZABBIX_USER="u", ZABBIX_PASSWORD="p")
    proc = subprocess.Popen(
        [sys.executable, "-m", "zapi_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        time.sleep(2)  # let the stdio server actually start before signalling it
        proc.send_signal(signal.SIGINT)
        _, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    assert proc.returncode == 0
    assert b"Traceback" not in stderr
