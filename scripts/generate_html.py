#!/usr/bin/env python3
"""
feed.json から静的 HTML ダッシュボードを生成
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "docs" / "feed.json"
OUTPUT_PATH = ROOT / "docs" / "index.html"

SOURCE_LABELS = {
    "hackernews": "🟠 Hacker News",
    "hatena": "🔵 はてな",
    "twitter": "🐦 Twitter",
}

SOURCE_COLORS = {
    "hackernews": "#ff6600",
    "hatena": "#008fde",
    "twitter": "#1d9bf0",
}


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
    title = item.get("title", "")
    url = item.get("url", "#")
    desc = item.get("description", "")
    date = format_date(item.get("published_at", ""))
    account = item.get("account", "")
    score = item.get("score", "")
    bookmarks = item.get("bookmarks", "")
    hn_url = item.get("hn_url", "")

    meta_parts = []
    if date:
        meta_parts.append(f'<span class="date">{date}</span>')
    if account:
        meta_parts.append(f'<span class="account">@{account}</span>')
    if score:
        meta_parts.append(f'<span class="score">▲ {score}</span>')
    if bookmarks:
        meta_parts.append(f'<span class="score">🔖 {bookmarks}</span>')
    if hn_url:
        meta_parts.append(f'<a href="{hn_url}" target="_blank" class="comment-link">コメント →</a>')
    meta_html = " · ".join(meta_parts)

    return f"""
    <div class="card" data-source="{source}">
      <div class="card-source" style="color:{color}">{label}</div>
      <a href="{url}" target="_blank" class="card-title">{title}</a>
      {f'<p class="card-desc">{desc}</p>' if desc and desc != title else ""}
      <div class="card-meta">{meta_html}</div>
    </div>"""


def generate_html(feed: dict) -> str:
    updated_at = feed.get("updated_at", "")
    try:
        dt = datetime.fromisoformat(updated_at)
        updated_str = dt.strftime("%Y/%m/%d %H:%M UTC")
    except Exception:
        updated_str = updated_at

    hn_items = feed.get("hackernews", [])
    hatena_items = feed.get("hatena", [])
    twitter_items = feed.get("twitter", [])

    all_items = hn_items + hatena_items + twitter_items

    # タブ別コンテンツ
    def cards(items):
        if not items:
            return '<p class="empty">記事がありません</p>'
        return "\n".join(card_html(i) for i in items)

    all_cards = cards(all_items)
    hn_cards = cards(hn_items)
    hatena_cards = cards(hatena_items)
    twitter_cards = cards(twitter_items)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed</title>
<style>
  :root {{
    --bg: #0f0f13;
    --surface: #1a1a22;
    --border: #2a2a38;
    --text: #e8e8f0;
    --muted: #7a7a9a;
    --accent: #7c6af7;
    --hn: #ff6600;
    --hatena: #008fde;
    --twitter: #1d9bf0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.6;
  }}
  header {{
    padding: 20px 24px 0;
    border-bottom: 1px solid var(--border);
  }}
  .header-top {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 16px;
  }}
  h1 {{ font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }}
  .updated {{ font-size: 12px; color: var(--muted); }}
  .tabs {{
    display: flex;
    gap: 0;
  }}
  .tab {{
    padding: 8px 18px;
    cursor: pointer;
    border: none;
    background: none;
    color: var(--muted);
    font-size: 13px;
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
  }}
  .tab:hover {{ color: var(--text); }}
  .tab.active {{ color: var(--text); border-bottom-color: var(--accent); }}
  .count {{
    display: inline-block;
    background: var(--border);
    border-radius: 10px;
    padding: 1px 7px;
    font-size: 11px;
    margin-left: 5px;
  }}
  main {{ padding: 16px 24px; max-width: 900px; }}
  .panel {{ display: none; }}
  .panel.active {{ display: block; }}
  .cards {{ display: flex; flex-direction: column; gap: 10px; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    transition: border-color 0.15s;
  }}
  .card:hover {{ border-color: var(--accent); }}
  .card-source {{
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 5px;
  }}
  .card-title {{
    display: block;
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
    font-size: 14px;
    margin-bottom: 5px;
    line-height: 1.4;
  }}
  .card-title:hover {{ color: var(--accent); }}
  .card-desc {{
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 6px;
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .card-meta {{
    font-size: 12px;
    color: var(--muted);
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
  }}
  .account {{ color: var(--twitter); }}
  .score {{ color: var(--muted); }}
  .comment-link {{
    color: var(--accent);
    text-decoration: none;
    font-size: 11px;
  }}
  .comment-link:hover {{ text-decoration: underline; }}
  .empty {{ color: var(--muted); padding: 20px 0; }}
  @media (max-width: 600px) {{
    header, main {{ padding-left: 16px; padding-right: 16px; }}
    .tab {{ padding: 8px 12px; font-size: 12px; }}
  }}
</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1>AI Feed</h1>
    <span class="updated">更新: {updated_str}</span>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="switchTab('all', this)">
      すべて <span class="count">{len(all_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hn', this)">
      HN <span class="count">{len(hn_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('hatena', this)">
      はてな <span class="count">{len(hatena_items)}</span>
    </button>
    <button class="tab" onclick="switchTab('twitter', this)">
      Twitter <span class="count">{len(twitter_items)}</span>
    </button>
  </div>
</header>
<main>
  <div id="panel-all" class="panel active">
    <div class="cards">{all_cards}</div>
  </div>
  <div id="panel-hn" class="panel">
    <div class="cards">{hn_cards}</div>
  </div>
  <div id="panel-hatena" class="panel">
    <div class="cards">{hatena_cards}</div>
  </div>
  <div id="panel-twitter" class="panel">
    <div class="cards">{twitter_cards}</div>
  </div>
</main>
<script>
  function switchTab(id, el) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    document.getElementById('panel-' + id).classList.add('active');
  }}
</script>
</body>
</html>"""


def main():
    if not FEED_PATH.exists():
        print(f"feed.json not found at {FEED_PATH}")
        return

    with open(FEED_PATH, encoding="utf-8") as f:
        feed = json.load(f)

    html = generate_html(feed)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
