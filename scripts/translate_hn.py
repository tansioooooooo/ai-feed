#!/usr/bin/env python3
"""
Hacker News のタイトルを Claude で日本語に翻訳して feed.json に保存する。
ANTHROPIC_API_KEY 環境変数が必要。

使い方:
  python scripts/translate_hn.py
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
DAILY_DIR = ROOT / "docs" / "daily"


def translate_titles(titles: list[str]) -> list[str]:
    """Claude を使ってタイトルを日本語に一括翻訳する。"""
    import anthropic

    client = anthropic.Anthropic()

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = (
        "以下の英語のタイトルを自然な日本語に翻訳してください。"
        "固有名詞（モデル名・企業名・製品名）はそのまま英語で残してください。\n"
        "番号付きリストの形式で、翻訳結果のみを返してください。余分な説明は不要です。\n\n"
        + numbered
    )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    translated = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^\d+\.\s*", "", line).strip()
        if cleaned:
            translated.append(cleaned)

    return translated


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set, skipping translation")
        return

    if not FEED_PATH.exists():
        print(f"feed.json not found: {FEED_PATH}")
        return

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)

    hn_items = feed.get("hackernews", [])

    # 未翻訳のアイテムだけ翻訳
    to_translate = [
        (i, item) for i, item in enumerate(hn_items) if not item.get("title_ja")
    ]

    if not to_translate:
        print("All HN titles already translated")
        return

    print(f"Translating {len(to_translate)} HN titles...")
    titles = [item["title"] for _, item in to_translate]

    try:
        translated = translate_titles(titles)
    except Exception as e:
        print(f"Translation failed: {e}")
        return

    # 件数が合わない場合はパディング
    while len(translated) < len(to_translate):
        translated.append("")
    translated = translated[: len(to_translate)]

    for (idx, _), ja_title in zip(to_translate, translated):
        if ja_title:
            feed["hackernews"][idx]["title_ja"] = ja_title

    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print(f"Saved translations to {FEED_PATH}")

    # 今日の日付別ファイルにも反映
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_path = DAILY_DIR / f"{today}.json"
    if daily_path.exists():
        with open(daily_path, encoding="utf-8") as f:
            daily = json.load(f)
        # daily の HN アイテムにも title_ja をセット（URL で照合）
        ja_map = {
            item["url"]: item["title_ja"]
            for item in feed["hackernews"]
            if item.get("title_ja")
        }
        for item in daily.get("hackernews", []):
            if item["url"] in ja_map and not item.get("title_ja"):
                item["title_ja"] = ja_map[item["url"]]
        with open(daily_path, "w", encoding="utf-8") as f:
            json.dump(daily, f, ensure_ascii=False, indent=2)
        print(f"Updated daily file: {daily_path}")


if __name__ == "__main__":
    main()
