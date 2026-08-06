# リファレンス

## ツール

### `health_check()`

どの経路でも同じキー構成を返すので、呼び出し側がキーの有無で分岐する必要がありません。

| キー | 意味 |
|---|---|
| `status` | `healthy` / `degraded` / `error` |
| `service` | 常に `zapi-mcp` |
| `version` | パッケージのバージョン |
| `zabbix_url` | 設定された URL（未設定なら空文字列） |
| `zabbix_api_version` | 検出した API バージョン。接続に成功するまでは `null` |
| `auth` | `ok` / `error` / `missing-env` |
| `categories` | 読み込まれた `daily_brief` カテゴリ名 |
| `detail` | degraded / error のときに理由が入る |
| `categories_error` | カテゴリファイルの解析に失敗したときに入る |

意図的に軽量です。認証を1回行い（キャッシュ済みセッションを再利用）、API バージョンを
読むだけで、問題やアイテムの走査はしません。セッション開始時やツール呼び出しの
タイムアウト後に安心して呼べます。

### `daily_brief()`

朝のレポートです。構造:

```text
# Daily Brief — 2026-08-06 09:00

## Active Problems (showing 50 of 97)
### High
  [High] Unavailable by ICMP ping  eventid=...  (2026-08-06 07:12, 2h ago)
  … and 14 older (stale; oldest 2024-10-04)

## DHCP Pool Usage
  100.0%  POOL-A   usage
   82.3%  POOL-B   usage
```

問題は Warning 以上を新しい順に、経過時間つきで並べます。`ZABBIX_BRIEF_RECENT_HOURS`
より古いものは `… and N older` の行に畳まれます。続いて、設定した `[section]` ごとに
カテゴリのセクションが並びます。

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

**唯一の書き込みツールです。** カンマ区切りのイベント ID を acknowledge し、
メッセージを添付します。問題のクローズはしません。acknowledge はその Zabbix の
全オペレーターに見え、黙って取り消すことができません。だからライブスモークテストは
このツールを名指しでスキップし、そのスキップをユニットテストが強制しています。

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
| `--brief` | 成功 | いずれかのセクションが失敗（出力中の `Error:` 行を参照） | — |

`--brief` が非ゼロを返すかどうかが「異常が無い」と「問い合わせられなかった」を
区別します。テキストだけでは区別がつきません。

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
