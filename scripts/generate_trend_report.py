#!/usr/bin/env python3
"""
Claude のトレンド分析結果（構造化JSON）を受け取り、週次・月次レポート HTML を生成する。

使い方:
    python scripts/generate_trend_report.py --mode weekly '<JSON>'
    python scripts/generate_trend_report.py --mode monthly '<JSON>'
    python scripts/generate_trend_report.py --mode weekly --date 2026-03-10 '<JSON>'

JSON スキーマ:
    {
        "summary": "string",       # 週/月の全体まとめ
        "trends": [                 # トレンド項目（3〜6件）
            {"title": "string", "description": "string"}
        ],
        "keywords": ["string"],    # 注目キーワード
        "outlook": "string"        # 来週/来月の展望
    }
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"

# generate_html.py と共通の CSS ベース
CSS = """\
:root {
  --bg: #0f0f13;
  --surface: #1a1a22;
  --border: #2a2a38;
  --text: #e8e8f0;
  --muted: #7a7a9a;
  --accent: #7c6af7;
  --green: #4ade80;
  --orange: #fb923c;
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
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border);
}
.header-top {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 4px;
}
h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
h1 a { color: var(--text); text-decoration: none; }
h1 a:hover { color: var(--accent); }
.subtitle { font-size: 14px; color: var(--muted); }
.period-badge {
  display: inline-block;
  background: var(--accent);
  color: white;
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
}
main { padding: 20px 24px; max-width: 860px; }
section { margin-bottom: 28px; }
section h2 {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 14px;
  color: var(--text);
  border-left: 3px solid var(--accent);
  padding-left: 10px;
}
.summary-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 20px;
  line-height: 1.8;
  color: var(--text);
}
.trends-list { display: flex; flex-direction: column; gap: 12px; }
.trend-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.trend-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--accent);
  margin-bottom: 6px;
}
.trend-desc { color: var(--text); line-height: 1.7; }
.keywords { display: flex; flex-wrap: wrap; gap: 8px; }
.keyword {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 14px;
  font-size: 12px;
  color: var(--text);
}
.outlook-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--green);
  border-radius: 10px;
  padding: 16px 20px;
  line-height: 1.8;
}
.articles-grid { display: flex; flex-direction: column; gap: 8px; }
.article-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.article-source {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  white-space: nowrap;
  flex-shrink: 0;
}
.article-link {
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
  line-height: 1.4;
}
.article-link:hover { color: var(--accent); }
.article-score { color: var(--muted); font-size: 11px; white-space: nowrap; flex-shrink: 0; }
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 16px;
}
.back-link:hover { text-decoration: underline; }
.stats-row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.stat-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  text-align: center;
  min-width: 80px;
}
.stat-num { font-size: 22px; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 2px; }
@media (max-width: 600px) {
  header, main { padding-left: 16px; padding-right: 16px; }
}"""


def get_week_range(ref_date: date) -> tuple[date, date]:
    """Return (monday, sunday) of the ISO week containing ref_date."""
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_month_range(ref_date: date) -> tuple[date, date]:
    """Return (first_day, last_day) of ref_date's month."""
    first = ref_date.replace(day=1)
    if ref_date.month == 12:
        last = date(ref_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(ref_date.year, ref_date.month + 1, 1) - timedelta(days=1)
    return first, last


def collect_articles(start: date, end: date) -> list[dict]:
    """Collect all unique articles from daily JSONs in [start, end]."""
    seen_urls: set[str] = set()
    articles: list[dict] = []
    current = start
    while current <= end:
        path = DAILY_DIR / f"{current.isoformat()}.json"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for key in ["hackernews", "hatena", "twitter"]:
                    for item in data.get(key, []):
                        url = item.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            articles.append(item)
            except Exception as e:
                print(f"Warning: failed to read {path}: {e}", file=sys.stderr)
        current += timedelta(days=1)
    return articles


def top_articles(articles: list[dict], source: str, score_key: str, n: int = 10) -> list[dict]:
    """Return top n articles from given source sorted by score_key desc."""
    items = [a for a in articles if a.get("source") == source and a.get(score_key)]
    items.sort(key=lambda x: x.get(score_key, 0), reverse=True)
    return items[:n]


def article_item_html(item: dict) -> str:
    source = item.get("source", "")
    color = {"hackernews": "#ff6600", "hatena": "#008fde", "twitter": "#1d9bf0"}.get(source, "#888")
    label = {"hackernews": "HN", "hatena": "Hatena", "twitter": "Twitter"}.get(source, source)
    title = escape(item.get("title_ja") or item.get("title", ""))
    url = escape(item.get("url", "#"))
    score = item.get("score") or item.get("bookmarks") or ""
    score_icon = "▲" if source == "hackernews" else ("🔖" if source == "hatena" else "")
    score_html = f'<span class="article-score">{score_icon} {score}</span>' if score else ""
    return (
        f'<div class="article-item">'
        f'<span class="article-source" style="color:{color}">{label}</span>'
        f'<a href="{url}" target="_blank" class="article-link">{title}</a>'
        f"{score_html}"
        f"</div>"
    )


def render_trend_html(
    analysis: dict,
    period_label: str,
    period_range: str,
    articles: list[dict],
    mode: str,
) -> str:
    summary = escape(analysis.get("summary", ""))
    trends = analysis.get("trends", [])
    keywords = analysis.get("keywords", [])
    outlook = escape(analysis.get("outlook", ""))

    trends_html = ""
    for t in trends:
        title = escape(t.get("title", ""))
        desc = escape(t.get("description", ""))
        trends_html += (
            f'<div class="trend-item">'
            f'<div class="trend-title">{title}</div>'
            f'<div class="trend-desc">{desc}</div>'
            f"</div>\n"
        )

    keywords_html = "".join(
        f'<span class="keyword">{escape(kw)}</span>' for kw in keywords
    )

    # Top articles
    hn_top = top_articles(articles, "hackernews", "score", 5 if mode == "weekly" else 10)
    hatena_top = top_articles(articles, "hatena", "bookmarks", 5 if mode == "weekly" else 10)
    hn_html = "".join(article_item_html(a) for a in hn_top)
    hatena_html = "".join(article_item_html(a) for a in hatena_top)

    hn_count = sum(1 for a in articles if a.get("source") == "hackernews")
    hatena_count = sum(1 for a in articles if a.get("source") == "hatena")
    twitter_count = sum(1 for a in articles if a.get("source") == "twitter")
    total = len(articles)

    period_type = "週次" if mode == "weekly" else "月次"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI トレンドレポート {period_label}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../index.html">AI Feed</a></h1>
    <span class="period-badge">{period_type}レポート</span>
    <span class="subtitle">{period_label} ({period_range})</span>
  </div>
</header>
<main>
  <a href="../index.html" class="back-link">&larr; 最新フィードへ</a>

  <div class="stats-row">
    <div class="stat-box"><div class="stat-num">{total}</div><div class="stat-label">総記事数</div></div>
    <div class="stat-box"><div class="stat-num">{hn_count}</div><div class="stat-label">HN</div></div>
    <div class="stat-box"><div class="stat-num">{hatena_count}</div><div class="stat-label">Hatena</div></div>
    <div class="stat-box"><div class="stat-num">{twitter_count}</div><div class="stat-label">Twitter</div></div>
  </div>

  <section>
    <h2>📋 {period_type}サマリー</h2>
    <div class="summary-box">{summary}</div>
  </section>

  <section>
    <h2>🔥 主要トレンド</h2>
    <div class="trends-list">{trends_html}</div>
  </section>

  <section>
    <h2>💡 注目キーワード</h2>
    <div class="keywords">{keywords_html}</div>
  </section>

  <section>
    <h2>🟠 HN ランキング TOP{len(hn_top)}</h2>
    <div class="articles-grid">{hn_html or '<p style="color:var(--muted)">記事なし</p>'}</div>
  </section>

  <section>
    <h2>🔵 はてな ランキング TOP{len(hatena_top)}</h2>
    <div class="articles-grid">{hatena_html or '<p style="color:var(--muted)">記事なし</p>'}</div>
  </section>

  <section>
    <h2>🌅 展望</h2>
    <div class="outlook-box">{outlook}</div>
  </section>
</main>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI trend report HTML")
    parser.add_argument("--mode", choices=["weekly", "monthly"], required=True)
    parser.add_argument("--date", default=None, help="Reference date YYYY-MM-DD (default: today)")
    parser.add_argument("analysis_json", nargs="?", default="", help="Trend analysis JSON from Claude")
    args = parser.parse_args()

    ref = date.fromisoformat(args.date) if args.date else date.today()

    if args.mode == "weekly":
        start, end = get_week_range(ref)
        iso_year, iso_week, _ = ref.isocalendar()
        period_label = f"{iso_year}-W{iso_week:02d}"
        period_range = f"{start.isoformat()} 〜 {end.isoformat()}"
        out_dir = WEEKLY_DIR
        out_name = f"{period_label}.html"
    else:
        start, end = get_month_range(ref)
        period_label = ref.strftime("%Y-%m")
        period_range = f"{start.isoformat()} 〜 {end.isoformat()}"
        out_dir = MONTHLY_DIR
        out_name = f"{period_label}.html"

    # Parse analysis JSON
    raw = args.analysis_json.strip()
    if raw:
        try:
            analysis = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"Warning: failed to parse analysis JSON ({e}), using empty analysis", file=sys.stderr)
            analysis = {}
    else:
        analysis = {}

    # Fill in defaults if analysis is empty / incomplete
    if not analysis.get("summary"):
        analysis["summary"] = f"{period_label} のAIトレンドレポートです。"
    if not analysis.get("trends"):
        analysis["trends"] = []
    if not analysis.get("keywords"):
        analysis["keywords"] = []
    if not analysis.get("outlook"):
        analysis["outlook"] = ""

    # Collect articles
    articles = collect_articles(start, end)
    print(f"Collected {len(articles)} articles for {period_label} ({start} - {end})")

    # Generate HTML
    html = render_trend_html(analysis, period_label, period_range, articles, args.mode)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    main()
