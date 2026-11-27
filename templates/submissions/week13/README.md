# Week 13 — Final Milestone / 最终里程碑

## Submission status / 提交状态

- **Project / 项目:** Product Review Analysis & Issue Discovery / 商品评论分析与问题发现
- **Repository / 仓库:** https://github.com/Fei-stack-wq/maie6000c-PRI
- **Working branch / 工作分支:** `integrate_v1`
- **Primary artifact / 提交入口:** `templates/submissions/week13/README.md`
- **Members / 成员:** FEI, Wenxiang; XIANG, Ke; XU, Chao; ZHANG, Mingyang
- **Required tag / 要求标签:** `w13-final` — pending final verification and publication / 待最终验证后发布
- **Tagged commit SHA / 标签对应提交:** To be recorded after tagging / 打标签后填写
- **Readiness / 就绪情况:** Integrated implementation; final release checks and known-defect fixes remain / 已整合实现，仍有最终验证及已知缺陷待处理
- **Last updated / 更新日期:** 27 November 2026 / 2026 年 11 月 27 日

This document describes the implemented system, verification evidence and planned final demonstration.
It does not claim that final release verification or all known-defect fixes are complete.

The independent review described below examined commit
`312cf4c53e9638a221c50e16378e9ea81baa9774`.
This is the review baseline, not the final tagged commit.

本文记录已实现的系统、验证证据和最终演示安排，不表示最终发布验证或全部缺陷修复已经完成。
下文独立复核基于提交 `312cf4c53e9638a221c50e16378e9ea81baa9774`；
该编号是检查基线，不是最终标签对应的提交。

## English

### 1. Project overview

The system helps reviewers turn imported product reviews into evidence-backed issue groups.
It combines asynchronous analysis, AI extraction, semantic grouping and auditable human review.

The main workflow is:

**CSV/JSON input → PostgreSQL batch/comments/jobs → Worker → AI extraction → evidence validation → semantic grouping → saved results → bilingual workbench → human review and issue follow-up.**

Users can:

- Import reviews and inspect validation errors and batch progress.
- Browse reviews and issues by batch, product and category.
- Inspect original text and the evidence supporting an issue association.
- Accept, reject or adjust associations and retain review history.
- Confirm, follow up, resolve or reopen issue groups.
- Stop unfinished batch work, move batches to trash, restore them or permanently delete them.

Accepting a review's association and confirming or resolving an issue group are separate operations.

### 2. Minimum engineering contract

| Requirement | Implementation and evidence |
| --- | --- |
| Persistent relational data | PostgreSQL with a persistent Docker volume; SQLAlchemy models and Alembic migrations through `20261126_0010`. Batches, comments, jobs, analysis runs, issue links and review history are stored. |
| Service/API layer | FastAPI endpoints for ingestion, queries, batch lifecycle, human review and issue follow-up. See [API entry point](../../../services/api/app/main.py). |
| Worker/async path | Database-backed jobs, claim leases, bounded retries, expired-claim recovery and guarded result writes. See [Worker](../../../services/worker/app/main.py). |
| Integrated AI function | OpenAI-compatible model extraction and local MiniLM semantic grouping feed the persisted business workflow. |
| Reproducible local startup | [Docker Compose](../../../compose.yaml), [Dockerfile](../../../Dockerfile), [.env.example](../../../.env.example) and a [PowerShell launcher](../../../scripts/start_product_ui.ps1). Final clean-machine rehearsal remains pending. |
| Tests or credible verification | Python unit/integration tests, Node frontend tests and recorded integration checks. Verification scope is described below. |
| Documentation | [README](../../../README.md), [architecture](../../../docs/architecture.md), [operations](../../../docs/operations.md), [human review](../../../docs/human-review.md) and [progress](../../../docs/progress.md). |
| Structured logs | JSON logging for API requests, Worker attempts and AI processing. |
| Health checks | API/AI `/health/live` and `/health/ready`, plus Compose health checks. |
| Basic observability | Prometheus metrics for requests, latency and Worker job states/events; [scrape configuration](../../../observability/prometheus.yml). |

### 3. Local startup

Prerequisites:

- Docker Desktop with Docker Compose.
- PowerShell for the provided launcher.
- Network access for the initial dependency and embedding-model downloads.
- Python 3.11 and Node 22+ if running tests directly on the host.

Start Docker Desktop, then run from the repository root:

```powershell
.\scripts\start_product_ui.ps1
```

Open <http://localhost:8000/ui/> or the configured API port.

The launcher creates `.env` from `.env.example` only when the file is missing, builds the services and applies database migrations.
The first build installs the CPU embedding dependencies and downloads the model weights.
Existing data is retained in the PostgreSQL volume.

Check or stop the stack:

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
```

Stopping the stack retains its data volume. Do not delete that volume when demonstrating persistence or updating the application.

Use the launcher's Compose project name for operational commands:

```bash
docker compose -p maie6000c-pri -f compose.yaml ps
docker compose -p maie6000c-pri -f compose.yaml logs --tail 100 api worker ai
docker compose -p maie6000c-pri -f compose.yaml exec ai python -m scripts.probe_grouping_backend
```

See [operations](../../../docs/operations.md) for configuration, identity and testing details.

### 4. AI integration and configuration

The AI workflow has two separate steps:

1. **Issue extraction:** an OpenAI-compatible model returns a structured verdict, category, description and verbatim supporting evidence.
2. **Semantic grouping:** a local MiniLM model suggests whether the extracted issue belongs to an existing group.

The Worker validates the output and locates evidence in the original review before saving results.
Analysis records retain model/prompt/category versions, input hashes, output, source, fallback metadata and latency.

For real LLM extraction, configure the ignored local `.env` before starting the services:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=<provider base URL>
LLM_MODEL=<model name>
LLM_API_KEY=<local secret>
LLM_API_KEY_HEADER=<provider header, e.g. api-key or Authorization>
```

Do not commit credentials.

Default extraction uses rules. Missing model configuration or failed model calls can also lead to rule fallback.
Local semantic grouping is a separate model step and requires no external provider key.

Before claiming a real-model demonstration:

- Inspect the saved extraction source and model version.
- Check whether fallback occurred.
- Verify the grouping backend using `scripts.probe_grouping_backend`.
- Do not present a heuristic extraction result as a successful LLM result.

Uncertain results and rule fallback remain pending for human review.
Automatic assignment requires additional evidence and consistency checks; model confidence alone is insufficient.

### 5. Verification evidence

| Evidence | Result and scope |
| --- | --- |
| Repository integration record, 27 November 2026 | [Integration verification](../../../docs/integrate-v1-verification.md) records 474 Python tests, 26 Node tests, PostgreSQL migration/concurrency checks and three real-model examples. These are the recorded results from that environment. |
| Independent Codex-assisted review of `312cf4c`, 27 November 2026 | Existing Python unit/integration suite: **433 passed, 41 PostgreSQL-specific tests skipped**. Frontend: **26 passed**. Ruff passed for services, scripts and migrations. |
| Additional diagnostic probes | Reproduced the four defects listed below. These temporary probes ran in a separate review workspace and are not committed repository regression tests. |
| Not repeated in the independent review | Full Docker deployment, clean-machine startup, PostgreSQL-specific tests and live provider calls. |

Run the existing tests from the repository root:

```bash
python -m pip install -e ".[dev]"
python -m pytest -q tests/unit tests/integration
node --test tests/frontend/*.cjs
ruff check .
```

For PostgreSQL-specific tests, set `WORKER_TEST_DATABASE_URL` to an isolated test database whose name ends in `_test`.
See [operations](../../../docs/operations.md) for the test setup.

Passing tests establishes the behavior exercised by those tests.
It does not establish review-classification accuracy or prove that every workflow is defect-free.

### 6. Planned final demonstration

Use disposable demonstration data and the integrated workbench, not an archived mock UI.

| Step | Demonstration | Evidence to show |
| --- | --- | --- |
| 1. Input entering the system | Upload a UTF-8 CSV with `shop_id,product_id,body`. | Import validation, batch ID and accepted/error counts. |
| 2. Persistence of state | Inspect stored batch/comment/job records; restart without deleting the volume. | The same batch, results and review history remain after restart. |
| 3. Background processing | Follow job progress and Worker activity. | Queued/processing/completed states and structured Worker logs. |
| 4. AI-enabled workflow | Inspect an analysis run and its grouping result. | Extraction source, model/prompt versions, original evidence and grouping hints. |
| 5. Output surfaced or stored | Browse issue groups, perform a human review decision and inspect history. | Saved results, review audit history and issue follow-up state. |
| 6. Operational signals | Inspect service health, logs and metrics. | Health responses, JSON logs, request/job counts and latency metrics. |
| 7. Honest limitation or failure mode | Show a controlled fallback or uncertain result. | Explicit fallback/source information and an explanation of the limitation. |

Sample input files:

- [Chinese product reviews](../../../frontend/test-data/chinese_product_reviews_50.csv)
- [English product reviews](../../../frontend/test-data/amazon_fashion_60.csv)

Small inputs may finish before an intermediate state appears in the UI.
Use saved job records and logs to explain background processing rather than relying only on a transient screen state.

This is a rehearsal plan. Final demonstration execution evidence still needs to be captured.

### 7. Known defects and limitations

The following defects were reproduced against the review baseline.
This documentation change does not fix them.

| Defect | Trigger and impact |
| --- | --- |
| Legacy regrouping can block startup | Two links for the same comment can normalize into the same issue group, violating the unique comment/issue constraint. Compose runs the repair before starting the API. |
| Deliberate repeat upload can reuse an old batch | The frontend retains the same request key for identical file/name/platform content throughout a browser session. Uploading again after stopping or trashing the original batch may return that old batch instead of creating new work. |
| Restored batches can leave issue groups unmanageable | A group containing both an analyzed comment and a manually linked failed comment can become affected after trash/restore. Locked and visible evidence sets differ, causing repeated `409 issue_changed` responses. |
| Chinese rule fallback can flag positive reviews | “质量很好，物流很快，穿着很舒适。” is classified as quality, logistics and usability issues by keyword matching. |

Other limitations and trade-offs:

- Extraction permits at most one issue per category per review.
- Confidence and similarity thresholds are operational rules, not calibrated accuracy guarantees.
- Representative analysis-quality evaluation remains incomplete.
- Real-platform adapters and operator-driven failed-job replay remain future work.
- The workbench is a shared team workspace, not a per-store authorization system.
- Review text may contain personal information; automatic redaction is not implemented.
- An external provider and initial model downloads introduce network dependencies.

See [architecture](../../../docs/architecture.md) and [progress](../../../docs/progress.md) for further scope details.

### 8. AI Use Statement

Existing project documentation declares the use of ChatGPT for documentation polishing, code scaffolding and testing.

Codex additionally assisted with:

- Reviewing repository implementation and integration behavior.
- Preparing and running diagnostic tests.
- Comparing the repository with the supplied assignment requirements.
- Drafting and revising this milestone README.

The Codex-assisted review inspected implementation paths, ran the checks reported above and reproduced the listed defects.
This README distinguishes recorded project verification from the independent rerun and leaves unverified deployment/model claims pending.
Passing the existing suite was not treated as proof of correctness or analysis accuracy.

### 9. Final release checklist

- [ ] Fix the reproduced defects and add regression coverage.
- [ ] Rehearse startup from a clean environment.
- [ ] Demonstrate real AI processing and clearly identified fallback behavior.
- [ ] Verify restart persistence without deleting the PostgreSQL volume.
- [ ] Repeat PostgreSQL-specific checks in an isolated database.
- [ ] Retain final test and demonstration evidence.
- [ ] Add architecture decision records under `docs/adrs/`.
- [ ] Check that documentation matches the final implementation.
- [ ] Prepare the final demonstration sequence and presentation slides if used.
- [ ] Confirm the team name, AI Use Statement and remaining limitations.
- [ ] Publish `w13-final` on the verified final commit.
- [ ] Record the tagged commit SHA at the top of this document.
- [ ] Submit the repository, tag, SHA, primary artifact path, team name and readiness note in Canvas.

## 中文

### 1. 项目目标与实现

系统将导入的商品评论整理为有原文证据支持的问题组，结合后台分析、AI 提取、语义归组和可追溯的人工复核。

主流程为：

**CSV／JSON → PostgreSQL 批次、评论和任务 → Worker → AI 提取 → 证据校验 → 语义归组 → 结果保存 → 双语工作台 → 人工复核与问题跟进。**

已实现的主要功能：

- 评论导入、行级校验、批次进度和错误信息。
- 按批次、商品和类别查看评论及问题。
- 查看原文和支持问题关联的证据。
- 接受、拒绝及调整关联，并保存复核历史。
- 确认、跟进、解决和重新打开问题组。
- 停止批次剩余任务、回收、恢复和永久删除。

“接受评论关联”与“确认或解决整个问题组”是两个独立操作。

系统已有关系型持久化、FastAPI、后台任务、AI 集成、结构化日志、健康检查及基础指标。
实现位置和证据链接见上方要求对照表。

### 2. 本地启动

前置条件：

- Docker Desktop 和 Docker Compose。
- 执行启动脚本所需的 PowerShell。
- 首次下载依赖和模型所需的网络连接。
- 如在宿主机执行测试，另需 Python 3.11 和 Node 22+。

启动 Docker Desktop，在仓库根目录运行：

```powershell
.\scripts\start_product_ui.ps1
```

打开 <http://localhost:8000/ui/>，或使用配置后的 API 端口。

脚本只在缺少 `.env` 时从 `.env.example` 创建配置，不会覆盖已有配置。
首次构建需要安装 CPU 语义模型依赖并下载权重。
数据库保存在 PostgreSQL 数据卷中。

检查与停止：

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
```

停止整套服务会保留数据卷。更新应用和演示重启持久化时，不要删除数据卷。

启动脚本使用 Compose 项目名 `maie6000c-pri`。
查询服务、日志和归组后端时，应使用上方带 `-p maie6000c-pri -f compose.yaml` 的命令。

### 3. AI 配置与结果说明

系统包含两个独立的 AI 步骤：

1. 使用 OpenAI-compatible 模型提取评论中的问题、类别和原文证据。
2. 使用本地 MiniLM 模型进行语义归组建议。

Worker 校验输出结构和原文证据后保存结果。
分析记录包含模型、提示词和类别版本，以及来源、回退原因和耗时等信息。

默认提取使用规则。演示真实 LLM 提取前，应在本地、已忽略的 `.env` 中配置：

- `LLM_PROVIDER=openai_compatible`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_API_KEY_HEADER`

不要提交密钥。

模型配置缺失或调用失败时可能回退到规则。
本地语义归组是另一个模型步骤，不需要额外的外部提供方 Key。

演示时必须核对保存结果中的提取来源、模型版本、回退信息及归组后端。
不能把规则回退称为 LLM 调用成功。
不确定结果和规则回退保持待人工确认；模型自报高置信度不足以单独触发自动采用。

### 4. 验证结果与边界

| 验证来源 | 结果与范围 |
| --- | --- |
| 仓库整合验证记录 | 记录了 474 项 Python、26 项 Node 测试，以及 PostgreSQL、迁移、真实模型样例和浏览器检查。详见[整合验证记录](../../../docs/integrate-v1-verification.md)。 |
| 本次 Codex 辅助独立复核 | 基于 `312cf4c`：已有 Python 单元／集成测试 **433 通过、41 项 PostgreSQL 专项跳过**；前端 **26 通过**；服务、脚本及迁移代码的 Ruff 检查通过。 |
| 补充诊断 | 在独立工作目录运行临时用例，复现了本文列出的四项缺陷。临时用例尚未作为回归测试提交到仓库。 |
| 本次未重新验证 | 完整 Docker 部署、全新环境启动、PostgreSQL 专项及真实提供方调用。 |

复跑命令见英文部分。
PostgreSQL 专项必须使用独立、名称以 `_test` 结尾的测试数据库。

已有测试通过不代表没有缺陷，也不能作为分析准确率。
仓库历史验证记录与本次独立复跑具有不同的环境和覆盖范围，应分别说明。

### 5. 最终演示安排

1. **输入进入系统：** 上传 UTF-8 CSV，展示校验结果和批次编号。
2. **状态持久化：** 展示评论与任务已入库；保留数据卷重启后，核对同一批次、分析结果和复核历史。
3. **后台处理：** 展示任务状态和 Worker 日志，证明处理通过后台任务完成。
4. **AI 工作流：** 展示真实 AI 调用对应的来源、模型／提示词版本、证据和归组信息，明确标注回退。
5. **结果展示与保存：** 查看问题组，完成人工核查，展示持久化历史和问题跟进状态。
6. **运行信号：** 展示健康检查、JSON 日志、请求／任务数量及延迟指标。
7. **真实限制：** 说明并展示至少一种不确定结果、失败模式或回退行为。

可使用仓库中的[中文样例](../../../frontend/test-data/chinese_product_reviews_50.csv)和[英文样例](../../../frontend/test-data/amazon_fashion_60.csv)。

这是待执行的最终演练计划，不是已经完成演练的声明。
使用可丢弃的演示数据和整合工作台，不使用历史 mock 页面代替真实流程。
小批次可能很快处理完成，可以通过保存的任务记录及日志说明过程。

### 6. 已知缺陷与范围限制

本次文档更新没有修复以下已复现问题：

- **旧数据整理可能阻断启动：** 同一评论的两条关联整理到同一问题组时，可能触发唯一键冲突；整理在 API 启动前执行。
- **重复主动上传仍返回旧批次：** 同一浏览器会话内相同文件复用旧请求编号，可能返回已停止或回收的旧批次。
- **恢复后部分问题组无法操作：** 同一组包含分析成功评论与人工补录的失败评论时，回收再恢复可能导致持续返回 `409 issue_changed`；原因是锁定集合与可见证据集合不一致。
- **中文规则回退误判好评：** “质量很好，物流很快，穿着很舒适。”会被关键词逻辑判为三个类别的问题。

其他限制：

- 每条评论每个类别最多提取一个问题。
- 置信度及相似度阈值不是经过校准的准确率保证。
- 代表性分析质量评测仍待完善。
- 真实平台接口和人工发起失败任务重放仍属于后续工作。
- 当前为小组共享工作区，不提供按店铺划分的账号授权。
- 原始评论可能包含个人信息，尚未实现自动脱敏。
- 外部模型调用及首次模型下载依赖网络。

详见[架构文档](../../../docs/architecture.md)和[开发进度](../../../docs/progress.md)。

### 7. AI 使用声明

项目现有说明记录了使用 ChatGPT 辅助文档润色、代码框架和测试。

本次还使用 Codex 辅助：

- 检查仓库实现和模块衔接。
- 编写并运行诊断测试。
- 对照课程要求检查完成情况。
- 编写和修改本 README。

### 8. 最终提交前待办

- [ ] 修复已复现缺陷并补充回归测试。
- [ ] 在全新环境按文档完成启动演练。
- [ ] 验证真实 AI 流程及明确标注的回退行为。
- [ ] 验证保留数据卷重启后的持久化。
- [ ] 在独立数据库完成 PostgreSQL 专项验证。
- [ ] 保存最终测试和演示证据。
- [ ] 补充 `docs/adrs/` 架构决策记录。
- [ ] 核对文档与最终实现一致。
- [ ] 准备最终演示流程及使用到的演示文稿。
- [ ] 确认团队名称、AI 使用声明和已知限制。
- [ ] 将 `w13-final` 推送到验证后的最终提交。
- [ ] 在本页顶部填写标签对应的提交 SHA。
- [ ] 在 Canvas 填写仓库、标签、SHA、提交入口、团队名称和演示就绪说明。
