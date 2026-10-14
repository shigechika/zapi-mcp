"""ZABBIX_READ_ONLY: write tools are not registered, and refuse to run if called directly."""

import asyncio
import importlib

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from zapi_mcp import server


def _tool_names(srv):
    return {t.name for t in asyncio.run(srv.mcp.list_tools())}


@pytest.fixture
def reload_with(monkeypatch):
    """Reload the server module under a given ZABBIX_READ_ONLY, then restore it."""

    def _reload(value):
        if value is None:
            monkeypatch.delenv("ZABBIX_READ_ONLY", raising=False)
        else:
            monkeypatch.setenv("ZABBIX_READ_ONLY", value)
        return importlib.reload(server)

    yield _reload
    # Restore the environment first, then rebuild the module from it.
    monkeypatch.undo()
    importlib.reload(server)


def test_write_tools_are_the_ones_annotated_as_writes():
    assert set(server.WRITE_TOOLS) == {"acknowledge_problem", "set_maintenance"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, (False, None)),
        ("", (False, None)),
        ("off", (False, None)),
        (" TRUE ", (True, None)),
        ("1", (True, None)),
    ],
)
def test_read_only_mode_parses_the_value(value, expected):
    env = {} if value is None else {"ZABBIX_READ_ONLY": value}
    assert server.read_only_mode(env) == expected


@pytest.mark.parametrize("value", [None, "", "0", "false", "No", "off"])
def test_write_tools_are_registered_by_default(reload_with, value):
    srv = reload_with(value)
    assert set(srv.WRITE_TOOLS) <= _tool_names(srv)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_read_only_removes_the_write_tools(reload_with, value):
    srv = reload_with(value)
    names = _tool_names(srv)
    assert not set(srv.WRITE_TOOLS) & names
    assert {"daily_brief", "get_problems", "health_check", "get_maintenance_windows"} <= names


def test_an_unrecognized_value_is_treated_as_read_only(reload_with):
    srv = reload_with("ture")
    assert not set(srv.WRITE_TOOLS) & _tool_names(srv)
    read_only, error = srv.read_only_mode()
    assert read_only is True and "ture" in error


def test_write_tools_refuse_when_called_directly_in_read_only_mode(reload_with):
    srv = reload_with("true")
    with pytest.raises(ToolError, match="read-only"):
        srv.acknowledge_problem("1", "msg")
    with pytest.raises(ToolError, match="read-only"):
        srv.set_maintenance("2026/01/01 00:00:00", "2026/01/01 01:00:00", "n", "d", location="x")


def test_every_write_tool_is_guarded(reload_with):
    """A new write tool gets the guard from its annotation alone; nothing to remember."""
    srv = reload_with("true")
    for name in srv.WRITE_TOOLS:
        fn = getattr(srv, name)
        with pytest.raises(ToolError, match="read-only"):
            _call_with_dummies(fn)


def _call_with_dummies(fn):
    import inspect

    params = inspect.signature(fn).parameters
    return fn(**{p: "x" for p, spec in params.items() if spec.default is inspect.Parameter.empty})


def test_tool_annotations_mark_read_and_write_tools():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for name, tool in tools.items():
        assert tool.annotations is not None, name
        assert tool.annotations.read_only_hint is (name not in server.WRITE_TOOLS), name
        assert tool.annotations.open_world_hint is False, name
    assert tools["set_maintenance"].annotations.idempotent_hint is True
    assert tools["acknowledge_problem"].annotations.idempotent_hint is False


def _health(srv, monkeypatch):
    from tests.conftest import make_router

    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    srv.reset_client()
    with make_router():
        return srv.health_check()


def test_health_check_reports_the_mode(reload_with, monkeypatch):
    srv = reload_with(None)
    out = _health(srv, monkeypatch)
    assert out["read_only"] is False and out["status"] == "healthy"
    srv = reload_with("on")
    out = _health(srv, monkeypatch)
    assert out["read_only"] is True and out["status"] == "healthy"
    assert "read_only_error" not in out


def test_health_check_degrades_on_an_unrecognized_value(reload_with, monkeypatch):
    srv = reload_with("maybe")
    out = _health(srv, monkeypatch)
    assert out["read_only"] is True
    assert out["status"] == "degraded"
    assert "maybe" in out["read_only_error"]
