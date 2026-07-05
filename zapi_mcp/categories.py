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
    threshold = 80             ; optional; flag values past the threshold
    direction = above          ; optional; "above" (default) flags >= threshold,
                               ;   "below" flags <= threshold (e.g. speed drops)

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


def _normalize_direction(value: str | None) -> str:
    """Return 'below' only for an explicit 'below'; default to 'above'."""
    return "below" if (value or "").strip().lower() == "below" else "above"


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
    direction: str = "above"  # "above": flag >= threshold; "below": flag <= threshold

    @property
    def kind(self) -> str:
        """``items`` when an item key (exact or substring) is configured, else ``problems``."""
        return "items" if (self.item_key or self.item_key_search) else "problems"


def load_categories(path: str | None = None) -> list[Category]:
    """Load categories from an INI file (env ``ZABBIX_CATEGORIES_INI`` by default).

    Returns an empty list when no path is configured or the file is absent.
    Raises ``configparser.Error`` (malformed INI, e.g. a missing section header
    or duplicate section), ``OSError`` (unreadable file), or
    ``UnicodeDecodeError`` (file isn't valid text) if the path exists but
    can't be parsed — callers that must not crash on a bad config should
    catch those three types.
    """
    path = path or os.environ.get("ZABBIX_CATEGORIES_INI")
    if not path or not os.path.isfile(path):
        return []

    # configparser.ConfigParser.read() silently swallows OSError per file
    # (its own try/except continues past unreadable files instead of
    # raising), which would make a permission-denied categories.ini look
    # identical to "nothing configured". Open it ourselves so a real OSError
    # propagates instead of being hidden.
    cp = configparser.ConfigParser()
    with open(path) as fp:
        cp.read_file(fp, source=path)

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
                direction=_normalize_direction(s.get("direction")),
            )
        )
    return categories
