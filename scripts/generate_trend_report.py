#!/usr/bin/env python3
"""
週次・月次 AI トレンドレポートを生成する。

使い方:
  python scripts/generate_trend_report.py --mode weekly
  python scripts/generate_trend_report.py --mode monthly
  python scripts/generate_trend_report.py --mode weekly --date 2026-03-10

環境変数 ANTHROPIC_API_KEY が設定されていれば Claude API でトレンド分析を行う。
未設定の場合はキーワード集計のみでレポートを生成する。
"""

import argparse
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"


# ---- データ収集 --------------------------------------------------------

def load_articles_for_dates(date_list: list[str]) -> list[dict]:
    """指定日付リストの daily JSON を読み込んで記事を結合（URL重複排除）。"""
    seen_urls: set[str] = set()
    articles: list[dict] = []
    for d in sorted(date_list):
        path = DAILY_DIR / f"{d}.json"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for key in ["hackernews", "hatena", "twitter"]:
            for item in data.get(key, []):
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    articles.append(item)
    return articles


def week_dates(base: date) -> list[str]:
    """base を含む週（月曜〜日曜）の日付文字列リスト。"""
    monday = base - timedelta(days=base.weekday())
    return [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def month_dates(base: date) -> list[str]:
    """base と同じ月の全日付文字列リスト。"""
    start = base.replace(day=1)
    # 翌月1日 - 1日 = 月末
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
    dates = []
    cur = start
    while cur <= end:
        dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


def week_label(base: date) -> str:
    """例: 2026-W11"""
    return f"{base.isocalendar().year}-W{base.isocalendar().week:02d}"


def month_label(base: date) -> str:
    """例: 2026-03"""
    return base.strftime("%Y-%m")


# ---- Claude API 分析 ---------------------------------------------------

def build_prompt(articles: list[dict], mode: str, label: str) -> str:
    period = "今週" if mode == "weekly" else "今月"
    lines = []
    for a in articles:
        title = a.get("title_ja") or a.get("title", "")
        source = a.get("source", "")
        score = a.get("score", "")
        bm = a.get("bookmarks", "")
        meta = f"[{source}]"
        if score:
            meta += f" スコア:{score}"
        if bm:
            meta += f" BM:{bm}"
        lines.append(f"{meta} {title}")

    articles_text = "\n".join(lines)

    return f"""以下は AI Feed（{label}）に収集された AI 関連記事のリストです。

{articles_text}

---

上記の記事リストを分析して、{period}の AI 業界トレンドレポートを日本語で作成してください。

【出力形式（JSON）】
{{
  "summary": "{period}全体の概況（3〜5文、具体的な動きを踏まえて）",
  "trends": [
    {{"title": "トレンドのタイトル（10字以内）", "description": "詳細説明（2〜3文）"}},
    ...（3〜5件）
  ],
  "keywords": ["注目キーワード1", "注目キーワード2", ...（5〜10個）],
  "outlook": "来{period[1]}の展望または総括（1〜2文）"
}}

記事タイトルから読み取れる具体的な動きや傾向を反映してください。
JSONのみ返してください。"""


def analyze_with_claude(articles: list[dict], mode: str, label: str) -> dict | None:
    """Claude API でトレンド分析。失敗時は None を返す。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed, falling back to keyword analysis")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = build_prompt(articles, mode, label)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # JSON ブロックを抽出
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(text)
    except Exception as e:
        print(f"Claude API error: {e}")
        return None


# ---- フォールバック: キーワード集計 ------------------------------------

AI_KEYWORDS = [
    "Claude", "GPT", "Gemini", "LLM", "OpenAI", "Anthropic", "Google", "Meta",
    "DeepSeek", "Llama", "Mistral", "Grok", "xAI", "Cohere", "o1", "o3",
    "AGI", "生成AI", "機械学習", "deep learning", "transformer",
    "RAG", "fine-tuning", "inference", "agent", "multimodal",
    "画像生成", "音声", "動画", "reasoning", "benchmark",
    "regulation", "規制", "著作権", "copyright", "policy",
    "open source", "オープンソース", "API", "GPU", "chip",
    "funding", "資金調達", "acquisition", "IPO",
]


def extract_keywords(articles: list[dict]) -> list[str]:
    text = " ".join(
        (a.get("title_ja") or a.get("title", "")) for a in articles
    ).lower()
    counts = Counter()
    for kw in AI_KEYWORDS:
        n = len(re.findall(re.escape(kw.lower()), text))
        if n > 0:
            counts[kw] += n
    return [kw for kw, _ in counts.most_common(10)]


def fallback_analysis(articles: list[dict], mode: str, label: str) -> dict:
    period = "今週" if mode == "weekly" else "今月"
    keywords = extract_keywords(articles)
    n = len(articles)
    return {
        "summary": (
            f"{label} の AI 関連記事 {n} 件を収集しました。"
            f"主な話題は {', '.join(keywords[:5]) if keywords else 'さまざま'} などです。"
            f"（Claude API が未設定のため詳細分析は省略されています）"
        ),
        "trends": [
            {
                "title": "収集記事一覧",
                "description": f"{n} 件の AI 関連記事が収集されました。詳細なトレンド分析には ANTHROPIC_API_KEY の設定が必要です。",
            }
        ],
        "keywords": keywords,
        "outlook": f"継続的なモニタリングにより{period[1:]}の動向を把握します。",
    }


# ---- HTML 生成 ----------------------------------------------------------

CSS_TREND = """\
:root {
  --bg: #0f0f13;
  --surface: #1a1a22;
  --border: #2a2a38;
  --text: #e8e8f0;
  --muted: #7a7a9a;
  --accent: #7c6af7;
  --green: #4caf88;
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
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 20px;
}
.back-link:hover { text-decoration: underline; }
h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.period { color: var(--muted); font-size: 13px; margin-bottom: 24px; }
.section { margin-bottom: 28px; }
.section h2 {
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  color: var(--muted);
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.summary-text {
  color: var(--text);
  font-size: 15px;
  line-height: 1.8;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
}
.trend-list { display: flex; flex-direction: column; gap: 10px; }
.trend-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.trend-card h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 6px;
}
.trend-card p { color: var(--text); font-size: 13px; line-height: 1.7; }
.keywords { display: flex; flex-wrap: wrap; gap: 8px; }
.keyword {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 14px;
  font-size: 13px;
  color: var(--text);
}
.keyword:nth-child(1) { border-color: var(--accent); color: var(--accent); }
.keyword:nth-child(2) { border-color: #e0877a; color: #e0877a; }
.keyword:nth-child(3) { border-color: var(--green); color: var(--green); }
.outlook-text {
  color: var(--text);
  font-size: 14px;
  line-height: 1.8;
  background: var(--surface);
  border-left: 3px solid var(--accent);
  border-radius: 0 8px 8px 0;
  padding: 12px 16px;
}
.stats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 16px;
  font-size: 13px;
}
.stat-num { font-size: 20px; font-weight: 700; color: var(--accent); }
.generated-at { color: var(--muted); font-size: 11px; margin-top: 32px; }
"""


def render_trend_html(
    label: str,
    mode: str,
    analysis: dict,
    articles: list[dict],
    generated_at: str,
) -> str:
    period_label = "Weekly" if mode == "weekly" else "Monthly"
    title = f"AI Trend Report — {label}"

    hn_count = sum(1 for a in articles if a.get("source") == "hackernews")
    hatena_count = sum(1 for a in articles if a.get("source") == "hatena")
    twitter_count = sum(1 for a in articles if a.get("source") == "twitter")

    stats_html = (
        f'<div class="stats">'
        f'<div class="stat"><div class="stat-num">{len(articles)}</div>総記事数</div>'
        f'<div class="stat"><div class="stat-num">{hn_count}</div>Hacker News</div>'
        f'<div class="stat"><div class="stat-num">{hatena_count}</div>はてな</div>'
        f'<div class="stat"><div class="stat-num">{twitter_count}</div>Twitter</div>'
        f"</div>"
    )

    trends_html = "\n".join(
        f'<div class="trend-card">'
        f'<h3>{escape(t.get("title", ""))}</h3>'
        f'<p>{escape(t.get("description", ""))}</p>'
        f"</div>"
        for t in analysis.get("trends", [])
    )

    keywords_html = "\n".join(
        f'<span class="keyword">{escape(k)}</span>'
        for k in analysis.get("keywords", [])
    )

    back_path = "../../index.html" if mode == "weekly" else "../../index.html"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>{CSS_TREND}</style>
</head>
<body>
<a href="{back_path}" class="back-link">&larr; AI Feed</a>
<h1>AI Trend Report</h1>
<div class="period">{period_label} · {escape(label)}</div>

{stats_html}

<div class="section">
  <h2>概況サマリー</h2>
  <div class="summary-text">{escape(analysis.get("summary", ""))}</div>
</div>

<div class="section">
  <h2>主要トレンド</h2>
  <div class="trend-list">{trends_html}</div>
</div>

<div class="section">
  <h2>注目キーワード</h2>
  <div class="keywords">{keywords_html}</div>
</div>

<div class="section">
  <h2>展望</h2>
  <div class="outlook-text">{escape(analysis.get("outlook", ""))}</div>
</div>

<div class="generated-at">Generated: {escape(generated_at)}</div>
</body>
</html>"""


# ---- メイン ------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI trend report")
    parser.add_argument(
        "--mode", choices=["weekly", "monthly"], required=True
    )
    parser.add_argument(
        "--date",
        default=date.today().strftime("%Y-%m-%d"),
        help="Base date (YYYY-MM-DD), default: today",
    )
    args = parser.parse_args()

    base = datetime.strptime(args.date, "%Y-%m-%d").date()

    if args.mode == "weekly":
        dates = week_dates(base)
        label = week_label(base)
        out_dir = WEEKLY_DIR
    else:
        dates = month_dates(base)
        label = month_label(base)
        out_dir = MONTHLY_DIR

    articles = load_articles_for_dates(dates)
    if not articles:
        print(f"No articles found for {label}, skipping report generation")
        return

    print(f"Loaded {len(articles)} articles for {label}")

    analysis = analyze_with_claude(articles, args.mode, label)
    if analysis is None:
        print("Falling back to keyword analysis (no ANTHROPIC_API_KEY or API error)")
        analysis = fallback_analysis(articles, args.mode, label)
    else:
        print("Trend analysis completed with Claude API")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_trend_html(label, args.mode, analysis, articles, generated_at)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{label}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {out_path}")


if __name__ == "__main__":
    main()
