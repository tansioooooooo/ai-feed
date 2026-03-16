# AI Feed

AI関連ニュースを自動収集し、GitHub Pages で公開する静的ダッシュボード。

## アーキテクチャ

```
config.yml          # データソース設定（Twitter accounts, HN, Hatena）
scripts/
  fetch_feeds.py    # HN API / はてなRSS / Twitter(twikit→RSSHub) からフィード取得 → docs/feed.json
  merge_classification.py  # Claude分類結果をfeed.jsonにマージ＆フィルタ → HTML生成呼び出し
  generate_html.py  # feed.json → 静的HTML（docs/index.html, docs/daily/*.html）
docs/
  feed.json         # 最新フィード（生成物・gitコミット対象）
  index.html        # ダッシュボード（生成物）
  daily/            # 日付別アーカイブ（JSON + HTML、生成物）
.github/workflows/
  update.yml        # 定期実行パイプライン（fetch → Claude分類 → merge → commit）
  claude.yml        # Issue/PR で @claude メンション時の応答
  claude-code-review.yml  # PR自動レビュー
```

## パイプライン（update.yml）

1. `fetch_feeds.py` — 3ソースからフィード取得、`docs/feed.json` に保存
2. Claude Code Action（構造化出力）— AI関連性判定 + HNタイトル日本語翻訳
3. `merge_classification.py` — Claude出力をマージ、非AI記事を除外、HTML生成
4. `git commit && push` — docs/ を自動コミット

## 技術スタック

- **言語**: Python 3.12
- **依存**: requests, pyyaml, twikit（requirements.txt）
- **CI/CD**: GitHub Actions
- **ホスティング**: GitHub Pages（docs/ ディレクトリ）
- **AI**: Claude Code Action（anthropics/claude-code-action@v1）

## 開発ルール

### データソース

- **Hacker News**: Firebase API → キーワードフィルタ（`is_ai_related`）→ Claude で精密判定
- **はてなブックマーク**: IT ホットエントリ RSS → 同上
- **Twitter**: twikit (guest) を優先、失敗時 RSSHub フォールバック
- ソース追加時は `config.yml` と `fetch_feeds.py` の両方を更新

### フィード処理

- `feed.json` のスキーマ: `{updated_at, hackernews[], hatena[], twitter[]}`
- 各アイテム共通フィールド: `source`, `title`, `url`, `published_at`
- HN固有: `score`, `comments`, `hn_url`, `title_ja`（日本語翻訳）
- 日付別ファイルはURL重複排除でマージ（同日複数回実行対応）

### HTML生成

- `generate_html.py` は純粋なPythonテンプレート（外部テンプレートエンジン不使用）
- ダークテーマ、タブ切り替え（All/HN/Hatena/Twitter）
- CSS/JS はインライン埋め込み

### AI処理の方針

- **Anthropic API（`anthropic` SDK）を直接叩くコードを書かない**
- AI処理（分類・要約・翻訳等）が必要な場合は、既に利用可能な以下の手段を使う:
  - **CI上**: Claude Code Action（`anthropics/claude-code-action@v1`）— update.yml の構造化出力パターンを参照
  - **ローカル**: Claude Code CLI
- APIキーの管理やコスト発生を避けるため、`import anthropic` や `requests.post("https://api.anthropic.com/...")` のようなコードは書かない
- 新しいAI処理が必要な場合は、update.yml に Claude Code Action のステップを追加する形で対応する

### 変更時の注意

- `docs/` 配下は全て生成物。手動編集しない
- Claude分類の出力スキーマを変更する場合、`update.yml` の `--json-schema` と `merge_classification.py` の両方を同期
- Twitter取得は外部サービス依存で不安定。エラーハンドリングを省略しない
- `config.yml` の変更は `fetch_feeds.py` の `load_config()` 経由で反映される

## コマンド

```bash
# ローカルでフィード取得
python scripts/fetch_feeds.py

# HTML生成（feed.json が必要）
python scripts/generate_html.py

# 分類結果のマージ（通常はCI経由）
python scripts/merge_classification.py '<JSON>'
```
