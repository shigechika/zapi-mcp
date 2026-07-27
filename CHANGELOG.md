# Changelog

## [0.6.1](https://github.com/shigechika/zapi-mcp/compare/v0.6.0...v0.6.1) (2026-07-27)


### Bug Fixes

* **ci:** read AI-review guidance from the base revision, drop the checkout ([#43](https://github.com/shigechika/zapi-mcp/issues/43)) ([3d58111](https://github.com/shigechika/zapi-mcp/commit/3d5811147ba79b550848c2b2a434c52a63670a8d))
* sync the smoke-test engine ([#40](https://github.com/shigechika/zapi-mcp/issues/40)) ([22c7c1a](https://github.com/shigechika/zapi-mcp/commit/22c7c1a11a61b88db0b062a9f57c25b812efa4d1))

## [0.6.0](https://github.com/shigechika/zapi-mcp/compare/v0.5.2...v0.6.0) (2026-07-26)


### Features

* live smoke test that exercises every registered tool ([#35](https://github.com/shigechika/zapi-mcp/issues/35)) ([f9c410e](https://github.com/shigechika/zapi-mcp/commit/f9c410e96caad7b43f8f356758e401d6b7c92211))


### Bug Fixes

* sync the smoke-test engine and unwrap the --stdio result ([#38](https://github.com/shigechika/zapi-mcp/issues/38)) ([ba9cc15](https://github.com/shigechika/zapi-mcp/commit/ba9cc15ff3166d1a5d9a1b237a6c662e6a152000))

## [0.5.2](https://github.com/shigechika/zapi-mcp/compare/v0.5.1...v0.5.2) (2026-07-05)


### Bug Fixes

* exit cleanly on ^C instead of dumping an anyio teardown traceback ([#16](https://github.com/shigechika/zapi-mcp/issues/16)) ([338c73f](https://github.com/shigechika/zapi-mcp/commit/338c73fd79543f16fab064984b509c3aeeabe945))

## [0.5.1](https://github.com/shigechika/zapi-mcp/compare/v0.5.0...v0.5.1) (2026-07-05)


### Bug Fixes

* pin categories.ini reads to UTF-8 (fixes Windows CI failure) ([#15](https://github.com/shigechika/zapi-mcp/issues/15)) ([5c037d5](https://github.com/shigechika/zapi-mcp/commit/5c037d593d7823e41f4c081870d8a77fcd533bc0))
* pre-public cleanup (docs parity, error handling, LICENSE name order) ([#14](https://github.com/shigechika/zapi-mcp/issues/14)) ([d6a62f4](https://github.com/shigechika/zapi-mcp/commit/d6a62f4b8036cf7d724a768c2eca212514de4a98))

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
