# -*- coding: utf-8 -*-
"""
agent-skills-radar：专门检索 GitHub 上高 star、实用的 Agent 技能 / 工具插件。

- 主榜 stars>1000；新星观察 200~1000 且近 90 天活跃
- 输出：reports/YYYY-MM-DD.md（卡片式）+ reports/YYYY-MM-DD.html（美观卡片版）
- 简介：免费翻译接口(MyMemory)把英文描述译为中文一句话，失败回退原文
"""
import html as _html
import json
import os
import sys
import datetime as dt
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
REPORTS_DIR = BASE_DIR / "reports"
HTTP_TIMEOUT = 20
UA = "agent-skills-radar/1.0 (+https://github.com; personal tooling digest)"
_T_CACHE: dict[str, str] = {}


# ---------- 基础 ----------
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def http_get(url: str, params: dict | None = None) -> requests.Response:
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.get(url, params=params, headers=h, timeout=HTTP_TIMEOUT)


def now_cst() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)


def hit_score(text: str, keywords: list[str]) -> int:
    t = text.lower()
    return sum(1 for k in keywords if k.lower() in t)


def days_since(pushed: str) -> float | None:
    try:
        d = dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        return (dt.datetime.now(dt.timezone.utc) - d).total_seconds() / 86400
    except Exception:
        return None


# ---------- 免费中文翻译 ----------
def translate_zh(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if text in _T_CACHE:
        return _T_CACHE[text]
    src = text[:220]
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": src, "langpair": "en|zh-CN"}, timeout=HTTP_TIMEOUT,
        )
        j = r.json()
        out = j.get("responseData", {}).get("translatedText", "")
        if out and j.get("responseStatus") == 200:
            _T_CACHE[text] = out
            return out
    except Exception as e:
        print(f"[warn] 翻译失败，回退原文: {e}", file=sys.stderr)
    _T_CACHE[text] = text
    return text


# ---------- GitHub 搜索 ----------
def search_github(query: str, min_stars: int, per_page: int) -> list[dict] | None:
    q = f"{query} stars:>{min_stars} archived:false"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": per_page}
    try:
        resp = http_get("https://api.github.com/search/repositories", params)
        if resp.status_code == 403:
            print("[warn] GitHub Search 限流(403)，停止后续请求", file=sys.stderr)
            return None
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception as e:
        print(f"[warn] 查询失败 ({query}): {e}", file=sys.stderr)
        return []


def repo_text(item: dict) -> str:
    topics = " ".join(item.get("topics") or [])
    return " ".join([item.get("name") or "", item.get("description") or "", topics])


def excluded(name: str, excludes: list[str]) -> bool:
    n = name.lower()
    return any(x in n for x in excludes)


# ---------- 聚合：每类多 query，本地分桶、跨类去重 ----------
def build_boards(cfg: dict) -> tuple[dict, dict]:
    g = cfg["github"]
    rise = cfg["rising"]
    min_star = g["min_stars"]
    rise_min = rise["min_stars"]
    excludes = g.get("exclude_name", [])

    main_board: dict[str, list] = {}
    rise_board: dict[str, list] = {}
    global_seen: set[str] = set()

    for cat in cfg["categories"]:
        bucket: dict[str, dict] = {}
        for q in cat["queries"]:
            items = search_github(q, rise_min, g["per_query"])
            if items is None:
                break
            for it in items:
                full = it["full_name"]
                if full in global_seen or full in bucket:
                    continue
                if excluded(it["name"], excludes):
                    continue
                score = hit_score(repo_text(it), cat["keywords"])
                if score == 0:
                    continue
                it["_score"] = score
                bucket[full] = it

        main_rows, rise_rows = [], []
        for it in bucket.values():
            star = it.get("stargazers_count", 0)
            if star >= min_star:
                main_rows.append(it)
            elif star >= rise_min:
                rise_rows.append(it)
            global_seen.add(it["full_name"])

        def sort_key(it: dict) -> tuple:
            d = days_since(it.get("pushed_at", ""))
            fresh = 1 if (d is not None and d <= g["active_days"]) else 0
            return (fresh, it.get("stargazers_count", 0))

        main_rows.sort(key=sort_key, reverse=True)
        rise_rows.sort(key=sort_key, reverse=True)
        main_board[cat["name"]] = main_rows[: g["max_per_topic"]]
        rise_board[cat["name"]] = rise_rows[: rise["max_per_topic"]]

    return main_board, rise_board


# ---------- 格式化 ----------
def fmt_stars(n: int) -> str:
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)


def intro_of(it: dict) -> str:
    desc = (it.get("description") or "").strip()
    return translate_zh(desc) if desc else translate_zh(it.get("name", ""))


def meta_of(it: dict) -> dict:
    d = days_since(it.get("pushed_at", ""))
    return {
        "stars": fmt_stars(it.get("stargazers_count", 0)),
        "forks": fmt_stars(it.get("forks_count", 0)),
        "lang": it.get("language") or "—",
        "fresh": d is not None and d <= 180,
        "pushed_days": int(d) if d is not None else None,
    }


# ---------- Markdown 卡片 ----------
def md_card(it: dict, idx: int) -> str:
    m = meta_of(it)
    fresh = " · 🟢近期活跃" if m["fresh"] else ""
    pushed = f" · 最近更新 {m['pushed_days']} 天前" if m["pushed_days"] is not None else ""
    intro = intro_of(it)
    return (
        f"#### {idx}. [{it['full_name']}]({it['html_url']})\n"
        f"⭐ {m['stars']} · 🍴 {m['forks']} · {m['lang']}{fresh}\n\n"
        f"> 📝 {intro}\n\n"
        f"🔗 [查看仓库]({it['html_url']}){pushed}\n"
    )


def render_md(date_str: str, main: dict, rising: dict) -> str:
    lines = [f"# Agent 技能 · 高星精选雷达 · {date_str}", ""]
    lines.append("> 专门检索 GitHub 高 star 的 Claude/Agent Skills 与 Agent 工具/插件，主榜门槛 stars>1000。")
    lines.append("")

    lines.append("## 一、高星主榜（stars > 1000）")
    any_main = False
    for cat, rows in main.items():
        if not rows:
            continue
        any_main = True
        lines.append(f"### {cat}")
        for i, it in enumerate(rows, 1):
            lines.append(md_card(it, i))
    if not any_main:
        lines.append("_今日主榜无满足门槛的项目（可看下方新星观察）。_")
        lines.append("")

    any_rise = any(rows for rows in rising.values())
    if any_rise:
        lines.append("## 二、新星观察（200~1000 star · 近 90 天活跃）")
        for cat, rows in rising.items():
            if not rows:
                continue
            lines.append(f"### {cat}")
            for i, it in enumerate(rows, 1):
                lines.append(md_card(it, i))
    return "\n".join(lines)


# ---------- HTML 卡片版 ----------
def esc(s: str) -> str:
    return _html.escape(str(s), quote=True)


def html_card(it: dict) -> str:
    m = meta_of(it)
    intro = intro_of(it)
    fresh = '<span class="badge fresh">🟢 近期活跃</span>' if m["fresh"] else ""
    pushed = f"最近更新 {m['pushed_days']} 天前" if m["pushed_days"] is not None else ""
    return f"""
    <article class="card">
      <div class="card-head">
        <a class="name" href="{esc(it['html_url'])}">{esc(it['full_name'])}</a>
        {fresh}
      </div>
      <div class="badges">
        <span class="badge">⭐ {m['stars']}</span>
        <span class="badge">🍴 {m['forks']}</span>
        <span class="badge lang">{esc(m['lang'])}</span>
      </div>
      <p class="intro">📝 {esc(intro)}</p>
      <div class="card-foot">
        <span class="muted">{esc(pushed)}</span>
        <a class="cta" href="{esc(it['html_url'])}">访问仓库 →</a>
      </div>
    </article>"""


def section_html(title: str, rows: list) -> str:
    if not rows:
        return ""
    body = "\n".join(html_card(it) for it in rows)
    return f"""
    <section>
      <h2>{esc(title)}</h2>
      <div class="grid">{body}
      </div>
    </section>"""


def render_html(date_str: str, main: dict, rising: dict) -> str:
    main_html = "\n".join(section_html(cat, rows) for cat, rows in main.items())
    rise_html = "\n".join(section_html(cat, rows) for cat, rows in rising.items())
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent 技能雷达 · {date_str}</title>
<style>
  :root {{ --bg:#f4f6fb; --card:#fff; --ink:#1f2430; --sub:#6b7280; --line:#e7eaf2;
           --accent:#4f6ef7; --accent-soft:#eef1ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif; line-height:1.6; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:28px 18px 60px; }}
  header {{ background:linear-gradient(135deg,#4f6ef7,#7a5cf0); color:#fff;
            border-radius:18px; padding:26px 28px; margin-bottom:22px; }}
  header h1 {{ margin:0 0 6px; font-size:22px; }}
  header p {{ margin:0; opacity:.9; font-size:14px; }}
  h2 {{ font-size:17px; margin:26px 0 12px; padding-left:10px; border-left:4px solid var(--accent); }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
           padding:16px 16px 14px; display:flex; flex-direction:column; gap:10px;
           transition:box-shadow .15s; }}
  .card:hover {{ box-shadow:0 6px 20px rgba(79,110,247,.12); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
  .name {{ font-weight:700; font-size:15px; color:var(--ink); text-decoration:none; word-break:break-all; }}
  .name:hover {{ color:var(--accent); }}
  .badges {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .badge {{ font-size:12px; color:var(--sub); background:var(--bg);
            border-radius:999px; padding:3px 10px; }}
  .badge.fresh {{ color:#0a8f5b; background:#e6f6ee; }}
  .badge.lang {{ color:var(--accent); background:var(--accent-soft); }}
  .intro {{ margin:0; font-size:14px; color:#333845; flex:1; }}
  .card-foot {{ display:flex; justify-content:space-between; align-items:center; }}
  .muted {{ font-size:12px; color:var(--sub); }}
  .cta {{ font-size:13px; color:var(--accent); text-decoration:none; font-weight:600; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🎯 Agent 技能 · 高星精选雷达</h1>
    <p>{date_str} · 主榜 stars&gt;1000 · Claude/Agent Skills 与 Agent 工具/插件 · 每日自动更新</p>
  </header>
  {main_html}
  {rise_html}
</div>
</body>
</html>"""


# ---------- 主流程 ----------
def main() -> None:
    cfg = load_config()
    today = now_cst().strftime("%Y-%m-%d")
    REPORTS_DIR.mkdir(exist_ok=True)

    main_board, rise_board = build_boards(cfg)

    (REPORTS_DIR / f"{today}.md").write_text(render_md(today, main_board, rise_board), encoding="utf-8")
    (REPORTS_DIR / f"{today}.html").write_text(render_html(today, main_board, rise_board), encoding="utf-8")
    print(f"✓ 榜单已生成: reports/{today}.md / .html")


if __name__ == "__main__":
    main()
