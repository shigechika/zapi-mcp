# Changelog

## [0.5.0](https://github.com/shigechika/zapi-mcp/compare/v0.4.0...v0.5.0) (2026-06-04)


### Features

* depend on zapi-lib for the Zabbix client ([#9](https://github.com/shigechika/zapi-mcp/issues/9)) ([73b6741](https://github.com/shigechika/zapi-mcp/commit/73b674148fea3aec0bdfeb8511896c0b1126184a))

## [0.4.0](https://github.com/shigechika/zapi-mcp/compare/v0.3.0...v0.4.0) (2026-06-04)


### Features

* support below-threshold flagging in daily_brief categories ([#7](https://github.com/shigechika/zapi-mcp/issues/7)) ([c9500c7](https://github.com/shigechika/zapi-mcp/commit/c9500c77600ecd4dce825cdd532dd4b31539ae88))

## [0.3.0](https://github.com/shigechika/zapi-mcp/compare/v0.2.0...v0.3.0) (2026-06-04)


### Features

* add health_check tool ([#4](https://github.com/shigechika/zapi-mcp/issues/4)) ([be1d685](https://github.com/shigechika/zapi-mcp/commit/be1d685ec04213242278929ba3f6809ed9b45c21))
* add ZapiClient.set_host_tag for upserting host tags ([#5](https://github.com/shigechika/zapi-mcp/issues/5)) ([396c68f](https://github.com/shigechika/zapi-mcp/commit/396c68ff001f59d85c0f03f3bd9a88479bbe0008))

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
