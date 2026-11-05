# -*- coding: utf-8 -*-
"""
agent-skills-radar：专门检索 GitHub 上高 star、实用的 Agent 技能 / 工具插件。

- 周循环：以周一至周日为一周，同一仓库一周内只出现一次；每日只推「本周未出现」的新项目
- 主榜 stars>1000；新星观察 200~1000 且近 90 天活跃
- 输出：reports/YYYY-MM-DD.md（卡片式）+ reports/YYYY-MM-DD.html（美观卡片版）
- 周汇总：每周日额外生成 reports/week/YYYY-Www.md / .html 本周榜单
- 简介：免费翻译接口(MyMemory)把英文描述译为中文一句话，失败回退原文；结果缓存进周状态，周报复用
"""
import argparse
import html as _html
import json
import os
import sys
import time
import datetime as dt
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
REPORTS_DIR = BASE_DIR / "reports"
WEEK_DIR = REPORTS_DIR / "week"
STATE_PATH = REPORTS_DIR / "_week_state.json"
HTTP_TIMEOUT = 20
UA = "agent-skills-radar/1.0 (+https://github.com; personal tooling digest)"
_T_CACHE: dict[str, str] = {}


# ---------- 基础 ----------
def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def http_get(url: str, params: dict | None = None, retries: int = 3) -> requests.Response:
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    last_err = None
    for i in range(retries):
        try:
            return requests.get(url, params=params, headers=h, timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            last_err = e
            print(f"[warn] 请求失败({i + 1}/{retries})，重试: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))
    raise last_err  # type: ignore[misc]


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


# ---------- 周循环与状态 ----------
def today_cst() -> dt.date:
    return now_cst().date()


def week_bounds(d: dt.date) -> tuple[dt.date, dt.date]:
    """本周一到本周日。"""
    monday = d - dt.timedelta(days=d.weekday())
    return monday, monday + dt.timedelta(days=6)


def week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_range_text(mon: dt.date, sun: dt.date) -> str:
    return f"{mon.strftime('%m-%d')} ~ {sun.strftime('%m-%d')}"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] 读取周状态失败，按新周处理: {e}", file=sys.stderr)
    return {}


def save_state(st: dict) -> None:
    REPORTS_DIR.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def new_state(d: dt.date, prev_total: int) -> dict:
    mon, sun = week_bounds(d)
    return {
        "week": week_label(d),
        "start": mon.isoformat(),
        "end": sun.isoformat(),
        "prev_total": prev_total,
        "items": [],
    }


def state_to_item(s: dict) -> dict:
    """周状态条目 → 可复用的卡片数据（简介已在入库时确定，不再重复翻译）。"""
    return {
        "full_name": s["full_name"],
        "html_url": s["html_url"],
        "stargazers_count": s.get("stars", 0),
        "forks_count": s.get("forks", 0),
        "language": s.get("language"),
        "description": s.get("description", ""),
        "pushed_at": s.get("pushed_at", ""),
        "_intro": s.get("intro", ""),
    }


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


# ---------- 关键字检索（按 star 排名） ----------
def search_by_keyword(kw: str, limit: int, excludes: list[str]) -> list[dict] | None:
    """按关键字在名称/描述/topics 检索，按 star 降序返回。"""
    q = f"{kw} in:name,description,topics archived:false"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": limit}
    try:
        resp = http_get("https://api.github.com/search/repositories", params)
        if resp.status_code == 403:
            print("[warn] GitHub Search 限流(403)", file=sys.stderr)
            return None
        resp.raise_for_status()
        rows = []
        seen: set[str] = set()
        for it in resp.json().get("items", []):
            full = it["full_name"]
            if full in seen or excluded(it["name"], excludes):
                continue
            seen.add(full)
            rows.append(it)
        rows.sort(key=lambda x: x.get("stargazers_count", 0), reverse=True)
        return rows[:limit]
    except Exception as e:
        print(f"[warn] 关键字查询失败 ({kw}): {e}", file=sys.stderr)
        return []


# ---------- 聚合：每类多 query，本地分桶、跨类去重 ----------
def build_boards(cfg: dict, seen: set[str] | None = None) -> tuple[dict, dict]:
    seen = seen or set()
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
                # 本周已展示过的不再进入候选，保证一周七天不重复
                if full in seen or full in global_seen or full in bucket:
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
    cached = it.get("_intro")
    if cached:
        return cached
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
def md_card(it: dict, idx: int, extra: str = "") -> str:
    m = meta_of(it)
    fresh = " · 🟢近期活跃" if m["fresh"] else ""
    pushed = f" · 最近更新 {m['pushed_days']} 天前" if m["pushed_days"] is not None else ""
    intro = intro_of(it)
    return (
        f"#### {idx}. [{it['full_name']}]({it['html_url']})\n"
        f"⭐ {m['stars']} · 🍴 {m['forks']} · {m['lang']}{fresh}{extra}\n\n"
        f"> 📝 {intro}\n\n"
        f"🔗 [查看仓库]({it['html_url']}){pushed}\n"
    )


def render_md(date_str: str, main: dict, rising: dict, note: str = "") -> str:
    lines = [f"# Agent 技能 · 高星精选雷达 · {date_str}", ""]
    lines.append("> 专门检索 GitHub 高 star 的 Claude/Agent Skills 与 Agent 工具/插件，主榜门槛 stars>1000。")
    if note:
        lines.append(f"> {note}")
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


def html_card(it: dict, extra_html: str = "") -> str:
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
        <span class="badge lang">{esc(m['lang'])}</span>{extra_html}
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


def render_html(date_str: str, main: dict, rising: dict, note: str = "") -> str:
    main_html = "\n".join(section_html(cat, rows) for cat, rows in main.items())
    rise_html = "\n".join(section_html(cat, rows) for cat, rows in rising.items())
    note_html = f"<p>{esc(note)}</p>" if note else ""
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
    {note_html}
  </header>
  {main_html}
  {rise_html}
</div>
</body>
</html>"""


# ---------- 关键字检索渲染（扁平列表 · 按 star 排名） ----------
def render_md_search(kw: str, rows: list, date_str: str) -> str:
    lines = [f"# 关键字检索：{kw} · {date_str}", ""]
    lines.append(f"> 按 star 降序排名 · 共 {len(rows)} 条")
    lines.append("")
    for i, it in enumerate(rows, 1):
        lines.append(md_card(it, i))
    return "\n".join(lines)


def render_html_search(kw: str, rows: list, date_str: str) -> str:
    body = "\n".join(html_card(it) for it in rows)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>关键字检索 {kw} · {date_str}</title>
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
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
           padding:16px 16px 14px; display:flex; flex-direction:column; gap:10px; }}
  .card:hover {{ box-shadow:0 6px 20px rgba(79,110,247,.12); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
  .name {{ font-weight:700; font-size:15px; color:var(--ink); text-decoration:none; word-break:break-all; }}
  .name:hover {{ color:var(--accent); }}
  .badges {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .badge {{ font-size:12px; color:var(--sub); background:var(--bg); border-radius:999px; padding:3px 10px; }}
  .badge.fresh {{ color:#0a8f5b; background:#e6f6ee; }}
  .badge.lang {{ color:var(--accent); background:var(--accent-soft); }}
  .intro {{ margin:0; font-size:14px; color:#333845; flex:1; }}
  .card-foot {{ display:flex; justify-content:space-between; align-items:center; }}
  .muted {{ font-size:12px; color:var(--sub); }}
  .cta {{ font-size:13px; color:var(--accent); text-decoration:none; font-weight:600; }}
</style>
</head>
<body><div class="wrap">
  <header><h1>🔎 关键字检索：{esc(kw)}</h1>
  <p>{date_str} · 按 star 降序 · 共 {len(rows)} 条</p></header>
  <div class="grid">{body}
  </div>
</div></body></html>"""


# ---------- 每周汇总榜 ----------
def weekly_items(st: dict) -> list[dict]:
    """本周状态去重后的条目（按 star 降序）。"""
    uniq: dict[str, dict] = {}
    for s in st.get("items", []):
        uniq.setdefault(s["full_name"], s)
    return sorted(uniq.values(), key=lambda x: x.get("stars", 0), reverse=True)


def weekly_stats(st: dict) -> dict:
    items = weekly_items(st)
    main_cnt = sum(1 for s in items if s.get("board") == "main")
    rise_cnt = len(items) - main_cnt
    by_cat: dict[str, int] = {}
    for s in items:
        by_cat[s.get("category", "未分类")] = by_cat.get(s.get("category", "未分类"), 0) + 1
    return {
        "total": len(items), "main": main_cnt, "rising": rise_cnt,
        "prev_total": st.get("prev_total"),
        "days": len({s.get("date") for s in items if s.get("date")}),
        "by_cat": by_cat,
    }


def render_weekly_md(st: dict, top_n: int, top_rise: int) -> str:
    items = weekly_items(st)
    stats = weekly_stats(st)
    mon = dt.date.fromisoformat(st["start"])
    sun = dt.date.fromisoformat(st["end"])
    title_range = week_range_text(mon, sun)
    prev = f"（上周 {stats['prev_total']} 项）" if stats.get("prev_total") is not None else ""

    lines = [f"# 本周技能雷达汇总 · {st['week']}（{title_range}）", ""]
    lines.append(f"> 本周共收录 **{stats['total']}** 项{prev} · 主榜 {stats['main']} · 新星 {stats['rising']} · "
                 f"覆盖 {stats['days']} 天 · 同一仓库一周只出现一次")
    lines.append("")
    lines.append("## 📊 分类分布")
    lines.append("")
    lines.append("| 分类 | 收录数 |")
    lines.append("| --- | --- |")
    for cat, n in sorted(stats["by_cat"].items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {n} |")
    lines.append("")

    lines.append(f"## 🏆 本周 Top {min(top_n, len(items))}（按 star 降序）")
    lines.append("")
    for i, s in enumerate(items[:top_n], 1):
        lines.append(md_card(state_to_item(s), i, f" · 收录于 {s.get('date','')[:10][5:]}"))

    rise = [s for s in items if s.get("board") == "rising"][:top_rise]
    if rise:
        lines.append(f"## 🌱 本周新星 Top {len(rise)}（200~1000 star · 近 90 天活跃）")
        lines.append("")
        for i, s in enumerate(rise, 1):
            lines.append(md_card(state_to_item(s), i, f" · 收录于 {s.get('date','')[:10][5:]}"))

    lines.append("---")
    lines.append("_下周一开始新一轮，本周已上榜的项目下周一前不会重复出现；周日自动生成此汇总。_")
    return "\n".join(lines)


def render_weekly_html(st: dict, top_n: int, top_rise: int) -> str:
    items = weekly_items(st)
    stats = weekly_stats(st)
    mon = dt.date.fromisoformat(st["start"])
    sun = dt.date.fromisoformat(st["end"])
    title_range = week_range_text(mon, sun)
    prev = f"（上周 {stats['prev_total']} 项）" if stats.get("prev_total") is not None else ""

    def cards(rows: list[dict]) -> str:
        return "\n".join(
            html_card(state_to_item(s), f'<span class="badge day">📅 {esc(s.get("date","")[:10][5:])}</span>')
            for s in rows
        )

    rise = [s for s in items if s.get("board") == "rising"][:top_rise]
    cat_rows = "\n".join(
        f'<tr><td>{esc(cat)}</td><td>{n}</td></tr>'
        for cat, n in sorted(stats["by_cat"].items(), key=lambda x: -x[1])
    )
    rise_block = f"""
    <section>
      <h2>🌱 本周新星 Top {len(rise)}（200~1000 star · 近 90 天活跃）</h2>
      <div class="grid">{cards(rise)}
      </div>
    </section>""" if rise else ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>本周技能雷达汇总 · {st['week']}</title>
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
  .stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:6px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; text-align:center; }}
  .stat b {{ display:block; font-size:24px; color:var(--accent); }}
  .stat span {{ font-size:13px; color:var(--sub); }}
  h2 {{ font-size:17px; margin:26px 0 12px; padding-left:10px; border-left:4px solid var(--accent); }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:12px; overflow:hidden; }}
  th, td {{ text-align:left; padding:10px 14px; border-bottom:1px solid var(--line); font-size:14px; }}
  th {{ background:var(--accent-soft); color:var(--accent); font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
           padding:16px 16px 14px; display:flex; flex-direction:column; gap:10px; }}
  .card:hover {{ box-shadow:0 6px 20px rgba(79,110,247,.12); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
  .name {{ font-weight:700; font-size:15px; color:var(--ink); text-decoration:none; word-break:break-all; }}
  .name:hover {{ color:var(--accent); }}
  .badges {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .badge {{ font-size:12px; color:var(--sub); background:var(--bg); border-radius:999px; padding:3px 10px; }}
  .badge.fresh {{ color:#0a8f5b; background:#e6f6ee; }}
  .badge.lang {{ color:var(--accent); background:var(--accent-soft); }}
  .badge.day {{ color:#9a6b00; background:#fff4dd; }}
  .intro {{ margin:0; font-size:14px; color:#333845; flex:1; }}
  .card-foot {{ display:flex; justify-content:space-between; align-items:center; }}
  .muted {{ font-size:12px; color:var(--sub); }}
  .cta {{ font-size:13px; color:var(--accent); text-decoration:none; font-weight:600; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📅 本周技能雷达汇总 · {st['week']}</h1>
    <p>{title_range} · 本周收录 {stats['total']} 项{prev} · 同一仓库一周只出现一次</p>
  </header>
  <div class="stats">
    <div class="stat"><b>{stats['total']}</b><span>本周收录</span></div>
    <div class="stat"><b>{stats['main']}</b><span>高星主榜</span></div>
    <div class="stat"><b>{stats['rising']}</b><span>新星观察</span></div>
    <div class="stat"><b>{stats['days']}</b><span>覆盖天数</span></div>
  </div>
  <section>
    <h2>📊 分类分布</h2>
    <table><thead><tr><th>分类</th><th>收录数</th></tr></thead><tbody>{cat_rows}</tbody></table>
  </section>
  <section>
    <h2>🏆 本周 Top {min(top_n, len(items))}（按 star 降序）</h2>
    <div class="grid">{cards(items[:top_n])}
    </div>
  </section>{rise_block}
</div>
</body>
</html>"""


def write_weekly(st: dict, top_n: int, top_rise: int) -> Path:
    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    md_path = WEEK_DIR / f"{st['week']}.md"
    html_path = WEEK_DIR / f"{st['week']}.html"
    md_path.write_text(render_weekly_md(st, top_n, top_rise), encoding="utf-8")
    html_path.write_text(render_weekly_html(st, top_n, top_rise), encoding="utf-8")
    print(f"✓ 周汇总已生成: reports/week/{st['week']}.md / .html")
    return md_path


# ---------- 主流程 ----------
def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 技能雷达：自动精选 / 关键字检索")
    parser.add_argument("--kw", default=os.environ.get("SKILL_KEYWORD", "").strip(),
                        help="按关键字检索技能，按 star 排名；留空则跑每日自动榜")
    parser.add_argument("--limit", type=int,
                        default=int(os.environ.get("SKILL_LIMIT", "20") or 20),
                        help="关键字检索返回条数，默认 20")
    args = parser.parse_args()

    cfg = load_config()
    today = now_cst().strftime("%Y-%m-%d")
    REPORTS_DIR.mkdir(exist_ok=True)

    # —— 关键字检索模式（命令行 --kw 或表单 SKILL_KEYWORD）——
    if args.kw:
        import re as _re
        safe = _re.sub(r"[^\w\u4e00-\u9fa5]+", "_", args.kw).strip("_") or "query"
        rows = search_by_keyword(args.kw, args.limit, cfg["github"].get("exclude_name", []))
        if rows is None:
            print("✗ 查询被限流，请稍后重试或配置 GH_TOKEN", file=sys.stderr)
            sys.exit(1)
        search_dir = REPORTS_DIR / "search"
        search_dir.mkdir(exist_ok=True)
        (search_dir / f"{today}_{safe}.md").write_text(render_md_search(args.kw, rows, today), encoding="utf-8")
        (search_dir / f"{today}_{safe}.html").write_text(render_html_search(args.kw, rows, today), encoding="utf-8")
        print(f"✓ 关键字「{args.kw}」检索完成: reports/search/{today}_{safe}.md / .html")
        return

    # —— 默认：每日自动榜（周循环，一周内不重复）——
    d = today_cst()
    today_str = d.isoformat()
    label = week_label(d)
    mon, sun = week_bounds(d)
    wk_cfg = cfg.get("weekly", {})
    top_n = int(wk_cfg.get("top_n", 20))
    top_rise = int(wk_cfg.get("top_rising", 10))

    st = load_state()

    # 跨周：若上一周还有数据、但周报缺失，先补生成上周汇总
    if st.get("week") and st["week"] != label and st.get("items"):
        prev_md = WEEK_DIR / f"{st['week']}.md"
        if not prev_md.exists():
            write_weekly(st, top_n, top_rise)
            print(f"   ↳ 已补生成上周汇总 {st['week']}")
        prev_total = len({s["full_name"] for s in st["items"]})
    else:
        prev_total = st.get("prev_total") if st.get("week") == label else None

    if st.get("week") != label:
        st = new_state(d, prev_total)
        print(f"✓ 进入新的一周 {label}（{week_range_text(mon, sun)}），计数已清零")

    seen = {s["full_name"] for s in st["items"] if s.get("date") != today_str}
    # 同日重跑（含手动重触发）时只保留往日记录，今日重新生成，避免同一份日报被叠加替换成不同内容
    st["items"] = [s for s in st["items"] if s.get("date") != today_str]
    main_board, rise_board = build_boards(cfg, seen)

    # 记录今日新增条目，供后续几天排重与周日汇总使用
    added = 0
    for cat, rows in main_board.items():
        for it in rows:
            st["items"].append({
                "full_name": it["full_name"],
                "html_url": it["html_url"],
                "stars": it.get("stargazers_count", 0),
                "forks": it.get("forks_count", 0),
                "language": it.get("language") or "",
                "description": (it.get("description") or "").strip(),
                "intro": intro_of(it),
                "pushed_at": it.get("pushed_at", ""),
                "category": cat,
                "board": "main",
                "date": today_str,
            })
            added += 1
    for cat, rows in rise_board.items():
        for it in rows:
            st["items"].append({
                "full_name": it["full_name"],
                "html_url": it["html_url"],
                "stars": it.get("stargazers_count", 0),
                "forks": it.get("forks_count", 0),
                "language": it.get("language") or "",
                "description": (it.get("description") or "").strip(),
                "intro": intro_of(it),
                "pushed_at": it.get("pushed_at", ""),
                "category": cat,
                "board": "rising",
                "date": today_str,
            })
            added += 1
    save_state(st)

    day_idx = d.weekday() + 1
    note = (f"本周（{week_range_text(mon, sun)}）第 {day_idx}/7 天 · 今日新增 {added} 项 · "
            f"本周已累计 {len({s['full_name'] for s in st['items']})} 项（同一仓库一周只出现一次）")

    (REPORTS_DIR / f"{today}.md").write_text(render_md(today, main_board, rise_board, note), encoding="utf-8")
    (REPORTS_DIR / f"{today}.html").write_text(render_html(today, main_board, rise_board, note), encoding="utf-8")
    print(f"✓ 榜单已生成: reports/{today}.md / .html（今日新增 {added} 项）")

    # 周日（本周最后一天）出周汇总；也支持 FORCE_WEEKLY=1 手动补出
    force_weekly = os.environ.get("FORCE_WEEKLY", "").strip() in ("1", "true", "True", "yes")
    if d.weekday() == 6 or force_weekly:
        write_weekly(st, top_n, top_rise)


if __name__ == "__main__":
    main()
