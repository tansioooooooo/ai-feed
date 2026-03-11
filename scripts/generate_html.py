#!/usr/bin/env python3
"""
feed.json + daily/*.json から静的 HTML ダッシュボードを生成
- docs/index.html: 最新フィード（タブ切り替え）+ 日付アーカイブリンク
- docs/daily/YYYY-MM-DD.html: 日付別ページ
"""

import json
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"
OUTPUT_PATH = ROOT / "docs" / "index.html"

SOURCE_LABELS = {
    "hackernews": "HN",
    "hatena": "Hatena",
    "twitter": "Twitter",
}

SOURCE_COLORS = {
    "hackernews": "#ff6600",
    "hatena": "#008fde",
    "twitter": "#1d9bf0",
}

CSS = """\
:root {
  --bg: #0f0f13;
  --surface: #1a1a22;
  --border: #2a2a38;
  --text: #e8e8f0;
  --muted: #7a7a9a;
  --accent: #7c6af7;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.6;
}
header {
  padding: 20px 24px 0;
  border-bottom: 1px solid var(--border);
}
.header-top {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}
h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
h1 a { color: var(--text); text-decoration: none; }
h1 a:hover { color: var(--accent); }
.subtitle { font-size: 14px; color: var(--muted); }
.updated { font-size: 12px; color: var(--muted); }
.tabs { display: flex; gap: 0; }
.tab {
  padding: 8px 18px;
  cursor: pointer;
  border: none;
  background: none;
  color: var(--muted);
  font-size: 13px;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--text); border-bottom-color: var(--accent); }
.count {
  display: inline-block;
  background: var(--border);
  border-radius: 10px;
  padding: 1px 7px;
  font-size: 11px;
  margin-left: 5px;
}
main { padding: 16px 24px; max-width: 900px; }
.panel { display: none; }
.panel.active { display: block; }
.cards { display: flex; flex-direction: column; gap: 10px; }
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  transition: border-color 0.15s;
}
.card:hover { border-color: var(--accent); }
.card-source {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 5px;
}
.card-title {
  display: block;
  color: var(--text);
  text-decoration: none;
  font-weight: 500;
  font-size: 14px;
  margin-bottom: 5px;
  line-height: 1.4;
}
.card-title:hover { color: var(--accent); }
.card-desc {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-meta {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.account { color: #1d9bf0; }
.score { color: var(--muted); }
.comment-link {
  color: var(--accent);
  text-decoration: none;
  font-size: 11px;
}
.comment-link:hover { text-decoration: underline; }
.empty { color: var(--muted); padding: 20px 0; }
.archive-section { margin-top: 24px; }
.archive-section h2 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--muted);
}
.archive-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.archive-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  color: var(--text);
  text-decoration: none;
  font-size: 14px;
  transition: border-color 0.15s;
}
.archive-link:hover { border-color: var(--accent); color: var(--accent); }
.archive-count { color: var(--muted); font-size: 12px; }
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 12px;
}
.back-link:hover { text-decoration: underline; }
@media (max-width: 600px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .tab { padding: 8px 12px; font-size: 12px; }
}"""

TAB_JS = """\
function switchTab(id, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('panel-' + id).classList.add('active');
}"""


def format_date(date_str: str) -> str:
    if not date_str:
        return ""
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%m/%d %H:%M")
        except ValueError:
            continue
    return date_str[:16] if len(date_str) > 16 else date_str


def card_html(item: dict) -> str:
    source = item.get("source", "")
    color = SOURCE_COLORS.get(source, "#888")
    label = SOURCE_LABELS.get(source, source)
    title = escape(item.get("title", ""))
    title_ja = escape(item.get("title_ja", ""))
    url = escape(item.get("url", "#"))
    desc = escape(item.get("description", ""))
    date = format_date(item.get("published_at", ""))
    account = escape(item.get("account", ""))
    score = item.get("score", "")
    bookmarks = item.get("bookmarks", "")
    hn_url = escape(item.get("hn_url", ""))

    meta_parts = []
    if date:
        meta_parts.append(f'<span class="date">{date}</span>')
    if account:
        meta_parts.append(f'<span class="account">@{account}</span>')
    if score:
        meta_parts.append(f'<span class="score">&#9650; {score}</span>')
    if bookmarks:
        meta_parts.append(f'<span class="score">&#128278; {bookmarks}</span>')
    if hn_url:
        meta_parts.append(
            f'<a href="{hn_url}" target="_blank" class="comment-link">'
            f"comments &rarr;</a>"
        )
    meta_html = " &middot; ".join(meta_parts)

    desc_html = ""
    if desc and desc != title:
        desc_html = f'<p class="card-desc">{desc}</p>'

    if title_ja:
        title_html = (
            f'<a href="{url}" target="_blank" class="card-title">{title_ja}</a>'
            f'<span style="color:var(--muted);font-size:11px;display:block;margin-bottom:4px">{title}</span>'
        )
    else:
        title_html = f'<a href="{url}" target="_blank" class="card-title">{title}</a>'

    return (
        f'<div class="card" data-source="{source}">'
        f'<div class="card-source" style="color:{color}">{label}</div>'
        f"{title_html}"
        f"{desc_html}"
        f'<div class="card-meta">{meta_html}</div>'
        f"</div>"
    )


def render_cards(items: list[dict]) -> str:
    if not items:
        return '<p class="empty">No articles</p>'
    return "\n".join(card_html(i) for i in items)


def format_updated(updated_at: str) -> str:
    try:
        dt = datetime.fromisoformat(updated_at)
        return dt.strftime("%Y/%m/%d %H:%M UTC")
    except Exception:
        return updated_at


def load_daily_dates() -> list[tuple[str, int]]:
    """Return list of (date_str, item_count) sorted newest first."""
    if not DAILY_DIR.exists():
        return []
    dates = []
    for f in sorted(DAILY_DIR.glob("*.json"), reverse=True):
        date_str = f.stem
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            count = sum(
                len(data.get(k, []))
                for k in ["hackernews", "hatena", "twitter"]
            )
            dates.append((date_str, count))
        except Exception:
            continue
    return dates


def load_trend_reports() -> dict[str, list[str]]:
    """Return {'weekly': [...filenames...], 'monthly': [...filenames...]} sorted newest first."""
    result: dict[str, list[str]] = {"weekly": [], "monthly": []}
    for key, dir_path in [("weekly", WEEKLY_DIR), ("monthly", MONTHLY_DIR)]:
        if dir_path.exists():
            result[key] = sorted(
                [f.stem for f in dir_path.glob("*.html")],
                reverse=True,
            )
    return result


def generate_index_html(feed: dict, daily_dates: list[tuple[str, int]], trend_reports: dict | None = None) -> str:
    updated_str = format_updated(feed.get("updated_at", ""))
    hn_items = feed.get("hackernews", [])
    hatena_items = feed.get("hatena", [])
    twitter_items = feed.get("twitter", [])
    all_items = hn_items + hatena_items + twitter_items

    archive_html = ""
    if daily_dates:
        links = "\n".join(
            f'<a href="daily/{d}.html" class="archive-link">'
            f"<span>{d}</span>"
            f'<span class="archive-count">{c} articles</span></a>'
            for d, c in daily_dates
        )
        archive_html = (
            f'<div class="archive-section">'
            f"<h2>Archive</h2>"
            f'<div class="archive-list">{links}</div>'
            f"</div>"
        )

    trend_html = ""
    if trend_reports:
        weekly_links = "\n".join(
            f'<a href="weekly/{name}.html" class="archive-link">'
            f"<span>&#128202; {name}</span>"
            f'<span class="archive-count">週次レポート</span></a>'
            for name in trend_reports.get("weekly", [])[:8]
        )
        monthly_links = "\n".join(
            f'<a href="monthly/{name}.html" class="archive-link">'
            f"<span>&#128197; {name}</span>"
            f'<span class="archive-count">月次レポート</span></a>'
            for name in trend_reports.get("monthly", [])[:6]
        )
        if weekly_links or monthly_links:
            combined = "\n".join(filter(None, [monthly_links, weekly_links]))
            trend_html = (
                f'<div class="archive-section">'
                f"<h2>Trend Reports</h2>"
                f'<div class="archive-list">{combined}</div>'
                f"</div>"
            )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1>AI Feed</h1>
    <span class="updated">{updated_str}</span>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('all', this)">
      All <span class="count">{len(all_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hn', this)">
      HN <span class="count">{len(hn_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hatena', this)">
      Hatena <span class="count">{len(hatena_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('twitter', this)">
      Twitter <span class="count">{len(twitter_items)}</span>
    </button>
  </div>
</header>
<main>
  <div id="panel-all" class="panel active">
    <div class="cards">{render_cards(all_items)}</div>
  </div>
  <div id="panel-hn" class="panel">
    <div class="cards">{render_cards(hn_items)}</div>
  </div>
  <div id="panel-hatena" class="panel">
    <div class="cards">{render_cards(hatena_items)}</div>
  </div>
  <div id="panel-twitter" class="panel">
    <div class="cards">{render_cards(twitter_items)}</div>
  </div>
  {trend_html}
  {archive_html}
</main>
<script>{TAB_JS}</script>
</body>
</html>"""


def generate_daily_html(date_str: str, feed: dict) -> str:
    updated_str = format_updated(feed.get("updated_at", ""))
    hn_items = feed.get("hackernews", [])
    hatena_items = feed.get("hatena", [])
    twitter_items = feed.get("twitter", [])
    all_items = hn_items + hatena_items + twitter_items

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../index.html">AI Feed</a></h1>
    <span class="subtitle">{date_str}</span>
    <span class="updated">{updated_str}</span>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('all', this)">
      All <span class="count">{len(all_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hn', this)">
      HN <span class="count">{len(hn_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hatena', this)">
      Hatena <span class="count">{len(hatena_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('twitter', this)">
      Twitter <span class="count">{len(twitter_items)}</span>
    </button>
  </div>
</header>
<main>
  <a href="../index.html" class="back-link">&larr; Latest</a>
  <div id="panel-all" class="panel active">
    <div class="cards">{render_cards(all_items)}</div>
  </div>
  <div id="panel-hn" class="panel">
    <div class="cards">{render_cards(hn_items)}</div>
  </div>
  <div id="panel-hatena" class="panel">
    <div class="cards">{render_cards(hatena_items)}</div>
  </div>
  <div id="panel-twitter" class="panel">
    <div class="cards">{render_cards(twitter_items)}</div>
  </div>
</main>
<script>{TAB_JS}</script>
</body>
</html>"""


def main() -> None:
    if not FEED_PATH.exists():
        print(f"feed.json not found at {FEED_PATH}")
        return

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)

    # Generate daily HTML pages
    if DAILY_DIR.exists():
        for daily_json in DAILY_DIR.glob("*.json"):
            date_str = daily_json.stem
            with open(daily_json, encoding="utf-8") as f:
                daily_feed = json.load(f)
            daily_html_path = DAILY_DIR / f"{date_str}.html"
            with open(daily_html_path, "w", encoding="utf-8") as f:
                f.write(generate_daily_html(date_str, daily_feed))
            print(f"  Generated {daily_html_path}")

    # Generate index.html with archive links
    daily_dates = load_daily_dates()
    trend_reports = load_trend_reports()
    html = generate_index_html(feed, daily_dates, trend_reports)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
