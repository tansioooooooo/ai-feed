#!/usr/bin/env python3
"""
週次・月次 AI トレンドレポートを生成するスクリプト

使い方:
  python scripts/generate_trend_report.py --mode weekly [--date YYYY-MM-DD]
  python scripts/generate_trend_report.py --mode monthly [--date YYYY-MM-DD]

環境変数:
  ANTHROPIC_API_KEY  - Claude API キー（必須）
"""

import argparse
import json
import os
from datetime import date, timedelta
from html import escape
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"

SOURCE_COLORS = {"hackernews": "#ff6600", "hatena": "#008fde", "twitter": "#1d9bf0"}
SOURCE_LABELS = {"hackernews": "HN", "hatena": "Hatena", "twitter": "Twitter"}

CSS = """\
:root {
  --bg: #0f0f13;
  --surface: #1a1a22;
  --border: #2a2a38;
  --text: #e8e8f0;
  --muted: #7a7a9a;
  --accent: #7c6af7;
  --accent2: #4fcf8f;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.7;
}
header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border);
}
.header-top {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}
h1 { font-size: 20px; font-weight: 700; }
h1 a { color: var(--text); text-decoration: none; }
h1 a:hover { color: var(--accent); }
.period-label { font-size: 16px; color: var(--accent); font-weight: 600; }
.stats { font-size: 12px; color: var(--muted); margin-top: 6px; }
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 16px;
}
.back-link:hover { text-decoration: underline; }
main { padding: 20px 24px; max-width: 900px; }
.trend-report section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 16px;
}
.trend-report h2 {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.trend-report h3 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text);
}
.trend-report p { color: var(--text); margin-bottom: 8px; }
.trend-item {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 10px;
}
.trend-item:last-child { margin-bottom: 0; }
.keyword-list { display: flex; flex-wrap: wrap; gap: 8px; }
.keyword {
  background: var(--border);
  border-radius: 16px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--accent2);
}
.trend-report ul { padding-left: 20px; }
.trend-report li { margin-bottom: 6px; color: var(--text); }
.top-articles-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px;
  margin-bottom: 16px;
}
.top-articles-section h2 {
  font-size: 16px;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
table { width: 100%; border-collapse: collapse; }
td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:last-child td { border-bottom: none; }
td a { color: var(--text); text-decoration: none; }
td a:hover { color: var(--accent); }
@media (max-width: 600px) {
  header, main { padding-left: 16px; padding-right: 16px; }
}"""


def load_period_articles(start_date: date, end_date: date) -> list[dict]:
    """指定期間の daily JSON から記事を収集"""
    articles = []
    current = start_date
    while current <= end_date:
        json_path = DAILY_DIR / f"{current.isoformat()}.json"
        if json_path.exists():
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            for source_key in ["hackernews", "hatena", "twitter"]:
                seen_urls = set()
                for item in data.get(source_key, []):
                    url = item.get("url", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    articles.append(
                        {
                            "date": current.isoformat(),
                            "source": source_key,
                            "title": item.get("title_ja") or item.get("title", ""),
                            "title_en": item.get("title", ""),
                            "url": url,
                            "score": item.get("score") or item.get("bookmarks") or 0,
                        }
                    )
        current += timedelta(days=1)

    # URL 重複排除（複数日にまたがるケース）
    seen = set()
    unique = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique


def build_prompt(articles: list[dict], period_label: str, mode: str) -> str:
    lines = []
    for a in articles:
        score_str = f"（スコア:{a['score']}）" if a["score"] else ""
        label = SOURCE_LABELS.get(a["source"], a["source"])
        lines.append(f"- [{label}] {a['title']} {score_str}")

    articles_text = "\n".join(lines)

    if mode == "weekly":
        return f"""以下は{period_label}のAI関連ニュース記事の一覧です（HN=Hacker News, Hatena=はてなブックマーク, Twitter）。

{articles_text}

この記事一覧を分析して、{period_label}のAIトレンドレポートを日本語で作成してください。

以下の形式でHTMLを出力してください（<div class="trend-report">タグで全体を囲む）：

<div class="trend-report">
<section class="summary">
<h2>今週のサマリー</h2>
<p>（3〜5文で今週のAI動向の概要を記述）</p>
</section>

<section class="trends">
<h2>主要トレンド</h2>
（3〜5個の主要なトレンドをそれぞれ以下の形式で）
<div class="trend-item">
<h3>🔥 トレンド名</h3>
<p>トレンドの説明（2〜3文）</p>
</div>
</section>

<section class="keywords">
<h2>注目キーワード</h2>
<div class="keyword-list">
<span class="keyword">キーワード1</span>
<span class="keyword">キーワード2</span>
...（5〜10個）
</div>
</section>

<section class="outlook">
<h2>来週の展望</h2>
<p>（2〜3文で来週以降の注目点や予測）</p>
</section>
</div>

HTMLのみを出力し、コードブロック記法（```）は使わないでください。"""
    else:
        return f"""以下は{period_label}のAI関連ニュース記事の一覧です（HN=Hacker News, Hatena=はてなブックマーク, Twitter）。

{articles_text}

この記事一覧を分析して、{period_label}のAI月次まとめレポートを日本語で作成してください。

以下の形式でHTMLを出力してください（<div class="trend-report">タグで全体を囲む）：

<div class="trend-report">
<section class="summary">
<h2>今月のサマリー</h2>
<p>（4〜6文でこの月のAI動向の概要を記述）</p>
</section>

<section class="trends">
<h2>主要トレンド</h2>
（4〜6個の主要なトレンドをそれぞれ以下の形式で）
<div class="trend-item">
<h3>🔥 トレンド名</h3>
<p>トレンドの説明（2〜4文）</p>
</div>
</section>

<section class="highlights">
<h2>今月のハイライト</h2>
<ul>
（今月の重要な出来事を箇条書きで5〜8項目）
<li>...</li>
</ul>
</section>

<section class="keywords">
<h2>注目キーワード</h2>
<div class="keyword-list">
<span class="keyword">キーワード1</span>
<span class="keyword">キーワード2</span>
...（8〜15個）
</div>
</section>
</div>

HTMLのみを出力し、コードブロック記法（```）は使わないでください。"""


def generate_trend_analysis(articles: list[dict], period_label: str, mode: str) -> str:
    """Claude API でトレンド分析を生成"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            '<div class="trend-report"><section class="summary">'
            "<h2>エラー</h2>"
            "<p>ANTHROPIC_API_KEY が設定されていないため、トレンド分析を生成できませんでした。</p>"
            "</section></div>"
        )

    prompt = build_prompt(articles, period_label, mode)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def get_top_articles(articles: list[dict], n: int = 10) -> list[dict]:
    scored = [a for a in articles if a["score"] > 0]
    return sorted(scored, key=lambda x: x["score"], reverse=True)[:n]


def render_top_articles(articles: list[dict]) -> str:
    top = get_top_articles(articles)
    if not top:
        return "<p style=\"color:var(--muted)\">スコアデータなし</p>"
    rows = ""
    for i, a in enumerate(top, 1):
        color = SOURCE_COLORS.get(a["source"], "#888")
        label = SOURCE_LABELS.get(a["source"], a["source"])
        title = escape(a["title"])
        url = escape(a["url"])
        rows += (
            f"<tr>"
            f'<td style="color:var(--muted);text-align:center;width:30px">{i}</td>'
            f'<td style="width:60px"><span style="color:{color};font-size:11px;font-weight:600">{label}</span></td>'
            f'<td><a href="{url}" target="_blank">{title}</a></td>'
            f'<td style="text-align:right;color:var(--muted);white-space:nowrap">{a["score"]}</td>'
            f"</tr>"
        )
    return f"<table>{rows}</table>"


def generate_report_html(
    period_label: str,
    articles: list[dict],
    trend_analysis: str,
) -> str:
    source_count: dict[str, int] = {}
    for a in articles:
        source_count[a["source"]] = source_count.get(a["source"], 0) + 1

    stats_html = " &middot; ".join(
        [
            f"合計 {len(articles)} 記事",
            f"HN {source_count.get('hackernews', 0)} 件",
            f"Hatena {source_count.get('hatena', 0)} 件",
            f"Twitter {source_count.get('twitter', 0)} 件",
        ]
    )

    top_html = render_top_articles(articles)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - {escape(period_label)}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../../index.html">AI Feed</a></h1>
    <span class="period-label">{escape(period_label)}</span>
  </div>
  <div class="stats">{stats_html}</div>
</header>
<main>
  <a href="../../index.html" class="back-link">&larr; 最新フィード</a>
  {trend_analysis}
  <div class="top-articles-section">
    <h2>期間中のトップ記事</h2>
    {top_html}
  </div>
</main>
</body>
</html>"""


def get_week_range(ref_date: date) -> tuple[date, date, str, str]:
    """その週の月曜〜日曜の範囲・ラベル・ファイル名を返す"""
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    iso_year, iso_week, _ = monday.isocalendar()
    label = f"{iso_year}年 第{iso_week}週 ({monday.strftime('%m/%d')}〜{sunday.strftime('%m/%d')})"
    filename = f"{iso_year}-W{iso_week:02d}.html"
    return monday, sunday, label, filename


def get_month_range(ref_date: date) -> tuple[date, date, str, str]:
    """その月の1日〜末日の範囲・ラベル・ファイル名を返す"""
    first = ref_date.replace(day=1)
    if ref_date.month == 12:
        last = ref_date.replace(year=ref_date.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = ref_date.replace(month=ref_date.month + 1, day=1) - timedelta(days=1)
    label = f"{ref_date.year}年{ref_date.month}月"
    filename = f"{ref_date.year}-{ref_date.month:02d}.html"
    return first, last, label, filename


def main() -> None:
    parser = argparse.ArgumentParser(description="AI トレンドレポート生成")
    parser.add_argument("--mode", choices=["weekly", "monthly"], required=True, help="週次 or 月次")
    parser.add_argument("--date", default=None, help="基準日 YYYY-MM-DD（デフォルト: 今日）")
    args = parser.parse_args()

    ref_date = date.fromisoformat(args.date) if args.date else date.today()

    if args.mode == "weekly":
        start, end, label, filename = get_week_range(ref_date)
        output_dir = WEEKLY_DIR
    else:
        start, end, label, filename = get_month_range(ref_date)
        output_dir = MONTHLY_DIR

    print(f"Generating {args.mode} report: {label} ({start} to {end})")

    articles = load_period_articles(start, end)
    print(f"  Collected {len(articles)} articles")

    if not articles:
        print("  No articles found, skipping report generation")
        return

    print("  Generating trend analysis with Claude...")
    trend_analysis = generate_trend_analysis(articles, label, args.mode)

    html = generate_report_html(label, articles, trend_analysis)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  Generated {output_path}")


if __name__ == "__main__":
    main()
