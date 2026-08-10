# Agent Usage Monitor

[![CI](https://github.com/Darwin-lfl/agent-usage-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Darwin-lfl/agent-usage-monitor/actions/workflows/ci.yml)
[![Release](https://github.com/Darwin-lfl/agent-usage-monitor/actions/workflows/release.yml/badge.svg)](https://github.com/Darwin-lfl/agent-usage-monitor/actions/workflows/release.yml)

**本地优先的编程 Agent Token 用量监控器 / A privacy-first token usage monitor for coding agents**

[中文](#中文) · [English](#english)

支持 Claude Code、Codex、OpenCode、Trae、Qoder 和 CodeBuddy。统一统计 Token、模型、时间趋势和数据源状态，同时提供交互式 TUI、浏览器仪表盘以及 JSON/CSV 输出。

Monitor Claude Code, Codex, OpenCode, Trae, Qoder, and CodeBuddy from one local application, with an interactive TUI, a browser dashboard, and machine-readable output.

## 功能演示 / Demo

### Web 仪表盘 / Web dashboard

![Agent Usage Monitor Web dashboard demo](docs/assets/web-demo.gif)

### 终端界面 / Terminal UI

![Agent Usage Monitor terminal UI demo](docs/assets/tui-demo.gif)

> 演示由本机环境中的真实应用生成。只展示汇总用量和经过脱敏的项目名称，不包含提示词、回复内容或完整本地路径。
>
> The demos were captured from the real application running locally. They contain aggregated usage and sanitized project labels, but no prompts, responses, or full local paths.

---

## 中文

### 项目简介

Agent Usage Monitor 读取各编程 Agent 保存在本机的日志或数据库，将不同格式的 Token 计数归一化为统一事件，然后按 Agent、模型和时间维度展示。

所有扫描与聚合均在本机完成。Web 模式只监听 `127.0.0.1`，运行时不会上传日志、凭证、提示词或回复内容。

### 核心功能

| 功能 | 说明 |
|---|---|
| 多 Agent 统计 | 同时检测 Claude Code、Codex、OpenCode、Trae、Qoder、CodeBuddy |
| 模型维度 | 按 Agent 和模型统计 Input、Output、Cache、Reasoning、Total、事件数和日志中已有的 Cost |
| 时间分析 | 支持今天、24 小时、7/30/90 天、全部时间和自定义范围 |
| 时间粒度 | 支持小时、天、周、月聚合 |
| 交互图表 | Hover 预览时间桶，点击固定详情，键盘方向键切换时间桶 |
| 双界面 | Textual TUI 与本机 Web 仪表盘共享同一套统计服务 |
| 集成输出 | Rich、JSON、CSV、紧凑状态行、原子状态文件和可选 SQLite Warehouse |
| 本地优先 | 只读扫描本地数据；无遥测、无预测、无 Reset、无云端上传 |

### 安装

#### 独立二进制（推荐）

Release 二进制不要求用户安装 Python 或 uv。仓库正式发布后，macOS/Linux 使用：

```bash
curl -fsSL https://github.com/Darwin-lfl/agent-usage-monitor/releases/latest/download/install.sh | sh
```

Windows PowerShell：

```powershell
irm https://github.com/Darwin-lfl/agent-usage-monitor/releases/latest/download/install.ps1 | iex
```

安装器会检测操作系统和 CPU 架构、下载对应文件并校验 SHA256。

#### pipx

```bash
pipx install agent-usage-monitor
agent-monitor
```

#### 从源码安装

```bash
git clone https://github.com/Darwin-lfl/agent-usage-monitor.git
cd agent-usage-monitor
uv tool install -e .
agent-monitor
```

### 快速开始

#### TUI

```bash
agent-monitor
# 等价写法
agent-monitor tui
```

Agent、模型、时间范围和时间粒度都可以直接在顶部工具栏选择，不需要为日常使用记忆命令行参数。

| 按键 | 操作 |
|---|---|
| `1` | Agent 统计 |
| `2` | 模型统计 |
| `3` | 时间趋势 |
| `4` | 数据源状态 |
| `r` | 重新扫描 |
| `q` | 退出 |
| `←` / `→` | 切换 Activity 时间桶 |
| `Home` / `End` | 跳到首个/最后一个时间桶 |

定时扫描默认关闭。需要定期刷新时可使用：

```bash
agent-monitor --refresh-rate 60
```

#### 本机 Web

```bash
agent-monitor web
```

命令会在 `127.0.0.1:8765` 启动 Web 仪表盘并打开浏览器。若端口被占用，会自动尝试后续端口。

```bash
# 指定起始端口
agent-monitor web --port 9000

# 不自动打开浏览器
agent-monitor web --no-open
```

Web 页面支持：

- Agent、模型、时间范围和时间粒度筛选；
- Token 总量、Input、Output、Cache、Reasoning 和事件数；
- Activity 柱状图 Hover 提示、点击固定详情和键盘导航；
- 按模型统计的明细表；
- 本地数据源检测与解析状态；
- 桌面和移动视口。

Web 前端资源随 Python 包和独立二进制一起发布，不使用 CDN，也不监听局域网地址。

### 非交互输出

```bash
# Rich 快照
agent-monitor --once

# JSON / CSV
agent-monitor --output json
agent-monitor --output csv

# 状态栏友好的一行输出
agent-monitor --compact

# 数据源诊断
agent-monitor --doctor
```

命令行筛选示例：

```bash
agent-monitor --once --agent opencode --view models --range 7d
agent-monitor --once --range 24h --granularity hour
agent-monitor --once --model 'openai/*' --model 'anthropic/*'
agent-monitor --once --range custom --start 2026-08-01 --end 2026-08-08
agent-monitor --once --exact-only
```

`--model` 支持不区分大小写的子串和 Glob。`--exact-only` 会排除只能通过消息文本估算用量的 IDE 事件。

### JSON 与本地 Warehouse

JSON 使用 `schema_version: 2`，包含：

- 当前选择的范围、起止时间、粒度和模型过滤条件；
- 总量、各 Agent 汇总和各模型汇总；
- 每个时间桶及其模型明细；
- 数据源状态、数据来源和准确度警告。

```bash
# 原子写入最新状态
agent-monitor --once --write-state

# 将归一化事件持久化到本地 SQLite
agent-monitor --once --warehouse
```

默认文件：

- 状态：`~/.agent-usage-monitor/state/latest.json`
- Warehouse：`~/.agent-usage-monitor/usage.sqlite3`

Warehouse 只保存计数和分析维度，不保存提示词或回复正文。

### 支持的数据源

| Agent | 默认本地来源 | 准确度 |
|---|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` | Provider usage 字段，精确 |
| Codex | `~/.codex/{sessions,archived_sessions}/**/*.jsonl` | 累计 Token 快照和 Turn 模型上下文，精确 |
| OpenCode | `~/.local/share/opencode/opencode*.db` 或旧版 JSON 存储 | Message Token 字段，精确 |
| Trae | VS Code 兼容的 `User` JSON/SQLite 存储 | 精确字段或明确标记的估算 |
| Qoder | VS Code 兼容的 `User` JSON/SQLite 存储 | 精确字段或明确标记的估算 |
| CodeBuddy | VS Code 兼容的 `User` JSON/SQLite 存储 | 精确字段或明确标记的估算 |

OpenCode SQLite 使用只读查询，只选择时间、模型、项目、Cost 和 Token 数值字段，不加载提示词或回复正文。Codex 模型会根据日志顺序从 `turn_context` 和 `thread_settings_applied` 继承，因此同一会话中的模型切换也可以被统计。

Cache Input 与 Input 重叠的 Agent 会在适配器层完成归一化，避免重复计数。Reasoning Token 作为独立指标保留，但不会再次叠加进 Total。

### 隐私与安全

- 本地只读采集；
- 不上传凭证、日志、提示词或回复；
- Web 只绑定 `127.0.0.1`；
- 不加载 CDN 或第三方页面资源；
- 完整本地路径不会显示在 Web Activity 详情中；
- 估算事件始终带有 `estimated` 标记；
- Cost 只使用日志中已经提供的数值，不推测模型价格。

### 开发与测试

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests

cd web
npm ci
npm run typecheck
npm run build
```

构建当前平台的单文件程序：

```bash
uv run pyinstaller --clean --noconfirm agent-monitor.spec
./dist/agent-monitor --version
```

推送 `v*` Tag 会触发 GitHub Actions，生成 macOS arm64/x86_64、Linux arm64/x86_64 和 Windows x86_64 产物，并发布安装脚本、SHA256 清单、Wheel 和源码包。

---

## English

### Overview

Agent Usage Monitor reads the logs and databases created by local coding agents, normalizes their different token formats into a common event model, and presents usage by agent, model, and time.

Collection and aggregation stay on the user's machine. Web mode listens only on `127.0.0.1`; the runtime does not upload logs, credentials, prompts, or responses.

### Features

| Feature | Description |
|---|---|
| Multi-agent analytics | Detect Claude Code, Codex, OpenCode, Trae, Qoder, and CodeBuddy together |
| Model breakdown | Input, Output, Cache, Reasoning, Total, events, and log-reported cost by agent and model |
| Time ranges | Today, rolling 24 hours, 7/30/90 days, all time, and custom ranges |
| Granularity | Hour, day, week, and month buckets |
| Interactive activity | Hover to preview, click to pin, and use the keyboard to navigate buckets |
| Two interfaces | A Textual TUI and a local browser dashboard backed by the same measurement service |
| Integration output | Rich, JSON, CSV, compact status output, atomic state files, and an optional SQLite warehouse |
| Privacy first | Read-only local collection with no telemetry, forecasting, reset workflow, or cloud upload |

### Installation

#### Standalone binary (recommended)

Release binaries do not require Python or uv. After the repository is published, install the latest macOS or Linux release with:

```bash
curl -fsSL https://github.com/Darwin-lfl/agent-usage-monitor/releases/latest/download/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://github.com/Darwin-lfl/agent-usage-monitor/releases/latest/download/install.ps1 | iex
```

The installers detect the OS and CPU architecture, download the matching artifact, and verify its SHA256 checksum.

#### pipx

```bash
pipx install agent-usage-monitor
agent-monitor
```

#### From source

```bash
git clone https://github.com/Darwin-lfl/agent-usage-monitor.git
cd agent-usage-monitor
uv tool install -e .
agent-monitor
```

### Quick start

#### TUI

```bash
agent-monitor
# Equivalent explicit command
agent-monitor tui
```

Agent, model, range, and granularity controls are available directly in the toolbar, so normal use does not require CLI flags.

| Key | Action |
|---|---|
| `1` | Agent statistics |
| `2` | Model statistics |
| `3` | Timeline |
| `4` | Source health |
| `r` | Rescan local data |
| `q` | Quit |
| `←` / `→` | Move between activity buckets |
| `Home` / `End` | Jump to the first/last bucket |

Periodic refresh is disabled by default. Enable it explicitly when needed:

```bash
agent-monitor --refresh-rate 60
```

#### Local Web dashboard

```bash
agent-monitor web
```

This starts the dashboard on `127.0.0.1:8765` and opens the default browser. If the port is occupied, the application tries the next available port.

```bash
# Choose the starting port
agent-monitor web --port 9000

# Do not open a browser automatically
agent-monitor web --no-open
```

The dashboard includes:

- agent, model, time-range, and granularity filters;
- total, input, output, cache, reasoning, and event metrics;
- hover tooltips, click-to-pin details, and keyboard navigation on the activity chart;
- per-model analytics;
- local source detection and parsing status;
- responsive desktop and mobile layouts.

The frontend is bundled into both the Python package and standalone executable. It uses no CDN and never listens on a LAN-facing address.

### Non-interactive output

```bash
# Rich snapshot
agent-monitor --once

# JSON / CSV
agent-monitor --output json
agent-monitor --output csv

# Status-bar-friendly output
agent-monitor --compact

# Source diagnostics
agent-monitor --doctor
```

Filtering examples:

```bash
agent-monitor --once --agent opencode --view models --range 7d
agent-monitor --once --range 24h --granularity hour
agent-monitor --once --model 'openai/*' --model 'anthropic/*'
agent-monitor --once --range custom --start 2026-08-01 --end 2026-08-08
agent-monitor --once --exact-only
```

`--model` accepts case-insensitive substrings and globs. `--exact-only` excludes IDE events whose usage can only be estimated from message text.

### JSON and local warehouse

JSON output uses `schema_version: 2` and includes:

- the requested range, boundaries, granularity, and model filters;
- totals plus per-agent and per-model summaries;
- every timeline bucket with its model breakdown;
- source health, provenance, and accuracy warnings.

```bash
# Atomically update the latest state
agent-monitor --once --write-state

# Persist normalized events in local SQLite
agent-monitor --once --warehouse
```

Default files:

- State: `~/.agent-usage-monitor/state/latest.json`
- Warehouse: `~/.agent-usage-monitor/usage.sqlite3`

The warehouse stores counters and analytical dimensions, never prompt or response bodies.

### Supported data sources

| Agent | Default local source | Accuracy |
|---|---|---|
| Claude Code | `~/.claude/projects/**/*.jsonl` | Exact provider usage fields |
| Codex | `~/.codex/{sessions,archived_sessions}/**/*.jsonl` | Exact cumulative snapshots with turn-level model context |
| OpenCode | `~/.local/share/opencode/opencode*.db` or legacy JSON storage | Exact message token fields |
| Trae | VS Code-compatible `User` JSON/SQLite storage | Exact fields or labeled estimates |
| Qoder | VS Code-compatible `User` JSON/SQLite storage | Exact fields or labeled estimates |
| CodeBuddy | VS Code-compatible `User` JSON/SQLite storage | Exact fields or labeled estimates |

OpenCode SQLite files are queried read-only. Queries select only timestamps, models, projects, costs, and numeric token fields; prompt and response bodies are not loaded. Codex models are inherited in log order from `turn_context` and `thread_settings_applied`, including model changes inside one session.

Adapters normalize agents whose cached input overlaps input tokens, preventing double counting. Reasoning tokens remain available as a separate metric but are not added to Total a second time.

### Privacy and security

- Local, read-only collection;
- no credential, log, prompt, or response upload;
- Web mode binds only to `127.0.0.1`;
- no CDN or third-party page resources;
- full local paths are not rendered in Web activity details;
- estimated events are always labeled `estimated`;
- costs are shown only when reported by source logs; pricing is never guessed.

### Development and release

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests

cd web
npm ci
npm run typecheck
npm run build
```

Build a standalone executable for the current platform:

```bash
uv run pyinstaller --clean --noconfirm agent-monitor.spec
./dist/agent-monitor --version
```

Pushing a `v*` tag triggers the release workflow. It builds macOS arm64/x86_64, Linux arm64/x86_64, and Windows x86_64 binaries, then publishes installers, SHA256 checksums, a wheel, and a source distribution.

## License

MIT
