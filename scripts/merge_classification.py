#!/usr/bin/env python3
"""
Claude の構造化出力（HNタイトル翻訳）を feed.json にマージし、
キーワードマッチングでカテゴリを付与して HTML を生成する。
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
DAILY_DIR = ROOT / "docs" / "daily"

# ─────────────────────────────────────────────
# カテゴリ分類キーワード
# ─────────────────────────────────────────────
_AI_WORD_RE = re.compile(r"\bAI\b")

AI_KEYWORDS = [
    "llm", "gpt", "chatgpt", "claude", "gemini", "openai", "anthropic",
    "機械学習", "生成ai", "deep learning", "deeplearning", "neural network",
    "llama", "mistral", "copilot", "devin", "stable diffusion", "midjourney",
    "dall-e", "sora", "whisper", "transformer", "diffusion model",
    "rlhf", "rag", "fine-tuning", "finetuning", "embedding",
    "large language model", "foundation model", "generative ai",
    "multimodal", "text-to-image", "text-to-video", "huggingface",
    "deepseek", "qwen", "grok", "perplexity", "人工知能", "チャットgpt",
    "エージェント", "プロンプト", "o1", "o3", "o4",
]

POLITICS_KEYWORDS = [
    "政治", "選挙", "大臣", "首相", "議員", "政府", "国会", "自民", "立憲",
    "内閣", "外交", "安全保障", "防衛", "政策", "法律", "法案", "条例",
    "election", "congress", "senate", "parliament", "president", "minister",
    "government policy", "regulation",
]

NETA_KEYWORDS = [
    "笑い", "面白", "ネタ", "爆笑", "funny", "humor", "joke", "meme",
    "なんj", "2ch", "5ch",
]

COLUMN_KEYWORDS = [
    "コラム", "エッセイ", "振り返り", "感想", "体験談", "雑感",
    "を振り返る", "思ったこと", "考えたこと",
    "opinion", "essay", "my experience", "lessons learned", "reflection",
    "how i ", "why i ",
]


def categorize_item(item: dict) -> str:
    """キーワードマッチングでカテゴリを判定する。"""
    text = " ".join([
        item.get("title", ""),
        item.get("title_ja", ""),
        item.get("description", ""),
    ])
    text_lower = text.lower()

    if _AI_WORD_RE.search(text) or any(kw in text_lower for kw in AI_KEYWORDS):
        return "AI"
    if any(kw in text_lower for kw in POLITICS_KEYWORDS):
        return "政治"
    if any(kw in text_lower for kw in NETA_KEYWORDS):
        return "ネタ系"
    if any(kw in text_lower for kw in COLUMN_KEYWORDS):
        return "コラム"
    return "テクノロジー"


def apply_categories(feed: dict) -> None:
    """全アイテムにカテゴリを付与する。"""
    for key in ["hackernews", "hatena"]:
        for item in feed.get(key, []):
            item["category"] = categorize_item(item)

    category_counts: dict[str, int] = {}
    for key in ["hackernews", "hatena"]:
        for item in feed.get(key, []):
            cat = item["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
    print(f"  Categories: {category_counts}")


def save_feed(feed: dict) -> None:
    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print("Feed with categories saved")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_path = DAILY_DIR / f"{today}.json"
    if daily_path.exists():
        with open(daily_path, "w", encoding="utf-8") as f:
            json.dump(feed, f, ensure_ascii=False, indent=2)
        print(f"Updated daily file: {daily_path}")


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("No classification data provided, applying categories only")
        with open(FEED_PATH, encoding="utf-8") as f:
            feed = json.load(f)
        apply_categories(feed)
        save_feed(feed)
        generate_html()
        return

    raw = sys.argv[1].strip()

    try:
        classification = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Warning: failed to parse classification JSON ({e}), applying categories only")
        with open(FEED_PATH, encoding="utf-8") as f:
            feed = json.load(f)
        apply_categories(feed)
        save_feed(feed)
        generate_html()
        return

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)

    # hackernews: title_ja を適用（relevant は使わず全記事保持）
    hn_items = feed.get("hackernews", [])
    hn_flags = classification.get("hackernews", [])
    if hn_flags and len(hn_flags) == len(hn_items):
        for item, flag in zip(hn_items, hn_flags):
            if isinstance(flag, dict) and flag.get("title_ja"):
                item["title_ja"] = flag["title_ja"]
        print(f"  hackernews: applied title_ja for {len(hn_items)} items")
    else:
        print(f"  hackernews: length mismatch or empty ({len(hn_flags)} vs {len(hn_items)}), skipping title_ja")

    # カテゴリを全アイテムに付与
    apply_categories(feed)
    save_feed(feed)
    generate_html()


def generate_html() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_html.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
