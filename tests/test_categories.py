"""Tests for category config loading."""

import sys

import pytest

from zapi_mcp.categories import load_categories


def test_no_path_returns_empty(monkeypatch):
    monkeypatch.delenv("ZABBIX_CATEGORIES_INI", raising=False)
    assert load_categories() == []


def test_missing_file_returns_empty(tmp_path):
    assert load_categories(str(tmp_path / "nope.ini")) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_unreadable_file_raises_oserror(tmp_path):
    """configparser.read() silently skips unreadable files instead of raising;
    load_categories must open the file itself so callers see a real error
    instead of a permission-denied file looking like "nothing configured"."""
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\ntag = dhcp\n")
    p.chmod(0o000)
    try:
        with pytest.raises(OSError):
            load_categories(str(p))
    finally:
        p.chmod(0o644)  # restore so tmp_path fixture cleanup can remove it


def test_invalid_encoding_raises_unicode_decode_error(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_bytes(b"[dhcp]\ntag = dhcp\nname = \xff\xfe bad bytes\n")
    with pytest.raises(UnicodeDecodeError):
        load_categories(str(p))


def test_item_category(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\nname = DHCP Pool Usage\ntag = dhcp-pool-usage\nitem_key = usage\nthreshold = 80\n")
    cats = load_categories(str(p))
    assert len(cats) == 1
    c = cats[0]
    assert c.key == "dhcp"
    assert c.name == "DHCP Pool Usage"
    assert c.tag == "dhcp-pool-usage"
    assert c.item_key == "usage"
    assert c.threshold == 80.0
    assert c.kind == "items"


def test_problem_category_without_item_key(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[core]\nname = Core Network\ntag = role\ntag_value = main\n")
    c = load_categories(str(p))[0]
    assert c.tag_value == "main"
    assert c.item_key is None
    assert c.kind == "problems"


def test_section_without_tag_is_skipped(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[bad]\nname = No Tag\n\n[good]\ntag = role\n")
    cats = load_categories(str(p))
    assert [c.key for c in cats] == ["good"]


def test_name_defaults_to_section(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[edge]\ntag = role\n")
    assert load_categories(str(p))[0].name == "edge"


def test_env_var_used(tmp_path, monkeypatch):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\ntag = dhcp\nitem_key = usage\n")
    monkeypatch.setenv("ZABBIX_CATEGORIES_INI", str(p))
    cats = load_categories()
    assert cats[0].key == "dhcp"


def test_non_numeric_threshold_does_not_crash(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\ntag = dhcp\nitem_key = usage\nthreshold = high\n")
    cats = load_categories(str(p))
    assert cats[0].threshold is None


def test_item_key_search_makes_items_category(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[snat]\ntag = snat\nitem_key_search = .usage\n")
    c = load_categories(str(p))[0]
    assert c.item_key is None
    assert c.item_key_search == ".usage"
    assert c.kind == "items"


def test_direction_defaults_to_above(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[dhcp]\ntag = dhcp\nitem_key = usage\n")
    assert load_categories(str(p))[0].direction == "above"


def test_direction_below_parsed(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[speedtest]\ntag = speedtest-z\nitem_key_search = download\ndirection = below\n")
    assert load_categories(str(p))[0].direction == "below"


def test_direction_invalid_falls_back_to_above(tmp_path):
    p = tmp_path / "cats.ini"
    p.write_text("[x]\ntag = t\nitem_key = k\ndirection = sideways\n")
    assert load_categories(str(p))[0].direction == "above"
