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
# カテゴリを識別する Zabbix ホストタグ
tag = dhcp-pool-usage
# このアイテムキー（完全一致）の現在値を報告する
item_key = usage
# この値以上をフラグ
threshold = 80
name = DHCP Pool Usage

[snat]
tag = snat-pool-usage
# 部分一致（pool.node0.usage 等を拾う）
item_key_search = .usage
threshold = 80
name = SNAT Session Pool

[core]
tag = role
# タグがこの値と一致すること
tag_value = main
# アイテムキー無し -> アクティブな問題を報告する
name = Core Network
```

!!! warning "コメントは行を分けて書くこと"
    `configparser` を `inline_comment_prefixes` 無しで使っているため、行末の
    `; コメント` は値の一部になります。`tag = foo ; bar` と書くと
    `foo ; bar` という名前のタグを探して（何にも一致せず）、行末コメント付きの
    `threshold` は閾値なしとして解析されます。どちらも無言で起きます。上の例の
    ようにコメントは独立した行に書いてください。

リポジトリの [`categories.ini.example`](https://github.com/shigechika/zapi-mcp/blob/main/categories.ini.example)
も参照してください。

## キー

| キー | 必須 | 意味 |
|---|---|---|
| `name` | | レポート上のセクション見出し。省略時は `[ ]` 内のセクション名 |
| `tag` | **○** | カテゴリを識別するホストタグ。無いセクションはスキップされる |
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

**報告されるもの。** INI の構文エラー・読めないファイル・権限不足は、**黙って
「カテゴリ無し」に劣化しません**。`daily_brief` は `(Categories not loaded: …)` の
行を出すのでレポート自体で欠落が見え、`health_check` は失敗を `categories_error` に
載せます。対象はパーサーが送出するもの（`configparser.Error`・`OSError`・
`UnicodeDecodeError`）です。

読み込みには成功したが Zabbix への問い合わせが失敗したカテゴリは、そのセクションの
下に `Error: …` としてその場に表示され、レポートの残りはそのまま出ます。朝の
レポートが黙ってセクションを落とすのは、壊れたと言ってくれるより悪いことです。

**黙って起きるもの。** 構文として正しいファイル**の中身**の誤りは報告されません。
エラーを期待せず、`health_check` の `categories` 一覧を読んで確認してください。

- `tag` の無いセクション（`tags =` のような打ち間違い）は丸ごとスキップされ、
  ブリーフに一切現れません
- 数値として解釈できない `threshold` は「閾値なし」として扱われ、何もフラグされません
- `below` 以外の `direction`（`under` のような綴り間違いを含む）は `above` に倒れます

設定したはずのセクションが `health_check` の `categories` に無ければ、まず `tag` の
欠落・綴り間違いを疑ってください。
