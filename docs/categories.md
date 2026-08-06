# Categories for `daily_brief`

`daily_brief` always lists active problems. Categories add the sections that
make the report yours: DHCP pool exhaustion, SNAT session usage, the health of
core network devices — whatever your Zabbix installation actually tracks.

They live in an INI file pointed to by `ZABBIX_CATEGORIES_INI`. When the
variable is unset or the file is missing, `daily_brief` reports active problems
only, and nothing breaks.

## Why a config file instead of code

This server is published on PyPI and used by more than one site. Host tags,
item keys and thresholds are exactly the things that differ between
installations — and exactly the things that would otherwise leak an
organization's inventory into a public repository. Keeping them in a local INI
means the package stays generic and your naming stays yours.

## The file

Each `[section]` is one category:

```ini
[dhcp]
# Zabbix host tag identifying the group
tag = dhcp-pool-usage
# report current values for this exact item key
item_key = usage
# flag values >= this
threshold = 80
name = DHCP Pool Usage

[snat]
tag = snat-pool-usage
# substring match (catches pool.node0.usage etc.)
item_key_search = .usage
threshold = 80
name = SNAT Session Pool

[core]
tag = role
# the tag must equal this value
tag_value = main
# no item key -> report active problems instead
name = Core Network
```

!!! warning "Comments must be on their own line"
    `configparser` is used without `inline_comment_prefixes`, so a trailing
    `; comment` becomes part of the value. Written inline, `tag = foo ; bar`
    looks for a tag literally named `foo ; bar` (matching nothing) and a
    `threshold` with a trailing comment parses as no threshold at all — both
    silently. Keep comments on their own line, as above.

See [`categories.ini.example`](https://github.com/shigechika/zapi-mcp/blob/main/categories.ini.example)
in the repository.

## Keys

| Key | Required | Meaning |
|---|---|---|
| `name` | no | Section heading in the report; defaults to the section name in brackets |
| `tag` | **yes** | Host tag identifying the category. A section without it is skipped |
| `tag_value` | no | When set, the tag must **equal** this value (Equal). When absent, any host carrying the tag matches (Exists) |
| `item_key` | no | Exact item key; the section reports current values |
| `item_key_search` | no | Substring match on the item key, for keys that embed an id |
| `threshold` | no | Values at or beyond it are flagged |
| `direction` | no | `above` (default) flags values ≥ threshold; `below` flags values ≤ threshold |

## Two kinds of section

**Item sections** — set `item_key` or `item_key_search`. The section reports
current item values sorted high to low, flagging anything past the threshold.
This is how you watch a number climb toward a limit *before* a trigger fires,
which is the whole point of putting pool usage in a morning report.

**Problem sections** — set neither. The section reports active problems for
hosts carrying the tag, which is what you want for a group of devices where
"anything wrong at all" is the question.

## Choosing `item_key` vs `item_key_search`

Use `item_key` when the key is identical on every host (`usage`).

Use `item_key_search` when the key embeds an identifier —
`POOL-001.node0.usage`, `POOL-002.node1.usage` — and no single exact key would
match them all. A trailing fragment like `.usage` catches the family.

The trade-off is precision: a substring is happy to match keys you did not
intend. Prefer the most specific fragment that still covers the set.

## `direction` for lower bounds

Most categories watch a number growing toward a ceiling. Some watch it falling
through a floor — download throughput on a speed-test host, for instance, where
a gigabit link dropping under 100 Mbps is the event.

```ini
[speedtest]
name = Link throughput
tag = speedtest
item_key_search = _DL
direction = below
threshold = 100000000
```

## Failure behaviour

**Reported.** A malformed INI, an unreadable file or a bad permission does
**not** silently degrade to "no categories": `daily_brief` emits a
`(Categories not loaded: …)` line so the omission is visible in the report
itself, and `health_check` carries the failure in `categories_error`. This
covers what the parser raises — `configparser.Error`, `OSError`,
`UnicodeDecodeError`.

A category that loads but whose Zabbix query fails is rendered inline as
`Error: …` under that section, leaving the rest of the brief intact. A morning
report that quietly drops a section is worse than one that says it broke.

**Silent.** Mistakes *within* a well-formed file are not reported, so check
these by reading `health_check`'s `categories` list rather than expecting an
error:

- a section with no `tag` (a typo such as `tags =`) is skipped entirely — it
  simply never appears in the brief
- a `threshold` that is not a number is treated as no threshold, so nothing is
  ever flagged
- a `direction` other than `below` — including a misspelling like `under` —
  falls back to `above`

If a section you configured is missing from `health_check`'s `categories`, a
missing or misspelled `tag` is the first thing to check.
