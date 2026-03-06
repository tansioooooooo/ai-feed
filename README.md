# AI Feed

Hacker News・はてなテクノロジー・Twitterの特定アカウントからAI関連情報を収集し、GitHub Pagesで閲覧できるダッシュボードです。

## セットアップ

### 1. リポジトリを作成

このリポジトリをGitHubにpushします。

```bash
git init
git add .
git commit -m "init"
gh repo create ai-feed --public --push
```

### 2. OAuthトークンを生成（Maxサブスクリプション）

ローカルでClaude Codeにログイン済みの状態で：

```bash
claude /install-github-app
```

対話式メニューで：
1. リポジトリを選択
2. **「Create a long-lived token with your Claude subscription」** を選択

生成されたトークンが自動的に GitHub Secrets の `CLAUDE_CODE_OAUTH_TOKEN` に設定されます。

### 3. GitHub Pages を有効化

リポジトリの Settings → Pages → Source を **Deploy from a branch** にして、branch を `main`、フォルダを `/docs` に設定。

### 4. 手動で初回実行

Actions タブから「Update AI Feed」を選んで「Run workflow」。

---

## Twitterについて

RSSHub のパブリックインスタンス経由でアカウントのツイートをRSS取得しています。
インスタンスが不安定な場合は `config.yml` の `rsshub_instances` を変更してください。

自前でRSSHubをホストする場合（より安定）:
```bash
docker run -d -p 1200:1200 diygod/rsshub
```
その場合は `config.yml` の rsshub_instances に `http://localhost:1200` を追加してください。

## 更新頻度

毎日 9:00 と 21:00 JST に自動更新（`config.yml` の cron を変更可能）。
Actions タブから手動実行も可能です。
