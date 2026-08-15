# zapi-mcp

[English](README.md) | 日本語

[Zabbix](https://www.zabbix.com/) API 用の MCP（Model Context Protocol）サーバ。

ネットワーク運用向け：`daily_brief` 一発でアクティブな問題に加え、拠点固有の
カテゴリ（DHCP プール使用率、SNAT セッション使用率、コアネットワークの問題
など）をまとめて要約する。個別ツールで問題・ホスト・アイテム値も取得できる。
組織固有のタグはコードではなく設定ファイルに置くため、サーバ本体は汎用的なまま。

バージョン適応認証：Zabbix 6.0 LTS（`user` ＋ `auth` フィールド）で動作し、
6.4 / 7.0（`username` ＋ `Authorization: Bearer`）にも前方互換。

ドキュメント: <https://shigechika.github.io/zapi-mcp/ja/>

## 機能

| ツール | 説明 |
|------|------|
| `health_check` | サーバーバージョン、Zabbix 接続/認証状況、検出された API バージョン、設定済みの `daily_brief` カテゴリ ― セッション開始時やタイムアウト後に呼ぶ |
| `daily_brief` | 朝のパトロール：アクティブな問題（Warning 以上）、現在メンテナンス中のホスト、＋設定済みカテゴリごとのセクション |
| `get_problems` | 重要度・タグでフィルタしたアクティブな問題を新しい順・経過時間付きで一覧（見出しに正確な総件数、上限超過時は `showing N of TOTAL`／出力に `eventid` を含む） |
| `get_hosts` | role/タグ/グループでフィルタしたホスト一覧（IP・タグ付き） |
| `get_host_items` | ホストのアイテム現在値（サーバ側でホスト絞り込み） |
| `acknowledge_problem` | 問題の acknowledge とメッセージ追加（クローズはしない） |
| `set_maintenance` | 冪等なZabbixメンテナンス期間を開く。`location` タグまたは個別ホスト名のどちらか一方で対象を指定 |
| `get_maintenance_windows` | メンテナンス期間の一覧（Active/Upcoming/Expired）― 他ツールのアラートを新規障害と誤認する前に突き合わせる |

## インストール

```bash
# uv
uv pip install zapi-mcp

# pip
pip install zapi-mcp
```

ソースから:

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp

# uv
uv sync

# pip
pip install -e .
```

## 設定

以下の環境変数を設定する:

| 変数 | 説明 | デフォルト |
|---|---|---|
| `ZABBIX_URL` | Zabbix ベース URL（例: `https://zabbix.example.com`）。`/api_jsonrpc.php` は自動付与 | *必須* |
| `ZABBIX_USER` | Zabbix API ユーザ | *必須* |
| `ZABBIX_PASSWORD` | Zabbix API パスワード | *必須* |
| `ZABBIX_CATEGORIES_INI` | `daily_brief` 用カテゴリ INI ファイルのパス（任意） | — |
| `ZABBIX_BRIEF_RECENT_HOURS` | `daily_brief` の「直近」窓（時間）。これより古い問題は件数に折りたたむ | `24` |
| `ZABBIX_BRIEF_PROBLEM_LIMIT` | `daily_brief` が 1 回の呼び出しで取得するアクティブ問題の上限（超過分は件数のみ集計） | `1000` |

API ユーザには照会するホストグループの参照権限が必要。`acknowledge_problem`
を使う場合は acknowledge 権限も、`set_maintenance` を使う場合はメンテナンス
書き込み権限も、`get_maintenance_windows` と `daily_brief` の「In Maintenance」
セクションを使う場合はメンテナンス参照権限（通常は既定で付与済み）も付与する。

### `daily_brief` のアクティブな問題

問題は重要度別にまとめ、**新しい順**に経過時間（例: `3h ago`）を併記して一覧する。
直近窓（`ZABBIX_BRIEF_RECENT_HOURS`、デフォルト 24h）より古い問題は
`… and N older (stale; oldest …)` の 1 行に折りたたむ。Zabbix では復旧が自動確認
されない死活系アラート（ICMP ping down、RDP down など）が年単位で残るため、
これらの化石が当日の異常を埋もれさせないようにするための措置。セクション見出しには
正確な総件数を表示し、取得が上限に達した場合は `showing N of TOTAL` と明示する
（サイレントな切り捨てをしない）。

### `daily_brief` のメンテナンス期間

Active Problems の直後に、`daily_brief` は現在有効なメンテナンス期間、および
本日これから始まるメンテナンス期間の対象ホストを一覧する。計画停止を他の
ツールが検知した異常と誤認しないための材料。該当が無ければ `## In
Maintenance` セクション自体を出さない（セクション無し＝メンテ無し）。明日以降
に始まる窓や期限切れの窓はここには出ない ― 全体を見るには `get_maintenance_windows`
（`include_expired=True` で期限切れも含む）を呼ぶこと。

### `daily_brief` のカテゴリ（任意）

`daily_brief` は常にアクティブな問題を一覧する。さらに拠点固有のセクション
（DHCP プール枯渇、SNAT セッション使用率、コアネットワークの問題）を追加する
には、`ZABBIX_CATEGORIES_INI` に INI ファイルのパスを設定する。各 `[section]`
が 1 カテゴリに対応する:

```ini
[dhcp]
name = DHCP Pool Usage
# カテゴリを識別する Zabbix ホストタグ
tag = dhcp-pool-usage
# このアイテムキー（完全一致）の現在値を報告
item_key = usage
# この値以上を強調表示
threshold = 80

[snat]
name = SNAT Session Pool
tag = snat-pool-usage
# 部分一致（pool.node0.usage などを拾う）
item_key_search = .usage
threshold = 80

[core]
name = Core Network
tag = role
# タグがこの値と一致するもの
tag_value = main
# アイテムキー無し → 代わりにアクティブな問題を報告
```

- `tag`（必須）: カテゴリを識別するホストタグ。`tag_value` 併用時はその値と
  一致するもの（Equal）、無い場合はタグを持つホスト全て（Exists）。
- `item_key` / `item_key_search`: どちらか指定すると現在値を降順で報告。
  `item_key` は完全一致、`item_key_search` は ID を埋め込んだキー（例 `.usage`
  が `pool.node0.usage` を拾う）向けの部分一致。どちらも無ければそのタグの
  アクティブな問題を報告。
- `threshold`: 任意。この値以上を強調表示。

[`categories.ini.example`](categories.ini.example) を参照。環境変数が未設定、
またはファイルが無い場合はアクティブな問題のみを報告する。

### 書き込みツール

状態を変えるのは次の2つだけ。ほかはすべて読み取り。

| ツール | Zabbix API |
|---|---|
| `acknowledge_problem` | `event.acknowledge` |
| `set_maintenance` | `maintenance.create` |

`acknowledge_problem` には API ユーザーの acknowledge 権限、`set_maintenance`
にはメンテナンス書き込み権限が要る。**どちらか一方を付けなければ、その
ツールだけが読み取り専用のまま**になる ― Zabbix API 呼び出しが失敗するだけで
残りのツールはそのまま動くので、Zabbix の設定を変える権限を一切与えずに
調査だけを Claude に任せられる。アラートの acknowledge やメンテナンス
ウィンドウの作成を Claude にやらせたい場合にだけ権限を付与すること。

## 使い方

### Claude Code（プラグイン）

このリポジトリはプラグイン 1 個のマーケットプレイスも兼ねているので、
Claude Code からそのまま導入できます。

```
/plugin marketplace add shigechika/zapi-mcp
/plugin install zapi-mcp@zapi-mcp
```

プラグインは `uvx zapi-mcp` を起動し、[設定](#設定)と同じ環境変数を読みます。
Claude Code を起動する前に export しておいてください。`ZABBIX_CATEGORIES_INI`
は未設定のままで構いません。

プラグインは `uvx` を起動するため、Claude Code を実行するプロセスの `PATH` に
`uvx` が通っている必要があります。ログインシェルなら通常問題ありませんが、
GUI から起動した場合は通っていないことがあります。プラグインが起動しない場合は
[uv](https://docs.astral.sh/uv/) をシステム全体にインストールしてください。

### Claude Code（手動）

`.mcp.json` に追加:

```json
{
  "mcpServers": {
    "zapi-mcp": {
      "type": "stdio",
      "command": "zapi-mcp",
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_USER": "api-user",
        "ZABBIX_PASSWORD": "",
        "ZABBIX_CATEGORIES_INI": "/path/to/categories.ini"
      }
    }
  }
}
```

### Claude Desktop

`claude_desktop_config.json` に追加:

```json
{
  "mcpServers": {
    "zapi-mcp": {
      "command": "zapi-mcp",
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_USER": "api-user",
        "ZABBIX_PASSWORD": ""
      }
    }
  }
}
```

### 直接実行

```bash
export ZABBIX_URL=https://zabbix.example.com
export ZABBIX_USER=api-user
export ZABBIX_PASSWORD=your-password
zapi-mcp
```

### CLI オプション

```bash
zapi-mcp --version   # バージョン表示して終了
zapi-mcp --check     # 環境変数と認証を検証して終了
zapi-mcp --brief     # daily_brief を標準出力して終了（cron 向け）
zapi-mcp             # MCP サーバ起動（STDIO、デフォルト）
```

`--check` の終了コード: `0` 成功、`1` 設定エラー、`2` 認証/接続エラー。

`--brief` の終了コード: `0` 成功、`1` いずれかのセクションが失敗（認証、アクティブ
問題の取得、カテゴリ読み込みのいずれか — 出力中の `Error:` 行で詳細を確認）。

## 開発

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp

# uv
uv sync --dev
uv run pytest -v
uv run ruff check .

# pip
python3 -m venv .venv
.venv/bin/pip install -e . && .venv/bin/pip install pytest pytest-cov respx ruff
.venv/bin/pytest -v
.venv/bin/ruff check .
```

### ライブスモークテスト

`pytest` はフィクスチャに対してロジックを検証するだけで、ツールが実データを
返さなくなったことは検出できない。`scripts/smoke_test.py` は設定済みの Zabbix に対して
**登録されている全ツール**を実行し、空・不正・エラー応答を失敗として報告する。

```bash
# サーバーと同じ ZABBIX_* 環境変数が必要
uv run python scripts/smoke_test.py
uv run python scripts/smoke_test.py --only get_problems --traceback
```

- **読み取り専用**。`acknowledge_problem` と `set_maintenance` は名前で除外する
  （承認は全オペレーターから見えてしまいこっそり取り消せない、`set_maintenance` は
  実際にアラートを抑制するメンテナンス期間を開いてしまう）。除外はテストで強制している。レポートに出るのは
  ツール名とステータスだけでペイロードは出さない。Zabbix のエラー文言は問い合わせた
  ホスト名を含むため、これも伏字にする（`--traceback` を付ければ実行者の端末には全文が出る）。
- 実在のホスト・ホストグループ・タグ値を特定しうる引数は**実行時に発見**し、
  `scripts/smoke_probes.py` には書かない。これは2本のテストで強制している。
  ひとつは該当パラメータを直値で書くこと自体を拒否し、もうひとつはアドレス的な
  形（メールアドレス・URL・ホスト名・IPv4・IPv6）がファイル内に現れることを禁じる。
- ここでは応答が空であること自体が正常な観測結果（何も問題が起きていない監視システムが
  望ましい状態）なので、probe は件数ではなくツールが返すべき体裁（envelope）を表明する。
- CI では安価な半分を強制する。probe spec の無いツールを登録するとビルドが失敗するので
  （`tests/test_smoke_probes.py`）、ツール追加時に「どうやって動作を確認するか」を必ず決めることになる。
- `scripts/smoke_harness.py` はエンジンであり Zabbix 固有の知識を持たない。このハーネスを
  共有する各サーバーで同一に保つ方針なので、エンジンのバグはこの写しを直すのではなく
  一度直して全体に同期する。

## リリース

リリースは [release-please](https://github.com/googleapis/release-please) で自動化している。
[Conventional Commits](https://www.conventionalcommits.org/)（`feat:`、`fix:` など）を
`main` にマージすると、次バージョンと変更履歴を載せたリリース PR が常に開いた状態になる。
その PR をマージすると `vX.Y.Z` タグと GitHub Release が作成され、その
`release: published` イベントで `release` ワークフローが発火して PyPI と MCP Registry へ
publish する。`zapi_mcp/__init__.py` と `server.json` のバージョンは release-please が
管理するため、手動では更新しない。

> [!IMPORTANT]
> release-please ワークフローにはリポジトリシークレット `RELEASE_PLEASE_TOKEN`
> （`contents: write` ＋ `pull-requests: write` 権限の PAT）を設定する。既定の
> `GITHUB_TOKEN` が作成した Release は downstream の `release` ワークフローを発火
> できない（GitHub の再帰防止仕様）ため、PAT が無いと publish されない。シークレット
> 未設定時は `GITHUB_TOKEN` にフォールバックするので、フォークでの PR CI は動く。

## ロードマップ

- Streamable HTTP トランスポート ＋ OAuth2（リモート/モバイル利用）
- 主要メトリクスのビジュアル表示

## ライセンス

MIT