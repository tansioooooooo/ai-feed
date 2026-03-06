#!/usr/bin/env python3
"""
Claude が付与した ai_relevant フラグでフィルタリングし、HTML を生成する。
JSON が壊れている場合はバックアップから復元して続行する。
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
BACKUP_PATH = ROOT / "docs" / "feed.backup.json"


def load_feed() -> dict:
    """feed.json を読み込む。パース失敗時はバックアップから復元。"""
    try:
        with open(FEED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Warning: feed.json is invalid ({e}), restoring from backup")
        if BACKUP_PATH.exists():
            with open(BACKUP_PATH, encoding="utf-8") as f:
                feed = json.load(f)
            with open(FEED_PATH, "w", encoding="utf-8") as f:
                json.dump(feed, f, ensure_ascii=False, indent=2)
            return feed
        print("Error: backup not found either")
        sys.exit(1)


def filter_feed(feed: dict) -> dict:
    """ai_relevant: false の記事を除外する。"""
    for key in ["hackernews", "hatena", "twitter"]:
        original_count = len(feed.get(key, []))
        feed[key] = [
            item for item in feed.get(key, [])
            if item.get("ai_relevant", True)
        ]
        filtered_count = len(feed[key])
        print(f"  {key}: {original_count} -> {filtered_count}")
    return feed


def main() -> None:
    feed = load_feed()
    feed = filter_feed(feed)

    with open(FEED_PATH, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
    print("Filtered feed saved")

    # Clean up backup
    if BACKUP_PATH.exists():
        BACKUP_PATH.unlink()

    # Generate HTML
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_html.py")],
        check=True,
    )


if __name__ == "__main__":
    main()
