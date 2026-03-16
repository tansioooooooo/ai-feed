#!/usr/bin/env python3
"""
AI Feed Fetcher
- Hacker News API からAI関連記事を取得
- はてなブックマーク IT から取得
- RSSHub 経由で Twitter 特定アカウントを取得
結果を data/feed.json に保存
"""

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config.yml"
OUTPUT_PATH = ROOT / "docs" / "feed.json"
DAILY_DIR = ROOT / "docs" / "daily"

# 過去何日分の既出URLを重複チェック対象にするか
DEDUP_DAYS = 3


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────
# Hacker News
# ─────────────────────────────────────────────
# 具体的なモデル名・企業名・製品名で一次フィルタ
AI_KEYWORDS = [
    # モデル名
    "gpt-4", "gpt-5", "gpt4", "gpt5", "o1", "o3", "o4",
    "claude", "sonnet", "opus", "haiku",
    "gemini", "gemma",
    "llama", "mistral", "mixtral", "phi-4", "phi-3",
    "grok", "deepseek", "qwen", "command r",
    # 企業・研究機関
    "openai", "anthropic", "deepmind", "google ai", "meta ai", "xai",
    "hugging face", "huggingface", "stability ai", "cohere", "perplexity",
    # 製品・ツール
    "chatgpt", "copilot github", "github copilot", "cursor",
    "midjourney", "dall-e", "stable diffusion", "sora", "whisper",
    "claude code", "devin", "codex",
    # 技術用語（具体的なもの）
    "llm", "large language model", "language model",
    "foundation model", "generative ai", "gen ai",
    "fine-tuning", "fine tuning", "rlhf", "rag",
    "transformer", "diffusion model",
    "machine learning", "deep learning", "neural network",
    "artificial intelligence",
    "multimodal", "text-to-image", "text-to-video",
    "embedding", "vector database", "token", "context window",
    "inference", "training run", "gpu cluster",
    "reinforcement learning",
]

# 正規表現パターン: 単語境界付きで "AI" を検出（"MAIL" 等を除外）
_AI_WORD_RE = re.compile(r"\bAI\b")


def is_ai_related(text: str) -> bool:
    if _AI_WORD_RE.search(text):
        return True
    t = text.lower()
    return any(kw in t for kw in AI_KEYWORDS)


def fetch_hn(min_score: int = 50) -> list[dict]:
    print("Fetching Hacker News...")
    base = "https://hacker-news.firebaseio.com/v0"

    # topstories / beststories / newstories から幅広く収集
    all_ids: list[int] = []
    for endpoint in ["topstories", "beststories", "newstories"]:
        try:
            ids = requests.get(f"{base}/{endpoint}.json", timeout=10).json()
            all_ids.extend(ids[:200])
            print(f"  {endpoint}: {min(len(ids), 200)} fetched")
        except Exception as e:
            print(f"  {endpoint} fetch failed: {e}")

    # 重複IDを除去しつつ順序を維持
    seen_ids: set[int] = set()
    unique_ids: list[int] = []
    for item_id in all_ids:
        if item_id not in seen_ids:
            seen_ids.add(item_id)
            unique_ids.append(item_id)
    print(f"  Unique story IDs: {len(unique_ids)}")

    # newstories はスコアが低いので閾値を下げる
    items = []
    seen_urls: set[str] = set()
    for item_id in unique_ids:
        try:
            item = requests.get(f"{base}/item/{item_id}.json", timeout=5).json()
            if not item or item.get("type") != "story":
                continue
            if item.get("score", 0) < min_score:
                continue
            title = item.get("title", "")
            url = item.get("url", f"https://news.ycombinator.com/item?id={item_id}")
            if url in seen_urls:
                continue
            if is_ai_related(title):
                seen_urls.add(url)
                items.append({
                    "source": "hackernews",
                    "title": title,
                    "url": url,
                    "score": item.get("score", 0),
                    "comments": item.get("descendants", 0),
                    "hn_url": f"https://news.ycombinator.com/item?id={item_id}",
                    "published_at": datetime.fromtimestamp(
                        item.get("time", 0), tz=timezone.utc
                    ).isoformat(),
                })
        except Exception:
            continue
        time.sleep(0.05)

    print(f"  Found {len(items)} AI-related HN stories")
    return items


# ─────────────────────────────────────────────
# はてなブックマーク
# ─────────────────────────────────────────────
HATENA_SEARCH_KEYWORDS = [
    "AI", "LLM", "ChatGPT", "Claude", "生成AI", "機械学習",
    "OpenAI", "Anthropic", "Gemini", "大規模言語モデル",
]

# 記事の日付フィルタに使う上限日数
HATENA_MAX_AGE_DAYS = 3

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S GMT",
]


def _is_recent(date_str: str, max_days: int = HATENA_MAX_AGE_DAYS) -> bool:
    """日付文字列が直近 max_days 日以内なら True。パース失敗時は True（除外しない）。"""
    if not date_str:
        return True
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            return age.days <= max_days
        except ValueError:
            continue
    return True


def _parse_hatena_rss(content: bytes, require_ai_filter: bool) -> list[dict]:
    """はてなRSS（RDF/RSS1.0）をパースしてアイテムリストを返す。"""
    root = ET.fromstring(content)
    ns = {"rss": "http://purl.org/rss/1.0/",
          "dc": "http://purl.org/dc/elements/1.1/",
          "hatena": "http://www.hatena.ne.jp/info/xmlns#"}

    items = []
    for item in root.findall(".//rss:item", ns):
        title = item.findtext("rss:title", "", ns)
        link = item.findtext("rss:link", "", ns)
        desc = item.findtext("rss:description", "", ns)
        date = item.findtext("dc:date", "", ns)
        bookmarks_text = item.findtext("hatena:bookmarkcount", "0", ns)
        try:
            bookmarks = int(bookmarks_text)
        except ValueError:
            bookmarks = 0

        if require_ai_filter and not is_ai_related(title + " " + desc):
            continue

        items.append({
            "source": "hatena",
            "title": title,
            "url": link,
            "description": desc[:200] if desc else "",
            "bookmarks": bookmarks,
            "published_at": date,
        })
    return items


def _parse_hatena_atom(content: bytes) -> list[dict]:
    """はてなAtomフィード（検索結果）をパースしてアイテムリストを返す。"""
    root = ET.fromstring(content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    items = []
    for entry in root.findall(".//atom:entry", ns):
        title = entry.findtext("atom:title", "", ns)
        link_el = entry.find("atom:link", ns)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = entry.findtext("atom:summary", "", ns)
        published = entry.findtext("atom:published", "", ns)
        updated = entry.findtext("atom:updated", "", ns)

        items.append({
            "source": "hatena",
            "title": title,
            "url": link,
            "description": summary[:200] if summary else "",
            "bookmarks": 0,
            "published_at": published or updated or "",
        })
    return items


def fetch_hatena(feed_url: str, min_bookmarks: int = 20) -> list[dict]:
    print("Fetching Hatena Bookmark...")
    seen_urls: set[str] = set()
    all_items: list[dict] = []

    # 1. ホットエントリ（IT）— AI関連のみフィルタ（ホットエントリはブクマ閾値不要）
    try:
        resp = requests.get(feed_url, timeout=10)
        resp.raise_for_status()
        hotentry_items = _parse_hatena_rss(resp.content, require_ai_filter=True)
        for item in hotentry_items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
        print(f"  hotentry/it: {len(hotentry_items)} AI-related")
    except Exception as e:
        print(f"  hotentry/it fetch failed: {e}")

    # 2. キーワード検索RSS — 検索自体がAI絞りなのでフィルタ不要
    #    ブクマ数閾値でホットエントリ的な品質を担保
    for keyword in HATENA_SEARCH_KEYWORDS:
        search_url = (
            f"https://b.hatena.ne.jp/search/text?q={keyword}"
            f"&sort=recent&users={min_bookmarks}&mode=rss"
        )
        try:
            resp = requests.get(search_url, timeout=10)
            if resp.status_code != 200:
                continue
            # 検索結果はAtomかRSS1.0かレスポンスで異なる
            content_str = resp.content[:100].decode("utf-8", errors="ignore")
            if "<feed" in content_str:
                search_items = _parse_hatena_atom(resp.content)
            else:
                search_items = _parse_hatena_rss(
                    resp.content, require_ai_filter=False
                )
            new_count = 0
            for item in search_items:
                if item["url"] in seen_urls:
                    continue
                if not _is_recent(item.get("published_at", "")):
                    continue
                seen_urls.add(item["url"])
                all_items.append(item)
                new_count += 1
            if new_count:
                print(f"  search '{keyword}': +{new_count}")
        except Exception as e:
            print(f"  search '{keyword}' failed: {e}")
        time.sleep(0.3)

    print(f"  Total Hatena: {len(all_items)}")
    return all_items


# ─────────────────────────────────────────────
# Twitter via twikit (primary) / RSSHub (fallback)
# ─────────────────────────────────────────────
def _fetch_twitter_twikit(accounts: list[str]) -> list[dict]:
    """twikit の guest モジュールで認証不要のツイート取得を試みる。"""
    import asyncio

    try:
        from twikit.guest import GuestClient
    except ImportError:
        print("  twikit not installed, skipping")
        return []

    async def _fetch_all() -> list[dict]:
        client = GuestClient()
        await client.activate()
        all_items: list[dict] = []

        for account in accounts:
            try:
                user = await client.get_user_by_screen_name(account)
                tweets = await client.get_user_tweets(user.id)
                for tweet in list(tweets)[:10]:
                    text = getattr(tweet, "text", "") or ""
                    created = getattr(tweet, "created_at", "") or ""
                    tweet_id = getattr(tweet, "id", "")
                    url = f"https://x.com/{account}/status/{tweet_id}" if tweet_id else ""
                    all_items.append({
                        "source": "twitter",
                        "account": account,
                        "title": text[:100],
                        "url": url,
                        "description": text[:300],
                        "published_at": created,
                    })
                print(f"  @{account}: {min(len(list(tweets)), 10)} posts (twikit)")
            except Exception as e:
                print(f"  @{account}: twikit failed ({e})")
            await asyncio.sleep(0.5)

        return all_items

    return asyncio.run(_fetch_all())


def _fetch_twitter_rsshub(account: str, instances: list[str]) -> list[dict]:
    """RSSHub フォールバック: 1アカウント分のツイートを取得。"""
    for instance in instances:
        url = f"{instance}/twitter/user/{account}"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            channel = root.find("channel")
            if channel is None:
                continue

            items = []
            for item in channel.findall("item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                desc = item.findtext("description", "")
                clean_desc = re.sub(r"<[^>]+>", "", desc).strip()
                items.append({
                    "source": "twitter",
                    "account": account,
                    "title": title,
                    "url": link,
                    "description": clean_desc[:300] if clean_desc else title,
                    "published_at": pub_date,
                })
            return items[:10]
        except Exception:
            continue
    return []


def fetch_twitter(accounts: list[str], instances: list[str]) -> list[dict]:
    print("Fetching Twitter...")

    # twikit (guest) を最初に試す
    try:
        items = _fetch_twitter_twikit(accounts)
        if items:
            return items
    except Exception as e:
        print(f"  twikit failed: {e}")

    # twikit が使えなかった場合は RSSHub にフォールバック
    print("  Falling back to RSSHub...")
    all_items: list[dict] = []
    for account in accounts:
        account_items = _fetch_twitter_rsshub(account, instances)
        if account_items:
            print(f"  @{account}: {len(account_items)} posts (rsshub)")
        else:
            print(f"  @{account}: all methods failed, skipping")
        all_items.extend(account_items)
        time.sleep(0.5)
    return all_items


# ─────────────────────────────────────────────
# 日をまたいだ重複排除
# ─────────────────────────────────────────────
def load_recent_urls(days: int = DEDUP_DAYS) -> set[str]:
    """過去 N 日分の daily JSON から既出 URL を収集する。"""
    urls: set[str] = set()
    if not DAILY_DIR.exists():
        return urls

    today = datetime.now(timezone.utc).date()
    for daily_json in DAILY_DIR.glob("*.json"):
        try:
            file_date = datetime.strptime(daily_json.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        # 当日は除外（同日内の重複排除は別ロジック）
        if file_date >= today:
            continue
        if (today - file_date).days > days:
            continue
        try:
            with open(daily_json, encoding="utf-8") as f:
                data = json.load(f)
            for key in ["hackernews", "hatena", "twitter"]:
                for item in data.get(key, []):
                    if item.get("url"):
                        urls.add(item["url"])
        except Exception:
            continue

    return urls


def dedup_items(items: list[dict], seen_urls: set[str]) -> list[dict]:
    """既出 URL のアイテムを除外する。"""
    return [item for item in items if item.get("url") not in seen_urls]


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main():
    config = load_config()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    # 過去N日の既出URLを収集
    seen_urls = load_recent_urls()
    if seen_urls:
        print(f"Loaded {len(seen_urls)} URLs from past {DEDUP_DAYS} days for dedup")

    hn_items = fetch_hn(min_score=config.get("hn_min_score", 50))
    hatena_items = fetch_hatena(
        config["hatena_feed"],
        min_bookmarks=config.get("hatena_min_bookmarks", 20),
    )
    twitter_items = fetch_twitter(
        config["twitter_accounts"],
        config["rsshub_instances"]
    )

    # 日をまたいだ重複を除外
    hn_before, hatena_before = len(hn_items), len(hatena_items)
    hn_items = dedup_items(hn_items, seen_urls)
    hatena_items = dedup_items(hatena_items, seen_urls)
    twitter_items = dedup_items(twitter_items, seen_urls)
    if hn_before != len(hn_items) or hatena_before != len(hatena_items):
        print(f"Dedup: HN {hn_before}->{len(hn_items)}, "
              f"Hatena {hatena_before}->{len(hatena_items)}")

    now = datetime.now(timezone.utc)
    result = {
        "updated_at": now.isoformat(),
        "hackernews": hn_items,
        "hatena": hatena_items,
        "twitter": twitter_items,
    }

    # 最新の feed.json を保存（Claude フィルタ用）
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 日付別ファイルにも保存（履歴用）
    today = now.strftime("%Y-%m-%d")
    daily_path = DAILY_DIR / f"{today}.json"
    if daily_path.exists():
        # 同日2回目の実行: 既存データとマージ（URL で重複排除）
        with open(daily_path, encoding="utf-8") as f:
            existing = json.load(f)
        for key in ["hackernews", "hatena", "twitter"]:
            existing_urls = {item["url"] for item in existing.get(key, [])}
            for item in result.get(key, []):
                if item["url"] not in existing_urls:
                    existing[key].append(item)
        existing["updated_at"] = result["updated_at"]
        result = existing

    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_PATH} and {daily_path}")
    print(f"  HN: {len(hn_items)}, Hatena: {len(hatena_items)}, Twitter: {len(twitter_items)}")


if __name__ == "__main__":
    main()
