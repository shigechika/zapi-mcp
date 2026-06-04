# Changelog

## [0.5.0](https://github.com/shigechika/zapi-mcp/compare/v0.4.0...v0.5.0) (2026-06-04)


### Features

* depend on zapi-lib for the Zabbix client ([#9](https://github.com/shigechika/zapi-mcp/issues/9)) ([a2a785a](https://github.com/shigechika/zapi-mcp/commit/a2a785a904455ed4ba82430e851df20dd29b82d8))

## [0.4.0](https://github.com/shigechika/zapi-mcp/compare/v0.3.0...v0.4.0) (2026-06-04)


### Features

* support below-threshold flagging in daily_brief categories ([#7](https://github.com/shigechika/zapi-mcp/issues/7)) ([4b208c5](https://github.com/shigechika/zapi-mcp/commit/4b208c5c327170708cff43b7bf3d14827e03b0c5))

## [0.3.0](https://github.com/shigechika/zapi-mcp/compare/v0.2.0...v0.3.0) (2026-06-04)


### Features

* add health_check tool ([#4](https://github.com/shigechika/zapi-mcp/issues/4)) ([e13edfd](https://github.com/shigechika/zapi-mcp/commit/e13edfdc0758282d755ee58224ef8b2da66c82ce))
* add ZapiClient.set_host_tag for upserting host tags ([#5](https://github.com/shigechika/zapi-mcp/issues/5)) ([406cc54](https://github.com/shigechika/zapi-mcp/commit/406cc54e3269f7269d212f049d957db37419e222))

## 0.2.0 (2026-06-01)

> Note: git history was reset before this repository was made public, so the
> per-commit and pull-request links from the original 0.2.0 entry no longer
> resolve and have been removed. The change summary below is unchanged.


### Features

* add --brief CLI flag (print daily_brief and exit)
* recency-focused, total-aware Active Problems in daily_brief
* recency-focused, total-aware get_problems + configurable fetch cap
* substring item-key matching, value rounding, brief item cap


### Bug Fixes

* address adversarial review findings
