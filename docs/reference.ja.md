# リファレンス

## ツール

### `health_check()`

次のキーはどの経路でも必ず返ります。健全性の判断にキーの有無を調べる必要はなく、
`status` を読めば残りはそこにあります。

| キー | 意味 |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | 常に `zapi-mcp` |
| `version` | パッケージのバージョン |
| `zabbix_url` | 設定された URL（未設定なら空文字列） |
| `zabbix_api_version` | 検出した API バージョン。接続に成功するまでは `null` |
| `auth` | `ok` / `error` / `missing-env` |
| `categories` | 読み込まれた `daily_brief` カテゴリ名 |

次の2つは、伝えるべきことがあるときだけ現れます。

| キー | 現れる条件 |
|---|---|
| `detail` | バックエンド側の問題が起きたとき。環境変数の欠落（`status=error`・`auth=missing-env`）または Zabbix エラー（`status=degraded`・`auth=error`） |
| `categories_error` | カテゴリファイルの解析に失敗したとき（`status=degraded`） |

この2つは独立しています。カテゴリファイルが読めないことだけが原因の場合、
`status=degraded` と `categories_error` は返りますが `detail` は**付きません**。
バックエンド自体には問題が無かったからです。

意図的に軽量です。認証を1回行い（キャッシュ済みセッションを再利用）、API バージョンを
読むだけで、問題やアイテムの走査はしません。セッション開始時やツール呼び出しの
タイムアウト後に安心して呼べます。

### `daily_brief()`

朝のレポートです。構造:

```text
# Daily Brief — 2026-08-06 09:00

## Active Problems (showing 50 of 97)

### High (23, 2 in last 24h)
- Unavailable by ICMP ping  eventid=18813696  (2026-08-06 07:12, 2h ago)
- … and 21 older (stale; oldest 2024-10-04 10:39)

## In Maintenance (1 window)
- Legal-inspection-2608110900h  until 2026-08-11 17:00:00  (12 hosts: sw-01, sw-02, sw-03, sw-04, sw-05, sw-06, … and 6 more)

## DHCP Pool Usage (2 hosts)
- POOL-A: 100.0 %  ⚠️  (2026-08-06 09:00:00)
- POOL-B: 82.3 %  (2026-08-06 09:00:00)
```

問題は Warning 以上を新しい順に、`eventid`・発生時刻・経過時間つきで並べます。
深刻度の見出しには件数と、そのうち直近何件かが入ります。`ZABBIX_BRIEF_RECENT_HOURS`
より古いものは `… and N older` の行に畳まれます。各行に深刻度名は繰り返しません
（見出しが既に示しているため）。

Active Problems の直後にある `## In Maintenance` は、現在有効なメンテナンス
ウィンドウと、本日これから始まるウィンドウの対象ホストを一覧します。同じ
ホストについて他ツールが検知した異常を新規障害と誤認する前に、ここと突き
合わせてください。該当が無ければセクション自体を**出しません** ―
セクションが無いブリーフは、現在（または本日中に）登録済みメンテナンス
ウィンドウの対象になっているホストが無いことを意味します。もっと先の窓や
期限切れの窓を見るには、後述の `get_maintenance_windows()` を呼びます。

続いて、設定した `[section]` ごとにカテゴリのセクションが並び、閾値を超えた
値には `⚠️` が付きます。

### `get_problems(min_severity=2, tag_name=None, tag_value=None, limit=50)`

アクティブな問題を新しい順・経過時間つきで返します。`limit` で打ち切られた場合は
見出しが `Active Problems (showing N of TOTAL)`、そうでなければ `Active Problems (N)`
になります。総数は推測ではなく件数クエリを別途投げて取るので正確です。出力には
`eventid` が含まれ、これが `acknowledge_problem` の入力になります。

深刻度: `0` 未分類、`1` 情報、`2` 警告、`3` 平均、`4` 重度、`5` 致命的。

### `get_hosts(role=None, tag_name=None, tag_value=None, group=None)`

ホストを IP・タグつきで返します。`role` は `role` タグの短縮指定です。

### `get_host_items(host, search=None)`

1ホスト（ホスト名は完全一致）の現在のアイテム値を返します。`search` はアイテム名の
部分一致フィルタです。

### `acknowledge_problem(event_ids, message)`

**書き込みツールです**（`set_maintenance` も同様）。カンマ区切りのイベント ID
を acknowledge し、メッセージを添付します。問題のクローズはしません。
acknowledge はその Zabbix の全オペレーターに見え、黙って取り消すことができ
ません。だからライブスモークテストはこのツールを名指しでスキップし、その
スキップをユニットテストが強制しています。

### `get_maintenance_windows(include_expired=False)`

`set_maintenance` の読み取り版です。Zabbix のメンテナンスウィンドウを
Active / Upcoming（`include_expired=True` なら Expired も）に分けて一覧します:

```text
Maintenance Windows (1 active, 1 upcoming):

## Active
- Legal-inspection-2608110900h  2026-08-11 09:00:00 → 2026-08-11 17:00:00
  Annual legal inspection
  12 hosts: sw-01, sw-02, rt-01, rt-02, ap-01, ap-02, fw-01, fw-02, … and 4 more

## Upcoming
- UPS-check-2608150900h  2026-08-15 09:00:00 → 2026-08-15 12:00:00  [no data collection]
  UPS battery replacement
  2 hosts: b-sw-01, b-sw-02
```

「Active」は、ウィンドウの外枠（`active_since`/`active_till`）だけでなく
その中の時間帯（time period）自体に現在時刻が入っていることを意味します ―
`set_maintenance`/`set_maintenance_for_hosts` が作る one-time 窓では正確に
判定できます。繰り返し設定（Zabbix UI 等、このサーバの外で作られたもの）の
窓は外枠だけで判定し `(recurring)` と表示します。`[no data collection]` は
アラート抑止だけでなくデータ収集自体も止める窓に付きます。`set_maintenance`
は窓を削除しない設計のため期限切れの窓は増え続けます ― 既定では除外し、
`include_expired=True` で表示します。0件時: `No maintenance windows.`

## CLI

```bash
zapi-mcp            # MCP サーバーとして起動（stdio・既定）
zapi-mcp --version  # バージョンを表示して終了
zapi-mcp --check    # 環境変数と認証を確認して終了
zapi-mcp --brief    # daily_brief を標準出力へ（cron 向き）
```

終了コード:

| コマンド | 0 | 1 | 2 |
|---|---|---|---|
| `--check` | 成功 | 設定エラー | 認証・接続エラー |
| `--brief` | 成功 | 環境変数の欠落、**または**いずれかのセクションの失敗 | — |

`--brief` が非ゼロを返すかどうかが「異常が無い」と「問い合わせられなかった」を
区別します。テキストだけでは区別がつきません。

!!! warning "標準出力の grep で失敗を判定しない"
    exit 1 には出力の見え方が異なる2ケースが含まれます。環境変数の欠落は
    **標準エラー**に出力され標準出力は空になる（ブリーフも `Error:` 行も無い）ため、
    探すべき文字列自体が存在しません。バックエンドの失敗ではブリーフは出ますが、
    埋め込まれる行は `Zabbix error: …` や `Missing environment variable: …` であり
    `Error:` で始まりません。標準出力の `Error:` だけを見る監視は両方取りこぼします。
    終了コードで判定してください。

## 打ち切られた件数の読み方

`daily_brief` と `get_problems` は取得上限（`ZABBIX_BRIEF_PROBLEM_LIMIT`・`limit`）に
達することがあります。その場合、見出しは `showing N of TOTAL` になります。`N` は
見えている数、`TOTAL` は存在する数です。比較するときは `TOTAL` 同士で比べてください。
`N` を前回の `TOTAL` と比べてはいけません。

## 塩漬けの問題

Zabbix は復旧が確認されるまで問題をアクティブなままにするため、とうに終わった
アラートがいつまでも一覧に残ります。`daily_brief` は直近ウィンドウより古い問題を
削除するのではなく1行に畳むので、溜まった件数は見える形で残りつつ、今日の事象と
注意を奪い合いません。数日不在だった後は `ZABBIX_BRIEF_RECENT_HOURS` を広げると
「直近」の範囲を伸ばせます。
