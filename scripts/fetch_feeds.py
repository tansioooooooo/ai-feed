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


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ─────────────────────────────────────────────
# Hacker News
# ─────────────────────────────────────────────
AI_KEYWORDS = [
    "llm", "gpt", "claude", "gemini", "openai", "anthropic", "deepmind",
    "artificial intelligence", "machine learning", "deep learning",
    "neural network", "transformer", "diffusion", "embedding", "rag",
    "fine.tun", "inference", "foundation model", "language model",
    "multimodal", "agent", "mistral", "llama", "copilot", "grok",
    "ai ", " ai,", " ai.", "generative", "chatbot", "stable diffusion",
    "midjourney", "sora", "dall-e", "whisper", "reinforcement learning",
]


def is_ai_related(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in AI_KEYWORDS)


def fetch_hn(min_score: int = 50) -> list[dict]:
    print("Fetching Hacker News...")
    base = "https://hacker-news.firebaseio.com/v0"
    try:
        top_ids = requests.get(f"{base}/topstories.json", timeout=10).json()[:200]
    except Exception as e:
        print(f"  HN fetch failed: {e}")
        return []

    items = []
    for item_id in top_ids:
        try:
            item = requests.get(f"{base}/item/{item_id}.json", timeout=5).json()
            if not item or item.get("type") != "story":
                continue
            if item.get("score", 0) < min_score:
                continue
            title = item.get("title", "")
            url = item.get("url", f"https://news.ycombinator.com/item?id={item_id}")
            if is_ai_related(title):
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
def fetch_hatena(feed_url: str) -> list[dict]:
    print("Fetching Hatena Bookmark...")
    try:
        resp = requests.get(feed_url, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Hatena fetch failed: {e}")
        return []

    root = ET.fromstring(resp.content)
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

        if is_ai_related(title + " " + desc):
            items.append({
                "source": "hatena",
                "title": title,
                "url": link,
                "description": desc[:200] if desc else "",
                "bookmarks": bookmarks,
                "published_at": date,
            })

    print(f"  Found {len(items)} AI-related Hatena stories")
    return items


# ─────────────────────────────────────────────
# Twitter via RSSHub
# ─────────────────────────────────────────────
def fetch_twitter_account(account: str, instances: list[str]) -> list[dict]:
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
                # HTMLタグ除去
                clean_desc = re.sub(r"<[^>]+>", "", desc).strip()

                items.append({
                    "source": "twitter",
                    "account": account,
                    "title": title,
                    "url": link,
                    "description": clean_desc[:300] if clean_desc else title,
                    "published_at": pub_date,
                })
            return items[:10]  # 各アカウント最新10件
        except Exception:
            continue
    print(f"  @{account}: all instances failed, skipping")
    return []


def fetch_twitter(accounts: list[str], instances: list[str]) -> list[dict]:
    print("Fetching Twitter via RSSHub...")
    all_items = []
    for account in accounts:
        items = fetch_twitter_account(account, instances)
        print(f"  @{account}: {len(items)} posts")
        all_items.extend(items)
        time.sleep(0.5)
    return all_items


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main():
    config = load_config()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    hn_items = fetch_hn(min_score=config.get("hn_min_score", 50))
    hatena_items = fetch_hatena(config["hatena_feed"])
    twitter_items = fetch_twitter(
        config["twitter_accounts"],
        config["rsshub_instances"]
    )

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "hackernews": hn_items,
        "hatena": hatena_items,
        "twitter": twitter_items,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_PATH}")
    print(f"  HN: {len(hn_items)}, Hatena: {len(hatena_items)}, Twitter: {len(twitter_items)}")


if __name__ == "__main__":
    main()
