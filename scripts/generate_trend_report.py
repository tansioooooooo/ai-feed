#!/usr/bin/env python3
"""
週次・月次 AI トレンドレポートを生成する。

使い方:
  python scripts/generate_trend_report.py --mode weekly [--date YYYY-MM-DD]
  python scripts/generate_trend_report.py --mode monthly [--date YYYY-MM-DD]

ANTHROPIC_API_KEY 環境変数が必要。
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"

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
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
}
h1 { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
h1 a { color: var(--text); text-decoration: none; }
h1 a:hover { color: var(--accent); }
h2 { font-size: 17px; font-weight: 600; margin: 24px 0 10px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
h3 { font-size: 14px; font-weight: 600; margin: 16px 0 6px; }
p { margin-bottom: 10px; color: var(--text); }
.subtitle { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.back-link { display: inline-block; color: var(--accent); text-decoration: none; font-size: 13px; margin-bottom: 20px; }
.back-link:hover { text-decoration: underline; }
.report-body { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 24px; white-space: pre-wrap; line-height: 1.8; }
.ranking { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.rank-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; }
.rank-num { color: var(--accent); font-weight: 700; margin-right: 8px; }
.rank-title { color: var(--text); text-decoration: none; font-size: 14px; }
.rank-title:hover { color: var(--accent); }
.rank-meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
.meta { color: var(--muted); font-size: 12px; margin-bottom: 20px; }
"""


def load_articles_for_range(start: date, end: date) -> list[dict]:
    """指定期間の daily JSON から記事を収集（URL重複排除）。"""
    articles = []
    seen_urls = set()
    current = start
    while current <= end:
        path = DAILY_DIR / f"{current.isoformat()}.json"
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for key in ["hackernews", "hatena", "twitter"]:
                for item in data.get(key, []):
                    url = item.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(item)
        current += timedelta(days=1)
    return articles


def build_article_list_text(articles: list[dict]) -> str:
    """Claude に渡すための記事リストテキストを生成。"""
    lines = []
    for i, a in enumerate(articles, 1):
        title = a.get("title_ja") or a.get("title", "")
        title_en = a.get("title", "")
        source = a.get("source", "")
        score = a.get("score", "")
        bookmarks = a.get("bookmarks", "")
        date_str = (a.get("published_at", "") or "")[:10]

        meta = f"[{source}"
        if score:
            meta += f", score={score}"
        if bookmarks:
            meta += f", bookmarks={bookmarks}"
        if date_str:
            meta += f", {date_str}"
        meta += "]"

        if title_en and title_en != title:
            lines.append(f"{i}. {title} / {title_en} {meta}")
        else:
            lines.append(f"{i}. {title} {meta}")
    return "\n".join(lines)


def generate_trend_text_via_claude(
    articles: list[dict], mode: str, period_label: str
) -> str:
    """Claude API を呼び出してトレンド分析テキストを生成。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "（ANTHROPIC_API_KEY が設定されていないため、トレンド分析を生成できませんでした）"

    client = anthropic.Anthropic(api_key=api_key)
    article_text = build_article_list_text(articles)

    if mode == "weekly":
        prompt = f"""以下は {period_label} の AI 関連ニュース記事一覧です（HN/はてなブックマーク/Twitter から収集）。

{article_text}

この週のAIトレンドを日本語で分析・まとめてください。以下のセクション構成でレポートを作成してください。

## 今週のサマリー
（この週全体の概況を2〜3文で）

## 主要トレンド
（3〜5個のトレンドを、見出しと説明文の形式で。具体的な記事タイトルや企業名を引用しながら）

## 注目キーワード
（この週よく登場したキーワードをコンマ区切りで10個程度）

## 来週の展望
（今週の流れから見えてくる来週以降の動向予測を1〜2文で）

各セクションは Markdown の ## 見出しを使って区切り、自然な日本語で書いてください。"""
    else:  # monthly
        prompt = f"""以下は {period_label} の AI 関連ニュース記事一覧です（HN/はてなブックマーク/Twitter から収集）。

{article_text}

この月のAIトレンドを日本語で分析・まとめてください。以下のセクション構成でレポートを作成してください。

## 今月のサマリー
（この月全体の概況を3〜4文で）

## 主要トレンド
（4〜6個のトレンドを、見出しと説明文の形式で。具体的な記事タイトルや企業名を引用しながら）

## 今月のハイライト
（最も注目すべき出来事・記事を3〜5件、箇条書きで）

## 注目キーワード
（この月よく登場したキーワードをコンマ区切りで15個程度）

## 翌月の展望
（今月の流れから見えてくる来月以降の動向予測を2〜3文で）

各セクションは Markdown の ## 見出しを使って区切り、自然な日本語で書いてください。"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def markdown_to_html(text: str) -> str:
    """簡易 Markdown → HTML 変換（## 見出し、箇条書き、段落）。"""
    lines = text.split("\n")
    html_parts = []
    in_ul = False
    for line in lines:
        if line.startswith("## "):
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            html_parts.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            html_parts.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_ul:
                html_parts.append('<ul style="padding-left:1.5em;margin-bottom:10px;">')
                in_ul = True
            html_parts.append(f"<li>{escape(line[2:])}</li>")
        elif line.strip() == "":
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
        else:
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            html_parts.append(f"<p>{escape(line)}</p>")
    if in_ul:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def top_articles_html(articles: list[dict], source: str, key: str, top_n: int = 5) -> str:
    """スコア/ブックマーク順の上位記事 HTML。"""
    filtered = [a for a in articles if a.get("source") == source and a.get(key)]
    filtered.sort(key=lambda x: x.get(key, 0), reverse=True)
    top = filtered[:top_n]
    if not top:
        return "<p style='color:var(--muted)'>データなし</p>"
    items = []
    for i, a in enumerate(top, 1):
        title = escape(a.get("title_ja") or a.get("title", ""))
        url = escape(a.get("url", "#"))
        val = a.get(key, "")
        label = "▲" if key == "score" else "🔖"
        items.append(
            f'<div class="rank-item">'
            f'<span class="rank-num">#{i}</span>'
            f'<a href="{url}" target="_blank" class="rank-title">{title}</a>'
            f'<div class="rank-meta">{label} {val}</div>'
            f"</div>"
        )
    return '<div class="ranking">' + "\n".join(items) + "</div>"


def render_html(
    title: str,
    subtitle: str,
    trend_text: str,
    articles: list[dict],
    mode: str,
    top_n: int = 5,
) -> str:
    trend_html = markdown_to_html(trend_text)
    hn_ranking = top_articles_html(articles, "hackernews", "score", top_n)
    hatena_ranking = top_articles_html(articles, "hatena", "bookmarks", top_n)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<a href="../../index.html" class="back-link">&larr; AI Feed トップ</a>
<h1>AI Feed {escape(title)}</h1>
<p class="subtitle">{escape(subtitle)}</p>

<div class="report-body">
{trend_html}
</div>

<h2>HN ランキング TOP{top_n}（スコア順）</h2>
{hn_ranking}

<h2>はてな ランキング TOP{top_n}（ブックマーク順）</h2>
{hatena_ranking}

<p class="meta" style="margin-top:32px">Generated by Claude / AI Feed</p>
</body>
</html>"""


def get_week_range(ref_date: date) -> tuple[date, date]:
    """ref_date を含む月曜〜日曜の週を返す。"""
    start = ref_date - timedelta(days=ref_date.weekday())
    end = start + timedelta(days=6)
    return start, end


def get_month_range(ref_date: date) -> tuple[date, date]:
    """ref_date を含む月の 1 日〜月末を返す。"""
    start = ref_date.replace(day=1)
    if ref_date.month == 12:
        end = date(ref_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(ref_date.year, ref_date.month + 1, 1) - timedelta(days=1)
    return start, end


def iso_week_label(d: date) -> str:
    """例: 2026-W10"""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def generate_weekly(ref_date: date) -> Path:
    start, end = get_week_range(ref_date)
    articles = load_articles_for_range(start, end)
    if not articles:
        print(f"Weekly: no articles found for {start} - {end}, skipping.")
        return None

    week_label = iso_week_label(start)
    period_label = f"{start.isoformat()} 〜 {end.isoformat()}"
    print(f"Weekly trend report: {week_label} ({period_label}), {len(articles)} articles")

    trend_text = generate_trend_text_via_claude(articles, "weekly", period_label)

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WEEKLY_DIR / f"{week_label}.html"
    html = render_html(
        title=f"週次トレンドレポート {week_label}",
        subtitle=period_label,
        trend_text=trend_text,
        articles=articles,
        mode="weekly",
        top_n=5,
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {out_path}")
    return out_path


def generate_monthly(ref_date: date) -> Path:
    start, end = get_month_range(ref_date)
    articles = load_articles_for_range(start, end)
    if not articles:
        print(f"Monthly: no articles found for {start} - {end}, skipping.")
        return None

    month_label = ref_date.strftime("%Y-%m")
    period_label = f"{start.isoformat()} 〜 {end.isoformat()}"
    print(f"Monthly trend report: {month_label} ({period_label}), {len(articles)} articles")

    trend_text = generate_trend_text_via_claude(articles, "monthly", period_label)

    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MONTHLY_DIR / f"{month_label}.html"
    html = render_html(
        title=f"月次トレンドレポート {month_label}",
        subtitle=period_label,
        trend_text=trend_text,
        articles=articles,
        mode="monthly",
        top_n=10,
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="AI トレンドレポートを生成")
    parser.add_argument(
        "--mode",
        choices=["weekly", "monthly"],
        required=True,
        help="weekly または monthly",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="基準日 (YYYY-MM-DD)。省略時は今日",
    )
    args = parser.parse_args()

    if args.date:
        ref_date = date.fromisoformat(args.date)
    else:
        from datetime import datetime, timezone
        ref_date = datetime.now(timezone.utc).date()

    if args.mode == "weekly":
        result = generate_weekly(ref_date)
    else:
        result = generate_monthly(ref_date)

    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
