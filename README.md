# agent-skills-radar

专门检索 GitHub 上 **高 star、实用的 Agent 技能 / 工具插件** 的每日精选工具。

- 主榜门槛：`stars > 1000`（成熟高星，精选）
- 新星观察：`200 ~ 1000 star` 且近 90 天活跃（发现有潜力的新项目）
- 覆盖两类：**Claude / Agent Skills**、**Agent 工具 / 插件**
- 数据源：GitHub Search API（按 star 排序，本地关键词二次打分去噪、跨仓去重、非归档、近期活跃优先）

## 目录结构

```
agent-skills-radar/
├── skills_radar.py      # 主脚本
├── config.json          # 检索词、star 门槛、每类数量、排除词
├── requirements.txt
├── reports/             # 每日生成的榜单 YYYY-MM-DD.md
└── .github/workflows/skills.yml   # 每天定时（北京时间 08:50）
```

## 本地运行

```bash
pip install -r requirements.txt
python skills_radar.py
# 产出 reports/YYYY-MM-DD.md
```

可选：设置环境变量 `GH_TOKEN`（认证后搜索限额 30 次/分，未认证仅 10 次/分）。

## 配置（config.json）

| 字段 | 说明 |
|---|---|
| `github.min_stars` | 主榜 star 门槛，默认 1000 |
| `github.max_per_topic` | 每类主榜最多收录条数 |
| `github.exclude_name` | 名称含这些词的仓库排除（如 `awesome` 清单） |
| `github.active_days` | 多少天内有更新算「近期活跃」并优先排序 |
| `categories[].queries` | 该类别在 GitHub 搜索用的主词 |
| `categories[].keywords` | 本地二次打分词，命中才收录，用于去噪 |
| `rising.min_stars / active_days` | 新星观察门槛与活跃窗口 |

想调整方向，改 `queries`（扩大召回）和 `keywords`（收紧/放宽匹配）即可，不用改代码。

## 输出字段

每条含：仓库名（链接）、star、fork、语言、近期活跃标记、描述、最近更新天数。

## 定时说明

工作流每天北京时间 08:50 自动跑，结果提交回 `reports/`；也可在 Actions 页手动 `Run workflow` 补跑。
