# Product Review Analysis & Issue Discovery / 商品评论分析与问题发现

## English

### Start the midterm demo

Start Docker Desktop and open a terminal in the repository root.

```powershell
# Windows
.\scripts\start_midterm_demo.ps1
```

```bash
# macOS / Linux
docker compose -f compose.midterm.yaml up --build -d --wait
```

Open **[English demo](http://localhost:18717/en)** or [Chinese demo](http://localhost:18717/zh).
See the [demo run instructions](demo/midterm/README.md) for downloads, operation and shutdown.
The demo needs no `.env` file or model API key. The first build downloads dependencies.

### Project and current scope

We are building a tool to collect product reviews, identify concrete issues with source evidence,
and organise candidate issue groups for staff review. The planned product includes semantic grouping
and review/follow-up actions. These are still under development.

The current working path is:

**Submit review → save review and job → background analysis → verify evidence → save and display results.**

| Part | Current status |
| --- | --- |
| R1: ingestion and queries | CSV text / JSON input, row validation, deduplication, revisions, jobs and read APIs are implemented |
| R2: background processing | Claiming, bounded retries, expired-job recovery, protected writes, evidence checks and metrics are implemented |
| R3: analysis | Chinese/English rule extraction and category-based grouping work; LLM extraction, semantic grouping and quality evaluation remain |
| R4: product frontend | The original five-page interface uses mock data; live data and review-action APIs remain |
| Midterm demo | A separate Chinese/English page calls the existing backend and demonstrates persisted results and retry behaviour |

The demo is a Week 07 presentation interface, not a replacement for the team frontend.
The language pages share one round. Reviews and evidence remain in their original language;
common Chinese and English problem expressions are supported by the rule baseline.
The system does not determine product defects, liability or root causes, or act on the source platform.

**Analysis limits:** The rules cover selected expressions in quality, delivery, description mismatch
and usability. Warranty refusal, after-sales service and other unsupported wording can be missed;
`no` or `unknown` is not proof that the review contains no complaint. The demo shows processing,
retry and result storage. It has not established accuracy across unrestricted reviews.

### Repository guide

| Location | Contents |
| --- | --- |
| `services/api/app/` | Review ingestion and queries |
| `services/worker/app/` | Background job processing |
| `services/ai/app/` | Internal rule-based analysis service |
| `services/common/`, `alembic/` | Shared data models, request/response definitions and database migrations |
| `frontend/` | Original product frontend with mock interactions |
| `demo/midterm/`, `compose.midterm.yaml` | Standalone midterm demo and its own database |
| `tests/`, `scripts/` | Tests and operating scripts |
| `docs/`, `review/` | Current documentation and earlier design/review material |

Python 3.11, FastAPI, SQLAlchemy, Alembic and PostgreSQL 16 form the backend.
Worker-to-analysis calls use HTTP; Prometheus metrics and structured logs support checks.

### Documentation

- [Week 07 submission](templates/submissions/week07/README.md): demonstrated work, evidence, remaining work and known limitations.
- [Architecture](docs/architecture.md): components, data flow and implementation decisions.
- [Operations](docs/operations.md): demo/full-project startup, monitoring, troubleshooting and tests.
- [Progress](docs/progress.md): current implementation status and next steps.
- [R2 implementation](docs/r2-implementation.md), [execution chain](docs/r2-logic-chain.md) and [flowchart](docs/r2-flowchart.md).

### Full project and tests

To run the original services and frontend instead of the midterm demo, follow
[Operations](docs/operations.md). Its UI is at `http://localhost:8000/ui/` and currently uses mock data.

For a quick check of the running midterm demo, leave it idle and run
` .\scripts\start_midterm_demo.ps1 -Action check ` on Windows.
The complete R2 test environment is started by ` .\scripts\test_r2.ps1 `.
Recorded results and their conditions are in the [verification record](templates/submissions/week07/assets/verification.md).

## 中文

### 启动期中 Demo

启动 Docker Desktop，在仓库根目录打开终端。

```powershell
# Windows
.\scripts\start_midterm_demo.ps1
```

```bash
# macOS / Linux
docker compose -f compose.midterm.yaml up --build -d --wait
```

打开 **[英文版 Demo](http://localhost:18717/en)** 或 [中文版 Demo](http://localhost:18717/zh)。
下载、操作和停止方法见 [Demo 运行说明](demo/midterm/README.md)。
Demo 不需要 `.env` 或模型 API Key，首次构建会下载依赖。

### 项目与当前范围

我们正在开发一个商品评论整理工具：集中接收评论，提取具体问题和原文证据，
建立候选问题组，供工作人员复核。完整产品计划加入语义归组和人工复核、跟进功能，
这些内容仍在开发中。

当前已经接通的流程是：

**提交评论 → 保存评论和任务 → 后台分析 → 校验证据 → 保存并展示结果。**

| 部分 | 当前状态 |
| --- | --- |
| R1 数据接入与查询 | 已实现 CSV 文本／JSON 输入、逐行校验、去重、版本记录、建任务和查询接口 |
| R2 后台处理 | 已实现任务领取、有限重试、过期回收、受保护的结果保存、证据检查和指标 |
| R3 分析 | 中英文规则提取和按类别归组可运行；大模型、语义归组和效果评测待完成 |
| R4 产品前端 | 原五页界面使用模拟数据；真实数据接入和复核动作接口待完成 |
| 期中 Demo | 独立中英文页面连接现有后台，展示结果保存与失败重试 |

Demo 仅用于 Week 07 展示，不替代组员的产品前端。两种语言页面共用同一轮演示。
评论与证据保持原语言；规则基线支持常见中英文问题表达。
系统不判定产品缺陷、责任或根因，也不向来源平台执行操作。

**分析边界：** 规则只覆盖质量、物流、描述不符和使用体验中的部分表达。
拒绝保修、售后服务及其他未覆盖说法可能漏检；`no` 或 `unknown` 不代表评论确实没有投诉。
Demo 展示处理、重试和结果保存，尚未验证对任意评论的识别准确率。

### 仓库内容

| 位置 | 内容 |
| --- | --- |
| `services/api/app/` | 评论导入与查询 |
| `services/worker/app/` | 后台任务处理 |
| `services/ai/app/` | 内部规则分析服务 |
| `services/common/`、`alembic/` | 共享数据模型、输入输出格式和数据库迁移 |
| `frontend/` | 原产品前端与模拟交互 |
| `demo/midterm/`、`compose.midterm.yaml` | 独立期中 Demo 及其数据库 |
| `tests/`、`scripts/` | 测试和运行脚本 |
| `docs/`、`review/` | 当前说明与早期设计、评审材料 |

后台使用 Python 3.11、FastAPI、SQLAlchemy、Alembic 和 PostgreSQL 16。
Worker 通过 HTTP 调用分析服务，使用 Prometheus 指标和结构化日志检查运行情况。

### 文档入口

- [Week 07 提交说明](templates/submissions/week07/README.md)：本次成果、证据、待完成内容和已知限制。
- [系统架构](docs/architecture.md)：组件、数据流和实现选择。
- [运行说明](docs/operations.md)：Demo／原项目启动、监控、排查与测试。
- [当前进度](docs/progress.md)：当前实现状态和后续工作。
- [R2 实现](docs/r2-implementation.md)、[运行链条](docs/r2-logic-chain.md)与[流程图](docs/r2-flowchart.md)。

### 原项目与测试

运行原项目服务和前端的方法见 [运行说明](docs/operations.md)。
原前端地址为 `http://localhost:8000/ui/`，目前使用模拟数据。

检查已启动的期中 Demo 时，先让页面空闲，再在 Windows 执行
` .\scripts\start_midterm_demo.ps1 -Action check `。
完整 R2 测试环境通过 ` .\scripts\test_r2.ps1 ` 启动。
已执行的结果及条件见 [验证记录](templates/submissions/week07/assets/verification.md)。
