# `daily_brief` のカテゴリ設定

`daily_brief` は常にアクティブな問題を一覧します。カテゴリは、そのレポートを
自分たちのものにするセクションを足す仕組みです。DHCP プールの枯渇、SNAT セッション
使用率、コアネットワーク機器の健全性 — その Zabbix が実際に見ているものを載せます。

設定は `ZABBIX_CATEGORIES_INI` が指す INI ファイルに置きます。この変数が未設定でも
ファイルが無くても `daily_brief` はアクティブな問題だけを報告し、壊れません。

## なぜコードではなく設定ファイルなのか

このサーバーは PyPI で公開され、複数のサイトで使われます。ホストタグ・アイテムキー・
閾値は、まさに環境ごとに異なるものであり、同時に**公開リポジトリに組織のインベントリ
を漏らしてしまう**類のものです。ローカルの INI に置くことで、パッケージは汎用のまま、
命名は自分たちのものに保てます。

## ファイル

`[section]` 1つが1カテゴリです。

```ini
[dhcp]
name = DHCP Pool Usage
tag = dhcp-pool-usage      ; カテゴリを識別する Zabbix ホストタグ
item_key = usage           ; このアイテムキーの現在値を報告する
threshold = 80             ; この値以上をフラグ

[snat]
name = SNAT Session Pool
tag = snat-pool-usage
item_key_search = .usage   ; 部分一致（pool.node0.usage 等を拾う）
threshold = 80

[core]
name = Core Network
tag = role
tag_value = main           ; タグがこの値と一致すること
                           ; アイテムキー無し -> アクティブな問題を報告する
```

リポジトリの [`categories.ini.example`](https://github.com/shigechika/zapi-mcp/blob/main/categories.ini.example)
も参照してください。

## キー

| キー | 必須 | 意味 |
|---|---|---|
| `name` | ○ | レポート上のセクション見出し |
| `tag` | ○ | カテゴリを識別するホストタグ |
| `tag_value` | | 指定時はタグがこの値と**一致**すること（Equal）。省略時はタグを持つホストすべてが対象（Exists） |
| `item_key` | | 完全一致のアイテムキー。指定するとそのセクションは現在値を報告する |
| `item_key_search` | | アイテムキーの部分一致。キーに ID が埋め込まれている場合に使う |
| `threshold` | | この値に達した／超えた値をフラグ |
| `direction` | | `above`（既定）は閾値以上をフラグ、`below` は閾値以下をフラグ |

## セクションの2種類

**アイテムセクション** — `item_key` か `item_key_search` を設定した場合。現在の
アイテム値を大きい順に報告し、閾値を超えたものをフラグします。トリガーが発火する
**前**に数値が上限へ近づくのを見るための仕組みで、プール使用率を朝のレポートに
載せる目的そのものです。

**問題セクション** — どちらも設定しない場合。タグを持つホストのアクティブな問題を
報告します。「とにかく何か異常が出ていないか」が問いになる機器群に向いています。

## `item_key` と `item_key_search` の使い分け

どのホストでもキーが同一なら `item_key`（例: `usage`）。

キーに識別子が埋め込まれていて（`POOL-001.node0.usage`・`POOL-002.node1.usage`）、
1つの完全一致キーでは全部を拾えない場合は `item_key_search`。`.usage` のような
末尾の断片でファミリー全体を拾えます。

トレードオフは精度です。部分一致は意図しないキーにも喜んでマッチします。対象を
カバーできる範囲で、できるだけ具体的な断片を選んでください。

## 下限を見る `direction`

多くのカテゴリは上限へ向かって増える数値を見ます。一方、下限を割ることを見たい
ものもあります。たとえば速度計測ホストのダウンロード帯域は、ギガビット回線が
100 Mbps を下回ることこそが事象です。

```ini
[speedtest]
name = Link throughput
tag = speedtest
item_key_search = _DL
direction = below
threshold = 100000000
```

## 失敗したときの挙動

INI の記述ミス・読めないファイル・権限不足は、**黙って「カテゴリ無し」に劣化しません**。
`daily_brief` は `(Categories not loaded: …)` の行を出すのでレポート自体で欠落が
見え、`health_check` は解析失敗を `categories_error` に載せます。

読み込みには成功したが Zabbix への問い合わせが失敗したカテゴリは、そのセクションの
下に `Error: …` としてその場に表示され、レポートの残りはそのまま出ます。朝の
レポートが黙ってセクションを落とすのは、壊れたと言ってくれるより悪いことです。
