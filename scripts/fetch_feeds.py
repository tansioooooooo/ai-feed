#!/usr/bin/env python3
"""
Feed Fetcher
- Hacker News API から記事を取得
- はてなブックマーク IT から取得
結果を docs/feed.json に保存
"""

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
import trafilatura
import yaml

# trafilatura のタイムアウトを10秒に制限
trafilatura.settings.DEFAULT_CONFIG.set('DEFAULT', 'download_timeout', '10')

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
def fetch_hn(min_score: int = 100, max_items: int = 50) -> list[dict]:
    print(f"Fetching Hacker News (min_score={min_score}, max_items={max_items})...")
    base = "https://hacker-news.firebaseio.com/v0"

    # topstories / beststories から収集（newstories は低スコアが多いため除外）
    all_ids: list[int] = []
    for endpoint in ["topstories", "beststories"]:
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

    # スコア順でソートし、上限を適用
    items.sort(key=lambda x: x["score"], reverse=True)
    if len(items) > max_items:
        print(f"  Trimmed from {len(items)} to {max_items} items")
        items = items[:max_items]

    print(f"  Found {len(items)} HN stories")
    return items


# ─────────────────────────────────────────────
# はてなブックマーク
# ─────────────────────────────────────────────

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


def _fetch_bookmark_counts(urls: list[str]) -> dict[str, int]:
    """はてなブックマーク件数取得APIでブクマ数を一括取得（最大50件ずつ）。"""
    counts: dict[str, int] = {}
    batch_size = 50
    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        params = [("url", u) for u in batch]
        try:
            resp = requests.get(
                "https://bookmark.hatenaapis.com/count/entries",
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                counts.update(resp.json())
        except Exception as e:
            print(f"  bookmark count API failed: {e}")
        time.sleep(0.3)
    return counts


def fetch_hatena(feed_url: str, min_bookmarks: int = 20) -> list[dict]:
    print("Fetching Hatena Bookmark...")
    seen_urls: set[str] = set()
    all_items: list[dict] = []

    # ホットエントリ（IT）— フィルタなし全記事取得
    try:
        resp = requests.get(feed_url, timeout=10)
        resp.raise_for_status()
        hotentry_items = _parse_hatena_rss(resp.content, require_ai_filter=False)
        for item in hotentry_items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_items.append(item)
        print(f"  hotentry/it: {len(hotentry_items)} items")
    except Exception as e:
        print(f"  hotentry/it fetch failed: {e}")

    # ブクマ数が0のアイテムをAPIで補完
    urls_need_count = [
        item["url"] for item in all_items if not item.get("bookmarks")
    ]
    if urls_need_count:
        print(f"  Fetching bookmark counts for {len(urls_need_count)} items...")
        counts = _fetch_bookmark_counts(urls_need_count)
        for item in all_items:
            if not item.get("bookmarks") and item["url"] in counts:
                item["bookmarks"] = counts[item["url"]]

    print(f"  Total Hatena: {len(all_items)}")
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
            for key in ["hackernews", "hatena"]:
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
# フルテキスト取得
# ─────────────────────────────────────────────
FULLTEXT_MAX_CHARS = 5000
FULLTEXT_MAX_ITEMS = 20


def fetch_fulltext(url: str) -> str:
    """記事URLからフルテキストを取得する。失敗時は空文字を返す。"""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if not text:
            return ""
        # 文字数制限
        return text[:FULLTEXT_MAX_CHARS]
    except Exception as e:
        print(f"  fulltext fetch failed for {url}: {e}")
        return ""


def enrich_fulltext(feed: dict) -> None:
    """スコア/ブクマ数上位の記事にフルテキストを付与する。"""
    # HN: score上位20件
    hn_items = feed.get("hackernews", [])
    hn_targets = sorted(hn_items, key=lambda x: x.get("score", 0), reverse=True)[:FULLTEXT_MAX_ITEMS]
    hn_target_urls = {item["url"] for item in hn_targets}

    # はてな: bookmarks上位20件
    hatena_items = feed.get("hatena", [])
    hatena_targets = sorted(hatena_items, key=lambda x: x.get("bookmarks", 0), reverse=True)[:FULLTEXT_MAX_ITEMS]
    hatena_target_urls = {item["url"] for item in hatena_targets}

    target_urls = hn_target_urls | hatena_target_urls
    print(f"Fetching fulltext for {len(target_urls)} articles...")

    fetched = 0
    for items in [hn_items, hatena_items]:
        for item in items:
            if item["url"] in target_urls:
                text = fetch_fulltext(item["url"])
                item["full_text"] = text
                if text:
                    fetched += 1
            else:
                item["full_text"] = ""

    print(f"  Fulltext fetched: {fetched}/{len(target_urls)} articles")


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

    hn_items = fetch_hn(
        min_score=config.get("hn_min_score", 100),
        max_items=config.get("hn_max_items", 50),
    )
    hatena_items = fetch_hatena(
        config["hatena_feed"],
        min_bookmarks=config.get("hatena_min_bookmarks", 20),
    )

    # 日をまたいだ重複を除外
    hn_before, hatena_before = len(hn_items), len(hatena_items)
    hn_items = dedup_items(hn_items, seen_urls)
    hatena_items = dedup_items(hatena_items, seen_urls)
    if hn_before != len(hn_items) or hatena_before != len(hatena_items):
        print(f"Dedup: HN {hn_before}->{len(hn_items)}, "
              f"Hatena {hatena_before}->{len(hatena_items)}")

    # スコア/ブクマ数上位の記事にフルテキストを付与
    pre_enrich_feed = {"hackernews": hn_items, "hatena": hatena_items}
    enrich_fulltext(pre_enrich_feed)

    now = datetime.now(timezone.utc)
    result = {
        "updated_at": now.isoformat(),
        "hackernews": hn_items,
        "hatena": hatena_items,
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
        for key in ["hackernews", "hatena"]:
            existing_urls = {item["url"] for item in existing.get(key, [])}
            for item in result.get(key, []):
                if item["url"] not in existing_urls:
                    existing.setdefault(key, []).append(item)
        existing["updated_at"] = result["updated_at"]
        result = existing

    with open(daily_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {OUTPUT_PATH} and {daily_path}")
    print(f"  HN: {len(hn_items)}, Hatena: {len(hatena_items)}")


if __name__ == "__main__":
    main()
