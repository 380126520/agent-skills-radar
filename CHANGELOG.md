# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)（MAJOR.MINOR.PATCH）与 Keep a Changelog 规范。

## [1.0.0] - 2026-11-02

### 新增
- 每日自动精选高 star 的 Claude/Agent Skills 与 Agent 工具/插件：主榜 `stars>1000` + 新星观察（200~1000、近 90 天活跃）
- 每条配中文一句话简介（免费翻译，无需 LLM Key），输出卡片式 Markdown + 自包含 HTML 美观版
- 支持按关键字检索并按 star 排名：网页版（GitHub Pages，输入即查）+ 命令行 `--kw`
- 跨仓去重、过滤 awesome 清单、非归档、近期活跃优先

### 变更
- README 重写美化（徽章、亮点、示例、快速开始、配置表）

---

### 版本号约定
- **PATCH**（1.0.x）：修 bug、文案、不改变用法的小调整
- **MINOR**（1.x.0）：新增功能、向后兼容（如新增检索类别/输出格式）
- **MAJOR**（x.0.0）：不兼容的行为变更（如改门槛口径、改输出结构）
