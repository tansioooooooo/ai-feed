#!/usr/bin/env python3
"""
daily/*.json を集計してトレンドレポートを生成する。
- docs/weekly/YYYY-WNN.html : 週次レポート（過去7日）
- docs/monthly/YYYY-MM.html : 月次レポート（当月全体）

呼び出し:
  python scripts/generate_trend_report.py [--date YYYY-MM-DD]
  --date を省略した場合は今日の日付を基準に生成
"""

import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent.parent
DAILY_DIR = ROOT / "docs" / "daily"
WEEKLY_DIR = ROOT / "docs" / "weekly"
MONTHLY_DIR = ROOT / "docs" / "monthly"

# ---------------------------------------------------------------------------
# AI関連の重要キーワード（ノイズ除外しやすくするため単語リストを明示）
# ---------------------------------------------------------------------------
STOP_WORDS = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or", "is",
    "it", "its", "with", "from", "by", "as", "be", "this", "that", "are",
    "was", "were", "has", "have", "had", "not", "no", "but", "if", "up",
    "do", "can", "will", "how", "why", "what", "when", "who", "you", "your",
    "we", "our", "they", "their", "about", "into", "via", "after", "before",
    "over", "more", "new", "use", "using", "used", "just", "get", "make",
    "than", "also", "all", "some", "any", "out", "now", "my", "one", "two",
    "first", "last", "may", "vs", "per", "so", "i", "me", "him", "her",
    "them", "us", "–", "-", "—", "like", "based", "does", "been", "much",
    "data", "year", "time", "long", "large", "made", "could", "would", "should",
    "while", "where", "other", "only", "even", "same", "both", "each",
    "most", "well", "here", "way", "back", "good", "better", "s", "don",
    "t", "re", "d", "ll", "ve", "show", "shows", "says", "say", "says",
    "know", "think", "need", "want", "help", "let", "look", "see", "try",
    "build", "open", "run", "find", "take", "keep", "set", "work", "works",
    "go", "goes", "give", "put", "then", "there", "than", "though", "through",
    "every", "own", "few", "many", "without", "those", "these", "which",
    "across", "still", "already", "always", "within", "between", "under",
    "around", "up", "down", "off", "yet", "once", "again", "later", "earlier",
    "next", "really", "actually", "top", "big", "small", "high", "low",
    "full", "free", "fast", "best", "real", "since", "while", "until",
}

# 重要AIキーワード（これらは必ず計上）
PRIORITY_KEYWORDS = {
    "claude", "gpt", "gemini", "llm", "llms", "openai", "anthropic", "deepseek",
    "mistral", "llama", "copilot", "chatgpt", "grok", "xai", "google", "microsoft",
    "apple", "meta", "nvidia", "amd", "intel", "hugging", "face", "huggingface",
    "rag", "agent", "agents", "mcp", "transformer", "diffusion", "multimodal",
    "reasoning", "coding", "code", "inference", "training", "fine-tuning",
    "finetuning", "benchmark", "alignment", "rlhf", "robotics", "robot",
    "vision", "audio", "voice", "text", "image", "video", "3d",
    "open-source", "opensource", "safety", "regulation", "copyright",
    "leak", "jailbreak", "prompt", "context", "window", "token", "tokens",
    "sora", "stable", "diffusion", "midjourney", "dall-e", "dalle",
    "cursor", "devin", "software", "engineering", "startup", "funding",
    "arxiv", "paper", "research", "model", "models", "weights",
}

CSS = """\
:root {
  --bg: #0f0f13;
  --surface: #1a1a22;
  --surface2: #22222e;
  --border: #2a2a38;
  --text: #e8e8f0;
  --muted: #7a7a9a;
  --accent: #7c6af7;
  --green: #4caf8a;
  --orange: #ff6600;
  --blue: #1d9bf0;
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
.header-top { display: flex; align-items: baseline; gap: 12px; margin-bottom: 4px; }
h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.3px; }
h1 a { color: var(--text); text-decoration: none; }
h1 a:hover { color: var(--accent); }
.period { font-size: 14px; color: var(--muted); }
.back-link {
  display: inline-block;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  margin-top: 8px;
}
.back-link:hover { text-decoration: underline; }
main { padding: 24px; max-width: 960px; }
section { margin-bottom: 36px; }
h2 {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}
h3 { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--muted); }

/* --- トレンドキーワード --- */
.keyword-cloud { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.keyword-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 13px;
}
.keyword-tag.rank1 { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.keyword-tag.rank2 { border-color: #5a52c0; color: #9d96f5; }
.keyword-count { color: var(--muted); font-size: 11px; }

/* --- ランキングリスト --- */
.rank-list { display: flex; flex-direction: column; gap: 8px; }
.rank-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  transition: border-color 0.15s;
}
.rank-item:hover { border-color: var(--accent); }
.rank-num {
  font-size: 18px;
  font-weight: 700;
  color: var(--muted);
  min-width: 28px;
  text-align: right;
  padding-top: 1px;
}
.rank-num.gold { color: #f5c542; }
.rank-num.silver { color: #b0b8c1; }
.rank-num.bronze { color: #cd7f32; }
.rank-body { flex: 1; min-width: 0; }
.rank-title {
  display: block;
  color: var(--text);
  text-decoration: none;
  font-weight: 500;
  font-size: 14px;
  margin-bottom: 4px;
  line-height: 1.4;
}
.rank-title:hover { color: var(--accent); }
.rank-title-ja {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 4px;
}
.rank-meta { font-size: 12px; color: var(--muted); }
.rank-score { color: var(--orange); font-weight: 600; }
.rank-bm { color: var(--blue); font-weight: 600; }
.rank-source {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--border);
  margin-left: 6px;
}

/* --- 統計サマリー --- */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  text-align: center;
}
.stat-num { font-size: 28px; font-weight: 700; color: var(--accent); }
.stat-label { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* --- 日別推移バー --- */
.daily-bars { display: flex; flex-direction: column; gap: 6px; }
.daily-bar-row { display: flex; align-items: center; gap: 10px; }
.daily-bar-label { font-size: 12px; color: var(--muted); min-width: 80px; }
.daily-bar-track {
  flex: 1;
  height: 18px;
  background: var(--surface2);
  border-radius: 4px;
  overflow: hidden;
}
.daily-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.3s;
}
.daily-bar-count { font-size: 12px; color: var(--muted); min-width: 36px; text-align: right; }

/* --- テーマ分析 --- */
.theme-list { display: flex; flex-direction: column; gap: 8px; }
.theme-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
}
.theme-name { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.theme-desc { font-size: 12px; color: var(--muted); }
.theme-count { font-size: 11px; color: var(--accent); margin-top: 4px; }

/* --- 週別セクション（月次用） --- */
.week-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.week-section h3 { color: var(--text); margin-bottom: 8px; }
.week-top-articles { font-size: 12px; color: var(--muted); }
.week-top-articles a { color: var(--accent); text-decoration: none; }
.week-top-articles a:hover { text-decoration: underline; }

@media (max-width: 600px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}"""


def load_daily_data(dates: list[str]) -> dict:
    """複数日分のdaily JSONを読み込んで統合する。"""
    all_items = {"hackernews": [], "hatena": [], "twitter": []}
    seen_urls = set()
    for d in dates:
        path = DAILY_DIR / f"{d}.json"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key in ["hackernews", "hatena", "twitter"]:
            for item in data.get(key, []):
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_items[key].append(item)
    return all_items


def extract_keywords(items: dict, top_n: int = 30) -> list[tuple[str, int]]:
    """全記事タイトルからキーワードを抽出して頻度順に返す。"""
    counter = Counter()
    for source_items in items.values():
        for item in source_items:
            title = item.get("title", "") + " " + item.get("title_ja", "")
            # 英数字の単語を抽出
            words = re.findall(r"[A-Za-z][A-Za-z0-9\-\.]*[A-Za-z0-9]|[A-Za-z]{2,}", title)
            for w in words:
                wl = w.lower()
                if wl in STOP_WORDS:
                    continue
                if len(wl) < 2:
                    continue
                counter[wl] += 1
    # 日本語カタカナ語も抽出（AI、LLM系の語は日本語でも多い）
    for source_items in items.values():
        for item in source_items:
            title_ja = item.get("title_ja", "")
            # カタカナ語（3文字以上）
            kata_words = re.findall(r"[ァ-ヶー]{3,}", title_ja)
            for w in kata_words:
                counter[w] += 1
    # 優先キーワードはスコア補正
    for kw in PRIORITY_KEYWORDS:
        if kw in counter:
            counter[kw] = int(counter[kw] * 1.2)
    return counter.most_common(top_n)


def categorize_trends(items: dict, keywords: list[tuple[str, int]]) -> list[dict]:
    """
    上位キーワードを元にトレンドカテゴリを識別する。
    簡易的なルールベース分類。
    """
    all_titles = []
    for source_items in items.values():
        for item in source_items:
            all_titles.append(item.get("title", "").lower() + " " + item.get("title_ja", ""))

    trend_rules = [
        {
            "name": "LLM・モデルリリース",
            "patterns": ["release", "launch", "model", "weights", "open-source", "opensource",
                         "llama", "gemini", "gpt", "claude", "mistral", "deepseek",
                         "リリース", "公開", "モデル"],
            "desc": "新しいAIモデルのリリースや公開に関する話題",
        },
        {
            "name": "AI規制・著作権・倫理",
            "patterns": ["regulation", "copyright", "legal", "policy", "ban", "safety", "ethics",
                         "legitimate", "lawsuit", "규제", "規制", "著作権", "倫理", "禁止"],
            "desc": "AI利用の法的・倫理的側面に関する議論",
        },
        {
            "name": "開発者ツール・コーディングAI",
            "patterns": ["coding", "code", "cursor", "copilot", "devin", "agent", "mcp",
                         "tool", "sdk", "api", "developer", "コーディング", "開発", "ツール"],
            "desc": "AIを活用した開発支援ツール・コーディングエージェントの話題",
        },
        {
            "name": "資金調達・ビジネス動向",
            "patterns": ["funding", "raises", "startup", "billion", "valuation", "investment",
                         "ipo", "acquisition", "資金調達", "スタートアップ", "億", "調達"],
            "desc": "AI企業の資金調達・買収・事業展開の動向",
        },
        {
            "name": "研究・論文",
            "patterns": ["arxiv", "paper", "research", "benchmark", "study", "university",
                         "training", "fine-tuning", "rlhf", "reasoning", "研究", "論文", "大学"],
            "desc": "AI研究論文・ベンチマーク・技術的知見",
        },
        {
            "name": "画像・動画・マルチモーダル",
            "patterns": ["image", "video", "vision", "multimodal", "sora", "diffusion",
                         "midjourney", "dalle", "3d", "画像", "動画", "マルチモーダル"],
            "desc": "画像生成・動画生成・マルチモーダルAIの話題",
        },
    ]

    results = []
    for rule in trend_rules:
        count = 0
        for title in all_titles:
            if any(p in title for p in rule["patterns"]):
                count += 1
        if count > 0:
            results.append({
                "name": rule["name"],
                "desc": rule["desc"],
                "count": count,
            })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:6]


def top_articles(items: dict, source: str, score_key: str, limit: int = 5) -> list[dict]:
    """指定ソースのトップ記事をスコア順に返す。"""
    src_items = items.get(source, [])
    scored = [(item.get(score_key, 0) or 0, item) for item in src_items]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def daily_counts(dates: list[str]) -> list[tuple[str, int]]:
    """日付ごとの記事数を返す。"""
    results = []
    for d in dates:
        path = DAILY_DIR / f"{d}.json"
        if not path.exists():
            results.append((d, 0))
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        count = sum(len(data.get(k, [])) for k in ["hackernews", "hatena", "twitter"])
        results.append((d, count))
    return results


def rank_num_html(rank: int) -> str:
    classes = {1: "gold", 2: "silver", 3: "bronze"}
    cls = classes.get(rank, "")
    if cls:
        return f'<span class="rank-num {cls}">{rank}</span>'
    return f'<span class="rank-num">{rank}</span>'


def article_card_html(rank: int, item: dict, score_key: str, score_label: str, score_css: str) -> str:
    title = escape(item.get("title", ""))
    title_ja = escape(item.get("title_ja", ""))
    url = escape(item.get("url", "#"))
    score = item.get(score_key, "")
    hn_url = escape(item.get("hn_url", ""))
    source = item.get("source", "")

    title_ja_html = f'<span class="rank-title-ja">{title_ja}</span>' if title_ja else ""
    score_html = f'<span class="{score_css}">{score_label} {score}</span>' if score else ""
    hn_html = f' · <a href="{hn_url}" target="_blank" style="color:var(--accent);font-size:11px">comments</a>' if hn_url else ""
    source_html = f'<span class="rank-source">{source}</span>' if source else ""

    return (
        f'<div class="rank-item">'
        f'{rank_num_html(rank)}'
        f'<div class="rank-body">'
        f'<a href="{url}" target="_blank" class="rank-title">{title}</a>'
        f'{title_ja_html}'
        f'<div class="rank-meta">{score_html}{hn_html}{source_html}</div>'
        f'</div></div>'
    )


def keyword_tags_html(keywords: list[tuple[str, int]]) -> str:
    parts = []
    for i, (word, count) in enumerate(keywords):
        cls = "rank1" if i == 0 else ("rank2" if i < 3 else "")
        cls_attr = f' class="keyword-tag {cls}"' if cls else ' class="keyword-tag"'
        parts.append(f'<span{cls_attr}>{escape(word)} <span class="keyword-count">{count}</span></span>')
    return '<div class="keyword-cloud">' + "\n".join(parts) + "</div>"


def bar_chart_html(bars: list[tuple[str, int]]) -> str:
    max_count = max((c for _, c in bars), default=1) or 1
    rows = []
    for label, count in bars:
        pct = int(count / max_count * 100)
        rows.append(
            f'<div class="daily-bar-row">'
            f'<span class="daily-bar-label">{escape(label)}</span>'
            f'<div class="daily-bar-track"><div class="daily-bar-fill" style="width:{pct}%"></div></div>'
            f'<span class="daily-bar-count">{count}</span>'
            f'</div>'
        )
    return '<div class="daily-bars">' + "\n".join(rows) + "</div>"


def theme_list_html(themes: list[dict]) -> str:
    parts = []
    for theme in themes:
        parts.append(
            f'<div class="theme-item">'
            f'<div class="theme-name">{escape(theme["name"])}</div>'
            f'<div class="theme-desc">{escape(theme["desc"])}</div>'
            f'<div class="theme-count">関連記事 {theme["count"]} 件</div>'
            f'</div>'
        )
    return '<div class="theme-list">' + "\n".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# 週次レポート生成
# ---------------------------------------------------------------------------

def generate_weekly_html(target_date: date) -> str:
    # ISO週番号を取得
    iso_year, iso_week, _ = target_date.isocalendar()
    # その週の月〜日
    week_monday = target_date - timedelta(days=target_date.weekday())
    week_dates = [(week_monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    week_label = f"{iso_year}-W{iso_week:02d}"
    period_label = f"{week_monday.strftime('%Y/%m/%d')} 〜 {(week_monday + timedelta(days=6)).strftime('%Y/%m/%d')}"

    items = load_daily_data(week_dates)
    total_hn = len(items["hackernews"])
    total_hatena = len(items["hatena"])
    total_twitter = len(items["twitter"])
    total = total_hn + total_hatena + total_twitter

    keywords = extract_keywords(items, top_n=25)
    themes = categorize_trends(items, keywords)
    top_hn = top_articles(items, "hackernews", "score", 5)
    top_hatena = top_articles(items, "hatena", "bookmarks", 5)
    bars = daily_counts(week_dates)

    # Ranking HTML
    hn_cards = "\n".join(
        article_card_html(i + 1, item, "score", "▲", "rank-score")
        for i, item in enumerate(top_hn)
    ) if top_hn else "<p style='color:var(--muted)'>データなし</p>"

    hatena_cards = "\n".join(
        article_card_html(i + 1, item, "bookmarks", "🔖", "rank-bm")
        for i, item in enumerate(top_hatena)
    ) if top_hatena else "<p style='color:var(--muted)'>データなし</p>"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - 週次トレンド {week_label}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../index.html">AI Feed</a></h1>
    <span class="period">週次トレンド {week_label}</span>
  </div>
  <div style="color:var(--muted);font-size:13px">{period_label}</div>
  <a href="../index.html" class="back-link">&larr; トップへ戻る</a>
</header>
<main>

  <!-- 集計サマリー -->
  <section>
    <h2>📊 週間サマリー</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{total}</div>
        <div class="stat-label">総記事数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_hn}</div>
        <div class="stat-label">Hacker News</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_hatena}</div>
        <div class="stat-label">はてな</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_twitter}</div>
        <div class="stat-label">Twitter</div>
      </div>
    </div>
    <h3>日別記事数</h3>
    {bar_chart_html(bars)}
  </section>

  <!-- トレンドキーワード -->
  <section>
    <h2>🔥 今週のホットキーワード</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">
      今週収集した記事タイトルから頻出キーワードを抽出しています。
    </p>
    {keyword_tags_html(keywords)}
  </section>

  <!-- トレンドテーマ -->
  <section>
    <h2>📌 今週のトレンドテーマ</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">
      記事内容を自動分類して今週のAI界隈のテーマを分析しました。
    </p>
    {theme_list_html(themes)}
  </section>

  <!-- HN トップ記事 -->
  <section>
    <h2>🟠 Hacker News 週間ランキング</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">スコア（upvote数）上位5件</p>
    <div class="rank-list">{hn_cards}</div>
  </section>

  <!-- Hatena トップ記事 -->
  <section>
    <h2>🔵 はてなブックマーク 週間ランキング</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">ブックマーク数上位5件</p>
    <div class="rank-list">{hatena_cards}</div>
  </section>

</main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 月次レポート生成
# ---------------------------------------------------------------------------

def get_month_dates(year: int, month: int) -> list[str]:
    """指定年月の全日付リストを返す。"""
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    return [
        date(year, month, d).strftime("%Y-%m-%d")
        for d in range(1, last_day + 1)
    ]


def get_weeks_in_month(year: int, month: int) -> list[tuple[str, list[str]]]:
    """月内の週ごとに日付リストを分けて返す。"""
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    weeks = {}
    for d in range(1, last_day + 1):
        dt = date(year, month, d)
        iso_year, iso_week, _ = dt.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        weeks.setdefault(key, [])
        weeks[key].append(dt.strftime("%Y-%m-%d"))
    return list(weeks.items())


def generate_monthly_html(year: int, month: int) -> str:
    month_label = f"{year}-{month:02d}"
    month_name_ja = ["", "1月", "2月", "3月", "4月", "5月", "6月",
                     "7月", "8月", "9月", "10月", "11月", "12月"][month]
    period_label = f"{year}年{month_name_ja}"

    month_dates = get_month_dates(year, month)
    items = load_daily_data(month_dates)
    total_hn = len(items["hackernews"])
    total_hatena = len(items["hatena"])
    total_twitter = len(items["twitter"])
    total = total_hn + total_hatena + total_twitter

    keywords = extract_keywords(items, top_n=30)
    themes = categorize_trends(items, keywords)
    top_hn = top_articles(items, "hackernews", "score", 10)
    top_hatena = top_articles(items, "hatena", "bookmarks", 10)
    bars = daily_counts(month_dates)

    # 週ごとのサマリー
    weeks = get_weeks_in_month(year, month)
    week_sections_html = ""
    for week_label, week_dates in weeks:
        w_items = load_daily_data(week_dates)
        w_total = sum(len(w_items[k]) for k in ["hackernews", "hatena", "twitter"])
        w_top_hn = top_articles(w_items, "hackernews", "score", 2)
        w_top_hatena = top_articles(w_items, "hatena", "bookmarks", 2)
        top_list = []
        for item in w_top_hn + w_top_hatena:
            title = escape(item.get("title_ja") or item.get("title", ""))
            url = escape(item.get("url", "#"))
            top_list.append(f'<li><a href="{url}" target="_blank">{title}</a></li>')
        top_html = f"<ul style='margin:4px 0 0 16px'>{''.join(top_list)}</ul>" if top_list else ""
        week_sections_html += (
            f'<div class="week-section">'
            f'<h3>{week_label}（{w_total}件）</h3>'
            f'<div class="week-top-articles">{top_html}</div>'
            f'</div>'
        )

    hn_cards = "\n".join(
        article_card_html(i + 1, item, "score", "▲", "rank-score")
        for i, item in enumerate(top_hn)
    ) if top_hn else "<p style='color:var(--muted)'>データなし</p>"

    hatena_cards = "\n".join(
        article_card_html(i + 1, item, "bookmarks", "🔖", "rank-bm")
        for i, item in enumerate(top_hatena)
    ) if top_hatena else "<p style='color:var(--muted)'>データなし</p>"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Feed - 月次レポート {period_label}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1><a href="../index.html">AI Feed</a></h1>
    <span class="period">月次レポート {period_label}</span>
  </div>
  <a href="../index.html" class="back-link">&larr; トップへ戻る</a>
</header>
<main>

  <!-- 月間サマリー -->
  <section>
    <h2>📊 {period_label} サマリー</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-num">{total}</div>
        <div class="stat-label">総記事数</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_hn}</div>
        <div class="stat-label">Hacker News</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_hatena}</div>
        <div class="stat-label">はてな</div>
      </div>
      <div class="stat-card">
        <div class="stat-num">{total_twitter}</div>
        <div class="stat-label">Twitter</div>
      </div>
    </div>
    <h3>日別記事数</h3>
    {bar_chart_html(bars)}
  </section>

  <!-- トレンドキーワード -->
  <section>
    <h2>🔥 今月のホットキーワード</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">
      今月収集した全記事タイトルから頻出キーワードを抽出しています。
    </p>
    {keyword_tags_html(keywords)}
  </section>

  <!-- トレンドテーマ -->
  <section>
    <h2>📌 今月のトレンドテーマ</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">
      記事内容を自動分類して今月のAI界隈の主要テーマを分析しました。
    </p>
    {theme_list_html(themes)}
  </section>

  <!-- 週別サマリー -->
  <section>
    <h2>📅 週別サマリー</h2>
    {week_sections_html}
  </section>

  <!-- HN トップ10 -->
  <section>
    <h2>🟠 Hacker News 月間ランキング TOP10</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">スコア（upvote数）上位10件</p>
    <div class="rank-list">{hn_cards}</div>
  </section>

  <!-- Hatena トップ10 -->
  <section>
    <h2>🔵 はてなブックマーク 月間ランキング TOP10</h2>
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">ブックマーク数上位10件</p>
    <div class="rank-list">{hatena_cards}</div>
  </section>

</main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="トレンドレポートを生成する")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="基準日 YYYY-MM-DD（デフォルト: 今日）",
    )
    parser.add_argument(
        "--weekly-only",
        action="store_true",
        help="週次レポートのみ生成",
    )
    parser.add_argument(
        "--monthly-only",
        action="store_true",
        help="月次レポートのみ生成",
    )
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    iso_year, iso_week, _ = target.isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"
    month_label = target.strftime("%Y-%m")

    generate_weekly = not args.monthly_only
    generate_monthly = not args.weekly_only

    if generate_weekly:
        WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
        html = generate_weekly_html(target)
        out_path = WEEKLY_DIR / f"{week_label}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated weekly report: {out_path}")

    if generate_monthly:
        MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
        html = generate_monthly_html(target.year, target.month)
        out_path = MONTHLY_DIR / f"{month_label}.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Generated monthly report: {out_path}")


if __name__ == "__main__":
    main()
