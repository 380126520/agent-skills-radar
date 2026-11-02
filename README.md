<div align="center">

# 🎯 agent-skills-radar

### 每天自动精选 GitHub 上高 star、真正实用的 Agent 技能 / 工具插件

![version](https://img.shields.io/badge/version-1.0.0-4f6ef7)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB)
![Schedule](https://img.shields.io/badge/cron-每天%2008:50%20(CST)-4f6ef7)
![Cost](https://img.shields.io/badge/成本-零服务器%20·%20GitHub%20Actions-0a8f5b)
![Output](https://img.shields.io/badge/输出-Markdown%20+%20HTML-7a5cf0)

</div>

---

每天自动检索 GitHub，按 star 排序并本地关键词二次打分去噪，为你筛出 **Claude / Agent Skills** 与 **Agent 工具 / 插件** 两类高星实用项目；每条配**中文一句话简介**，同时产出卡片式 Markdown 与美观 HTML 两个版本。零服务器成本，跑在 GitHub Actions 上。

## ✨ 亮点

- 🥇 **高星主榜**：`stars > 1000`，成熟项目精选，不做水军清单
- 🌱 **新星观察**：`200~1000 star` 且近 90 天活跃，提前发现潜力新项目
- 🗂 **双分类**：Claude / Agent Skills、Agent 工具 / 插件，分开成榜
- 📝 **中文简介**：每条把英文描述自动译为中文一句话，一眼看懂是做什么的
- 🎨 **双版式**：`reports/YYYY-MM-DD.md`（归档）+ `YYYY-MM-DD.html`（浏览器卡片版）
- 🧹 **自动去噪**：跨仓去重、过滤 awesome 清单类、非归档、近期活跃优先
- 🔑 **免 Key 免付费**：无需 LLM API Key、无服务器、无数据库

## 📊 输出示例（HTML 卡片版）

> 浏览器打开 `reports/YYYY-MM-DD.html` 即为卡片式榜单：渐变标题栏、star/fork/语言徽章、中文简介、一键访问。

每条统一格式（Markdown 版）：

```markdown
#### 1. [anthropics/skills](https://github.com/anthropics/skills)
⭐ 186.5k · 🍴 22.0k · Python · 🟢近期活跃

> 📝 座席技能的公共存储库（官方 Claude Skills 仓库）

🔗 [查看仓库](https://github.com/anthropics/skills) · 最近更新 4 天前
```

## 🗂 目录结构

```
agent-skills-radar/
├── skills_radar.py            # 主脚本：抓取 → 打分去噪 → 去重 → 翻译简介 → md/HTML 渲染
├── config.json                # 检索词、star 门槛、每类数量、排除词
├── requirements.txt
├── reports/                   # 每日榜单 YYYY-MM-DD.md / .html
└── .github/workflows/skills.yml   # 每天定时（北京时间 08:50）
```

## 🚀 快速开始（Fork 部署）

1. Fork 本仓库到自己账号。
2. （可选）仓库 **Settings → Secrets and variables → Actions** 加 `GH_TOKEN`（认证后搜索限额 30 次/分，未认证 10 次/分；本工具 10 次查询刚好够用）。
3. **Settings → Actions → General → Workflow permissions** 选 `Read and write`（榜单要提交回仓库）。
4. Actions 页手动 `Run workflow` 验证；之后每天北京时间 **08:50** 自动跑，结果提交到 `reports/`。

```bash
# 本地运行（每日自动榜）
pip install -r requirements.txt
python skills_radar.py
# 产出 reports/YYYY-MM-DD.md 与 .html
```

## 🔎 按关键字检索（按 star 排名）

除每日自动榜外，可随时指定关键字检索，结果按 star 降序：

```bash
# 命令行：--kw 关键字，--limit 返回条数（默认 20）
python skills_radar.py --kw "mcp" --limit 20
# 产出 reports/search/YYYY-MM-DD_mcp.md / .html
```

**云端手动触发**：Actions 页 `Run workflow`，在 `keyword` 框填关键字（留空则跑每日自动榜），`limit` 填条数；结果存 `reports/search/`。

> 关键字越具体越准（如 `mcp server`、`claude skill`）；通用词会命中大量无关高星库。

## ⚙️ 配置（config.json）

| 字段 | 说明 |
|---|---|
| `github.min_stars` | 主榜 star 门槛，默认 `1000` |
| `github.max_per_topic` | 每类主榜最多收录条数 |
| `github.per_query` | 每个检索词取回条数 |
| `github.exclude_name` | 名称含这些词的仓库排除（如 `awesome` 清单） |
| `github.active_days` | 多少天内有更新算「近期活跃」并优先排序 |
| `categories[].queries` | 该类别在 GitHub 搜索用的主词（扩大召回） |
| `categories[].keywords` | 本地二次打分词，命中才收录（收紧/去噪） |
| `rising.min_stars / active_days / max_per_topic` | 新星观察门槛、活跃窗口、条数 |

> 想调整方向：改 `queries`（扩大召回）和 `keywords`（收紧匹配）即可，无需改代码。

## 📌 定时说明

工作流每天北京时间 **08:50** 自动运行，结果提交回 `reports/`；也可在 Actions 页手动 `Run workflow` 补跑。

## 📝 说明

- 中文简介由免费翻译接口生成，个别术语机翻略生硬；配了 LLM Key 可在脚本 `intro_of` 处替换为更精炼的人工式摘要。
- GitHub Search 未认证限额 10 次/分；若偶发限流导致条目变少，加 `GH_TOKEN` 即可。
