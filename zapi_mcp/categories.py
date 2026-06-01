"""Site-specific monitoring categories for ``daily_brief``.

Categories are loaded from an INI file pointed to by ``ZABBIX_CATEGORIES_INI``.
This keeps organization-specific Zabbix tags and item keys out of the codebase
so the server stays generic and publishable. When unset or missing,
``daily_brief`` falls back to a generic active-problems summary.

Each ``[section]`` defines one category::

    [dhcp]
    name = DHCP Pool Usage
    tag = dhcp-pool-usage      ; Zabbix host tag identifying the group
    item_key = usage           ; if set -> report current item values
    threshold = 80             ; optional; flag values >= this

    [core]
    name = Core Network
    tag = role
    tag_value = main           ; tag must equal this value
                               ; no item_key -> report active problems
"""

import configparser
import os
from dataclasses import dataclass


def _safe_float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


@dataclass
class Category:
    """One monitoring category for the daily brief."""

    key: str
    name: str
    tag: str
    tag_value: str | None = None
    item_key: str | None = None
    item_key_search: str | None = None
    threshold: float | None = None

    @property
    def kind(self) -> str:
        """``items`` when an item key (exact or substring) is configured, else ``problems``."""
        return "items" if (self.item_key or self.item_key_search) else "problems"


def load_categories(path: str | None = None) -> list[Category]:
    """Load categories from an INI file (env ``ZABBIX_CATEGORIES_INI`` by default).

    Returns an empty list when no path is configured or the file is absent.
    """
    path = path or os.environ.get("ZABBIX_CATEGORIES_INI")
    if not path or not os.path.isfile(path):
        return []

    cp = configparser.ConfigParser()
    cp.read(path)

    categories: list[Category] = []
    for section in cp.sections():
        s = cp[section]
        tag = s.get("tag")
        if not tag:
            continue
        categories.append(
            Category(
                key=section,
                name=s.get("name", section),
                tag=tag,
                tag_value=s.get("tag_value") or None,
                item_key=s.get("item_key") or None,
                item_key_search=s.get("item_key_search") or None,
                threshold=_safe_float(s.get("threshold")),
            )
        )
    return categories
