#!/usr/bin/env python3
"""
Claude の構造化出力（各ソースの ai_relevant 判定配列）を
feed.json にマージし、false の記事を除外して HTML を生成する。
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
DAILY_DIR = ROOT / "docs" / "daily"


def main() -> None:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print("No classification data provided, skipping AI filter")
        generate_html()
        return

    raw = sys.argv[1].strip()

    try:
        classification = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Warning: failed to parse classification JSON ({e}), skipping filter")
        generate_html()
        return

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)

    # hackernews: {relevant, title_ja} のオブジェクト配列
    hn_items = feed.get("hackernews", [])
    hn_flags = classification.get("hackernews", [])
    if hn_flags and len(hn_flags) == len(hn_items):
        original = len(hn_items)
        filtered = []
        for item, flag in zip(hn_items, hn_flags):
            if isinstance(flag, dict):
                if not flag.get("relevant", True):
                    continue
                if flag.get("title_ja"):
                    item["title_ja"] = flag["title_ja"]
            elif not flag:
                continue
            filtered.append(item)
        feed["hackernews"] = filtered
        print(f"  hackernews: {original} -> {len(filtered)}")
    else:
        print(f"  hackernews: length mismatch or empty, keeping all {len(hn_items)}")

    # hatena: boolean 配列
    for key in ["hatena"]:
        items = feed.get(key, [])
        flags = classification.get(key, [])
        if flags and len(flags) == len(items):
            original = len(items)
            feed[key] = [
                item for item, relevant in zip(items, flags) if relevant
            ]
            print(f"  {key}: {original} -> {len(feed[key])}")
        else:
            print(f"  {key}: length mismatch or empty, keeping all {len(items)}")

    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print("Filtered feed saved")

    # 日付別ファイルにもフィルタ結果を反映
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_path = DAILY_DIR / f"{today}.json"
    if daily_path.exists():
        with open(daily_path, "w", encoding="utf-8") as f:
            json.dump(feed, f, ensure_ascii=False, indent=2)
        print(f"Updated daily file: {daily_path}")

    generate_html()


def generate_html() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_html.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
