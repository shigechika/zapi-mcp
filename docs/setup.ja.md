# セットアップ

## インストール

```bash
uv pip install zapi-mcp
# または
pip install zapi-mcp
```

ソースから:

```bash
git clone https://github.com/shigechika/zapi-mcp.git
cd zapi-mcp
uv sync          # または: pip install -e .
```

## Zabbix アカウント

API ユーザーには**照会対象のホストグループへの読み取り権限**が必要です。
`acknowledge_problem` を使う場合は acknowledge 権限も、`set_maintenance` を
使う場合はメンテナンス書き込み権限も要ります。それ以外は不要で、スーパー
管理者ロールも他の書き込み権限も必要ありません。

どちらかの権限を付けなければ、そのツールだけが Zabbix API 呼び出しで失敗し、
残りのツールはそのまま動きます ― 各ツールが実際に呼ぶ API は
[リファレンス](reference.ja.md)の `acknowledge_problem` / `set_maintenance`
の項を参照してください。

個人のアカウントを流用せず API 専用ユーザーを作ると、監査ログが読みやすくなり、
その人が異動・退職しても動き続けます。

## 環境変数

| 変数 | 説明 | 既定 |
|---|---|---|
| `ZABBIX_URL` | Zabbix のベース URL（例 `https://zabbix.example.com`）。`/api_jsonrpc.php` は無ければ補われる | *必須* |
| `ZABBIX_USER` | Zabbix API ユーザー | *必須* |
| `ZABBIX_PASSWORD` | Zabbix API パスワード | *必須* |
| `ZABBIX_CATEGORIES_INI` | `daily_brief` 用カテゴリ INI のパス | — |
| `ZABBIX_BRIEF_RECENT_HOURS` | `daily_brief` の「直近」ウィンドウ（時間）。これより古い問題は件数に畳まれる | `24` |
| `ZABBIX_BRIEF_PROBLEM_LIMIT` | `daily_brief` が1回に取得するアクティブ問題の上限。超過分は件数として数える | `1000` |

!!! tip "何かに組み込む前に確認する"
    ```bash
    zapi-mcp --check
    ```
    exit `0` なら環境変数が揃っていて認証も成功しています。`1` は設定エラー、
    `2` は認証・接続エラーです。一度これを走らせておけば、「ツールが何も返さない」
    が既に答えの出ている問いになります。

## MCP クライアントへの登録

### Claude Code（プラグイン）

このリポジトリはプラグイン 1 個のマーケットプレイスも兼ねています。

```
/plugin marketplace add shigechika/zapi-mcp
/plugin install zapi-mcp@zapi-mcp
```

プラグインは `uvx zapi-mcp` を起動し、上記の環境変数と同じものを読みます。
Claude Code を起動する前に export しておいてください。

プラグインは `uvx` を起動するため、Claude Code を実行するプロセスの `PATH` に
`uvx` が通っている必要があります。ログインシェルなら通常問題ありませんが、
GUI から起動した場合は通っていないことがあります。プラグインが起動しない場合は
[uv](https://docs.astral.sh/uv/) をシステム全体にインストールしてください。

### Claude Code（手動）

`.mcp.json`:

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

`claude_desktop_config.json`:

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

## Zabbix のバージョン互換

認証はバージョンに追随します。クライアントが API バージョンを検出し、6.0 LTS には
`user` ＋ `auth` フィールド、6.4 / 7.0 には `username` ＋ `Authorization: Bearer`
を送ります。これを選ぶ設定項目はありません。Zabbix サーバーをアップグレードしても
こちら側の変更は不要です。

`health_check` は検出したバージョンを `zabbix_api_version` に返すので、サーバーが
実際に何で応答したかを確認する最短手段になります。

## 次に

朝のレポートにサイト固有のセクションを追加します:
[daily_brief のカテゴリ設定](categories.ja.md)。
