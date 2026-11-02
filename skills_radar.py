# -*- coding: utf-8 -*-
"""
agent-skills-radar：专门检索 GitHub 上高 star、实用的 Agent 技能 / 工具插件。

数据源：GitHub Search API（按 stars 排序，本地关键词二次打分去噪、分桶）。
- 主榜：stars >= github.min_stars（默认 1000）
- 新星观察：rising.min_stars(200) ~ 主榜门槛，且近 rising.active_days 活跃
每个 query 只搜一次（stars:>rising_min），本地分桶，减少未认证请求次数。
输出：reports/YYYY-MM-DD.md；未配置 GH_TOKEN 走未认证限额（10 次/分）。
"""
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


# ---------- 渲染 ----------
def fmt_row(it: dict) -> str:
    name = it["full_name"]
    url = it["html_url"]
    stars = it.get("stargazers_count", 0)
    forks = it.get("forks_count", 0)
    lang = it.get("language") or "—"
    desc = (it.get("description") or "（无描述）").strip().replace("|", "/")
    d = days_since(it.get("pushed_at", ""))
    fresh = " 🟢近期活跃" if (d is not None and d <= 180) else ""
    pushed = f"最近更新 {int(d)} 天前" if d is not None else ""
    return (f"- **[{name}]({url})** ⭐{stars}｜🍴{forks}｜{lang}{fresh}\n"
             f"  - {desc}\n"
             f"  - {pushed}")


def render(date_str: str, main: dict, rising: dict) -> str:
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
        for it in rows:
            lines.append(fmt_row(it))
        lines.append("")
    if not any_main:
        lines.append("_今日主榜无满足门槛的项目（该生态较新，可看下方新星观察）。_")
        lines.append("")

    any_rise = any(rows for rows in rising.values())
    if any_rise:
        lines.append("## 二、新星观察（200~1000 star · 近 90 天活跃）")
        for cat, rows in rising.items():
            if not rows:
                continue
            lines.append(f"### {cat}")
            for it in rows:
                lines.append(fmt_row(it))
            lines.append("")
    return "\n".join(lines)


# ---------- 主流程 ----------
def main() -> None:
    cfg = load_config()
    today = now_cst().strftime("%Y-%m-%d")
    REPORTS_DIR.mkdir(exist_ok=True)

    main_board, rise_board = build_boards(cfg)
    md = render(today, main_board, rise_board)
    out = REPORTS_DIR / f"{today}.md"
    out.write_text(md, encoding="utf-8")
    print(f"✓ 榜单已生成: {out}")


if __name__ == "__main__":
    main()
