#!/usr/bin/env python3
"""
週次・月次 AI トレンドレポートを生成する。

Claude API（anthropic SDK）で記事タイトル一覧を分析し、
トレンドサマリーを日本語で生成して HTML に保存する。

ANTHROPIC_API_KEY が未設定の場合はキーワード集計のみ行うフォールバック動作。

使い方:
  python scripts/generate_trend_report.py --mode weekly
  python scripts/generate_trend_report.py --mode monthly
  python scripts/generate_trend_report.py --mode weekly --date 2026-03-10
"""

import argparse
import json
import os
import re
from collections import Counter
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"

# generate_html.py と同じ CSS を流用
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
main { padding: 20px 24px; max-width: 900px; }
section { margin-bottom: 32px; }
h2 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
h3 { font-size: 14px; font-weight: 600; color: var(--accent); margin-bottom: 8px; }
.summary-box {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  color: var(--text);
  line-height: 1.8;
  white-space: pre-wrap;
}
.trend-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.trend-title {
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 6px;
  font-size: 14px;
}
.trend-desc {
  color: var(--text);
  font-size: 13px;
  line-height: 1.7;
}
.keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.keyword-tag {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text);
}
.keyword-tag .kw-count {
  color: var(--accent);
  font-weight: 600;
  margin-left: 4px;
}
.article-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 8px;
}
.article-card a {
  color: var(--text);
  text-decoration: none;
  font-weight: 500;
  font-size: 13px;
  line-height: 1.4;
}
.article-card a:hover { color: var(--accent); }
.article-card .en-title {
  font-size: 11px;
  color: var(--muted);
  margin-top: 3px;
}
.article-meta {
  font-size: 11px;
  color: var(--muted);
  margin-top: 4px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
  margin-bottom: 20px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}
.stat-number { font-size: 24px; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 2px; }
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-bottom: 16px;
}
.back-link:hover { text-decoration: underline; }
.source-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-right: 4px;
}
.source-hn { background: #ff660022; color: #ff6600; }
.source-hatena { background: #008fde22; color: #008fde; }
.source-twitter { background: #1d9bf022; color: #1d9bf0; }
.week-section { margin-bottom: 24px; }
.week-section h3 { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
@media (max-width: 600px) {
  header, main { padding-left: 16px; padding-right: 16px; }
}"""


# ---------- データ読み込み ----------

def load_daily_jsons(start_date: date, end_date: date) -> list[dict]:
    """指定期間の daily JSON を読み込んで記事リストを返す（URL重複排除）。"""
    all_items = []
    seen_urls = set()
    d = start_date
    while d <= end_date:
        path = DAILY_DIR / f"{d.isoformat()}.json"
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for key in ["hackernews", "hatena", "twitter"]:
                    for item in data.get(key, []):
                        url = item.get("url", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_items.append(item)
            except Exception as e:
                print(f"  Warning: failed to load {path}: {e}")
        d += timedelta(days=1)
    return all_items


def format_items_for_claude(items: list[dict]) -> str:
    """Claude に渡す記事リスト文字列を構築。"""
    lines = []
    for item in items:
        source = item.get("source", "")
        title = item.get("title", "")
        title_ja = item.get("title_ja", "")
        score = item.get("score", "")
        bookmarks = item.get("bookmarks", "")

        display_title = title_ja if title_ja else title
        meta_parts = []
        if score:
            meta_parts.append(f"HNスコア:{score}")
        if bookmarks:
            meta_parts.append(f"ブックマーク:{bookmarks}")
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""

        en_note = f" / EN: {title}" if title_ja and title else ""
        lines.append(f"[{source.upper()}] {display_title}{en_note}{meta}")

    return "\n".join(lines)


# ---------- Claude API 分析 ----------

def analyze_with_claude(articles_text: str, mode: str, period_label: str) -> dict | None:
    """
    Claude API でトレンド分析を実行。
    ANTHROPIC_API_KEY が未設定の場合は None を返す。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  ANTHROPIC_API_KEY not set, skipping Claude analysis")
        return None

    try:
        import anthropic
    except ImportError:
        print("  anthropic package not installed, skipping Claude analysis")
        return None

    period_type = "週" if mode == "weekly" else "月"

    prompt = f"""\
あなたはAI業界のトレンドアナリストです。以下は{period_label}に収集されたAI関連記事の一覧です。
記事タイトル（日本語訳あり）とエンゲージメント指標をもとに、この{period_type}のAIトレンドを分析してください。

## 記事一覧
{articles_text}

## 出力形式（JSON）

以下の JSON 形式で厳密に出力してください。コードブロックは不要です。

{{
  "summary": "この{period_type}の全体的なAIトレンドを3〜5文で要約（日本語）",
  "trends": [
    {{
      "title": "トレンドのタイトル（例: LLMの商業化加速）",
      "description": "このトレンドについて2〜3文で説明（日本語）"
    }}
  ],
  "keywords": ["キーワード1", "キーワード2", "...（上位10個）"],
  "outlook": "来{period_type}の展望を1〜2文で（日本語）"
}}

トレンドは{"3〜5" if mode == "weekly" else "4〜7"}個程度抽出してください。
"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # JSONブロック抽出（```json ... ``` や ``` ... ``` を考慮）
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            raw = match.group(1).strip()

        result = json.loads(raw)
        print(f"  Claude analysis complete: {len(result.get('trends', []))} trends")
        return result
    except Exception as e:
        print(f"  Claude analysis failed: {e}")
        return None


# ---------- フォールバック: キーワード集計 ----------

IGNORE_WORDS = {
    "the", "a", "an", "and", "or", "for", "in", "on", "at", "to", "of",
    "is", "it", "as", "by", "be", "with", "from", "that", "this", "are",
    "was", "not", "but", "have", "has", "can", "its", "how", "why", "what",
    "new", "more", "using", "use", "used", "will", "than", "into", "your",
    "they", "their", "we", "our", "you", "he", "she", "his", "her", "us",
    "do", "does", "did", "been", "being", "had", "would", "could", "should",
    "so", "if", "when", "which", "who", "up", "out", "no", "vs", "via",
    "open", "now", "get", "got", "all", "just", "about", "after", "over",
}

AI_TERMS = {
    "llm", "gpt", "claude", "gemini", "openai", "anthropic", "deepseek",
    "llama", "mistral", "ai", "ml", "neural", "transformer", "diffusion",
    "rag", "agent", "model", "training", "inference", "benchmark", "fine-tuning",
    "langchain", "huggingface", "copilot", "chatgpt", "sora", "stable",
    "multimodal", "reasoning", "rlhf", "alignment", "safety",
}


def extract_keywords(items: list[dict], top_n: int = 15) -> list[tuple[str, int]]:
    """タイトルからキーワードを抽出して頻度でランキング。"""
    counter: Counter = Counter()
    for item in items:
        for field in ["title", "title_ja"]:
            text = item.get(field, "").lower()
            # 英単語・数字混じり語を抽出
            words = re.findall(r"[a-z][a-z0-9\-\.]*[a-z0-9]|[a-z]{3,}", text)
            for w in words:
                if w not in IGNORE_WORDS and len(w) >= 3:
                    counter[w] += 1

    # AI関連語を優先
    ai_counter = Counter({k: v for k, v in counter.items() if k in AI_TERMS})
    other_counter = Counter({k: v for k, v in counter.items() if k not in AI_TERMS})

    top = ai_counter.most_common(8) + other_counter.most_common(top_n - 8)
    # スコアで再ソート
    top.sort(key=lambda x: -x[1])
    return top[:top_n]


def get_top_articles(items: list[dict], source: str, n: int = 5) -> list[dict]:
    """ソース別スコア上位記事を返す。"""
    src_items = [i for i in items if i.get("source") == source]
    if source == "hackernews":
        src_items.sort(key=lambda x: x.get("score", 0), reverse=True)
    elif source == "hatena":
        src_items.sort(key=lambda x: x.get("bookmarks", 0), reverse=True)
    return src_items[:n]


# ---------- HTML 生成 ----------

def article_card_html(item: dict, depth: str = "../../") -> str:
    source = item.get("source", "")
    title = escape(item.get("title", ""))
    title_ja = escape(item.get("title_ja", ""))
    url = escape(item.get("url", "#"))
    score = item.get("score", "")
    bookmarks = item.get("bookmarks", "")
    hn_url = escape(item.get("hn_url", ""))

    display = title_ja if title_ja else title
    en_note = f'<div class="en-title">{title}</div>' if title_ja else ""

    meta_parts = []
    if score:
        meta_parts.append(f"&#9650; {score}")
    if bookmarks:
        meta_parts.append(f"&#128278; {bookmarks}")
    if hn_url:
        meta_parts.append(f'<a href="{hn_url}" target="_blank" style="color:var(--accent)">comments</a>')
    meta = " &middot; ".join(meta_parts)

    source_class = f"source-{source}" if source in ("hackernews", "hatena", "twitter") else ""
    source_labels = {"hackernews": "HN", "hatena": "Hatena", "twitter": "Twitter"}
    badge = f'<span class="source-badge {source_class}">{source_labels.get(source, source)}</span>' if source else ""

    return (
        f'<div class="article-card">'
        f"{badge}"
        f'<a href="{url}" target="_blank">{display}</a>'
        f"{en_note}"
        f'<div class="article-meta">{meta}</div>'
        f"</div>"
    )


def render_trend_items(trends: list[dict]) -> str:
    items_html = []
    for t in trends:
        title = escape(t.get("title", ""))
        desc = escape(t.get("description", ""))
        items_html.append(
            f'<div class="trend-item">'
            f'<div class="trend-title">{title}</div>'
            f'<div class="trend-desc">{desc}</div>'
            f"</div>"
        )
    return "\n".join(items_html)


def render_keywords(keywords: list) -> str:
    tags = []
    for kw in keywords:
        if isinstance(kw, tuple):
            word, count = kw
            tags.append(
                f'<span class="keyword-tag">{escape(word)}'
                f'<span class="kw-count">{count}</span></span>'
            )
        else:
            tags.append(f'<span class="keyword-tag">{escape(str(kw))}</span>')
    return f'<div class="keywords">{"".join(tags)}</div>'


def generate_weekly_html(
    period_label: str,
    items: list[dict],
    claude_result: dict | None,
    week_str: str,
) -> str:
    total = len(items)
    hn_count = sum(1 for i in items if i.get("source") == "hackernews")
    hatena_count = sum(1 for i in items if i.get("source") == "hatena")
    twitter_count = sum(1 for i in items if i.get("source") == "twitter")

    # 統計
    stats_html = (
        f'<div class="stats-grid">'
        f'<div class="stat-card"><div class="stat-number">{total}</div><div class="stat-label">総記事数</div></div>'
        f'<div class="stat-card"><div class="stat-number">{hn_count}</div><div class="stat-label">HN</div></div>'
        f'<div class="stat-card"><div class="stat-number">{hatena_count}</div><div class="stat-label">Hatena</div></div>'
        f'<div class="stat-card"><div class="stat-number">{twitter_count}</div><div class="stat-label">Twitter</div></div>'
        f"</div>"
    )

    if claude_result:
        summary_html = f'<div class="summary-box">{escape(claude_result.get("summary", ""))}</div>'
        trends_html = render_trend_items(claude_result.get("trends", []))
        kw_list = [(k, "") for k in claude_result.get("keywords", [])]
        keywords_html = render_keywords([(k, "") for k in claude_result.get("keywords", [])])
        # keyword-tag にカウントなしで表示
        kw_tags = "".join(
            f'<span class="keyword-tag">{escape(k)}</span>'
            for k in claude_result.get("keywords", [])
        )
        keywords_section = f'<div class="keywords">{kw_tags}</div>'
        outlook_html = f'<div class="summary-box">{escape(claude_result.get("outlook", ""))}</div>'
    else:
        summary_html = '<div class="summary-box">（Claude API キー未設定のため自動生成スキップ）</div>'
        trends_html = ""
        keywords_section = render_keywords(extract_keywords(items, 15))
        outlook_html = ""

    # HN / Hatena ランキング
    hn_top = get_top_articles(items, "hackernews", 5)
    hatena_top = get_top_articles(items, "hatena", 5)
    hn_cards = "\n".join(article_card_html(i) for i in hn_top) if hn_top else "<p>記事なし</p>"
    hatena_cards = "\n".join(article_card_html(i) for i in hatena_top) if hatena_top else "<p>記事なし</p>"

    trends_section = f"""
    <section>
      <h2>主要トレンド</h2>
      {trends_html if trends_html else '<p style="color:var(--muted)">Claude API キー未設定のためスキップ</p>'}
    </section>""" if claude_result else ""

    outlook_section = f"""
    <section>
      <h2>来週の展望</h2>
      {outlook_html}
    </section>""" if claude_result and claude_result.get("outlook") else ""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - 週次トレンドレポート {period_label}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../../index.html">AI Feed</a></h1>
    <span class="subtitle">週次トレンドレポート {period_label}</span>
  </div>
</header>
<main>
  <a href="../../index.html" class="back-link">&larr; Latest</a>

  <section>
    <h2>週間サマリー</h2>
    {stats_html}
    {summary_html}
  </section>

  {trends_section}

  <section>
    <h2>注目キーワード</h2>
    {keywords_section}
  </section>

  <section>
    <h2>HN 週間ランキング TOP5</h2>
    {hn_cards}
  </section>

  <section>
    <h2>Hatena 週間ランキング TOP5</h2>
    {hatena_cards}
  </section>

  {outlook_section}
</main>
</body>
</html>"""


def generate_monthly_html(
    period_label: str,
    items: list[dict],
    claude_result: dict | None,
    weekly_summaries: list[dict],
) -> str:
    total = len(items)
    hn_count = sum(1 for i in items if i.get("source") == "hackernews")
    hatena_count = sum(1 for i in items if i.get("source") == "hatena")
    twitter_count = sum(1 for i in items if i.get("source") == "twitter")

    stats_html = (
        f'<div class="stats-grid">'
        f'<div class="stat-card"><div class="stat-number">{total}</div><div class="stat-label">総記事数</div></div>'
        f'<div class="stat-card"><div class="stat-number">{hn_count}</div><div class="stat-label">HN</div></div>'
        f'<div class="stat-card"><div class="stat-number">{hatena_count}</div><div class="stat-label">Hatena</div></div>'
        f'<div class="stat-card"><div class="stat-number">{twitter_count}</div><div class="stat-label">Twitter</div></div>'
        f"</div>"
    )

    if claude_result:
        summary_html = f'<div class="summary-box">{escape(claude_result.get("summary", ""))}</div>'
        trends_html = render_trend_items(claude_result.get("trends", []))
        kw_tags = "".join(
            f'<span class="keyword-tag">{escape(k)}</span>'
            for k in claude_result.get("keywords", [])
        )
        keywords_section = f'<div class="keywords">{kw_tags}</div>'
        outlook_html = f'<div class="summary-box">{escape(claude_result.get("outlook", ""))}</div>'
    else:
        summary_html = '<div class="summary-box">（Claude API キー未設定のため自動生成スキップ）</div>'
        trends_html = ""
        keywords_section = render_keywords(extract_keywords(items, 20))
        outlook_html = ""

    # 週別サマリー
    week_sections = ""
    for ws in weekly_summaries:
        label = ws["label"]
        week_items = ws["items"]
        top2 = (get_top_articles(week_items, "hackernews", 2)
                + get_top_articles(week_items, "hatena", 1))[:2]
        top_cards = "\n".join(article_card_html(i, "../../") for i in top2)
        week_sections += (
            f'<div class="week-section">'
            f'<h3>{label}（{len(week_items)}記事）</h3>'
            f"{top_cards}"
            f"</div>"
        )

    # ランキング TOP10
    hn_top = get_top_articles(items, "hackernews", 10)
    hatena_top = get_top_articles(items, "hatena", 10)
    hn_cards = "\n".join(article_card_html(i, "../../") for i in hn_top) if hn_top else "<p>記事なし</p>"
    hatena_cards = "\n".join(article_card_html(i, "../../") for i in hatena_top) if hatena_top else "<p>記事なし</p>"

    trends_section = f"""
    <section>
      <h2>主要トレンド</h2>
      {trends_html if trends_html else '<p style="color:var(--muted)">Claude API キー未設定のためスキップ</p>'}
    </section>""" if claude_result else ""

    outlook_section = f"""
    <section>
      <h2>来月の展望</h2>
      {outlook_html}
    </section>""" if claude_result and claude_result.get("outlook") else ""

    week_section_block = f"""
    <section>
      <h2>週別サマリー</h2>
      {week_sections}
    </section>""" if weekly_summaries else ""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - 月次トレンドレポート {period_label}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../../index.html">AI Feed</a></h1>
    <span class="subtitle">月次トレンドレポート {period_label}</span>
  </div>
</header>
<main>
  <a href="../../index.html" class="back-link">&larr; Latest</a>

  <section>
    <h2>月間サマリー</h2>
    {stats_html}
    {summary_html}
  </section>

  {trends_section}

  <section>
    <h2>注目キーワード</h2>
    {keywords_section}
  </section>

  {week_section_block}

  <section>
    <h2>HN 月間ランキング TOP10</h2>
    {hn_cards}
  </section>

  <section>
    <h2>Hatena 月間ランキング TOP10</h2>
    {hatena_cards}
  </section>

  {outlook_section}
</main>
</body>
</html>"""


# ---------- エントリポイント ----------

def run_weekly(base_date: date) -> None:
    # 月曜始まりの週
    week_start = base_date - timedelta(days=base_date.weekday())
    week_end = week_start + timedelta(days=6)
    week_num = base_date.isocalendar()[1]
    period_label = f"{base_date.year}-W{week_num:02d}"
    print(f"Generating weekly report: {period_label} ({week_start} ~ {week_end})")

    items = load_daily_jsons(week_start, week_end)
    if not items:
        print("  No articles found, skipping")
        return
    print(f"  Loaded {len(items)} articles")

    articles_text = format_items_for_claude(items)
    claude_result = analyze_with_claude(articles_text, "weekly", period_label)

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = WEEKLY_DIR / f"{period_label}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(generate_weekly_html(period_label, items, claude_result, period_label))
    print(f"  Generated {out_path}")


def run_monthly(base_date: date) -> None:
    year = base_date.year
    month = base_date.month
    period_label = f"{year}-{month:02d}"

    # 月初〜当日（または月末）
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)
    # 当月分のみ（未来日は含めない）
    effective_end = min(month_end, base_date)

    print(f"Generating monthly report: {period_label} ({month_start} ~ {effective_end})")

    items = load_daily_jsons(month_start, effective_end)
    if not items:
        print("  No articles found, skipping")
        return
    print(f"  Loaded {len(items)} articles")

    # 週別サマリー構築
    weekly_summaries = []
    d = month_start
    while d <= effective_end:
        week_start = d - timedelta(days=d.weekday())
        week_end = min(week_start + timedelta(days=6), effective_end, month_end)
        week_num = d.isocalendar()[1]
        label = f"{year}-W{week_num:02d}"
        week_items = load_daily_jsons(max(week_start, month_start), week_end)
        if week_items:
            weekly_summaries.append({"label": label, "items": week_items})
        d = week_end + timedelta(days=1)

    articles_text = format_items_for_claude(items)
    claude_result = analyze_with_claude(articles_text, "monthly", period_label)

    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MONTHLY_DIR / f"{period_label}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(generate_monthly_html(period_label, items, claude_result, weekly_summaries))
    print(f"  Generated {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI トレンドレポート生成")
    parser.add_argument(
        "--mode", choices=["weekly", "monthly"], default="weekly",
        help="レポート種別（weekly / monthly）"
    )
    parser.add_argument(
        "--date", default=None,
        help="基準日 YYYY-MM-DD（省略時は今日）"
    )
    args = parser.parse_args()

    if args.date:
        base_date = date.fromisoformat(args.date)
    else:
        base_date = date.today()

    if args.mode == "weekly":
        run_weekly(base_date)
    else:
        run_monthly(base_date)


if __name__ == "__main__":
    main()
