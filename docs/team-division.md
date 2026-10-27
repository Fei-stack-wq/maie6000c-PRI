# 团队分工与模块边界（R1–R4）

> 依据：`docs/architecture.md`（目标架构）+ `review/系统设计评审与四人分工.md` §5。
> 本文定义**谁写哪些文件、接口怎么交接、什么算完成**；契约以
> `services/common/schemas.py` 为准，任何人改契约都要走本文 §5 的变更流程。

## 1. 协作模式：契约先行 + 四线并行 + 周集成

- **串行关口（已完成）**：W5 契约冻结（schemas/models/迁移 0002+0003）→ 迁移可执行 →
  R1 接入链路打通；之后四条工作流并行。
- **并行四线**：R1 数据与接入、R2 流水线可靠性、R3 AI 与评测、R4 复核与产品端。
- **每周五集成日**：合并 + 全量测试 + 迁移 + demo 录制；集成前各线自测通过。
- **共享文件单写者**：`services/common/`、`alembic/`、`docs/architecture.md` 只有 R1 能改；
  其他人以 issue/PR 提需求（字段名 / 类型 / 可空 / 索引 / 原因）。

## 2. 角色与所有权

| 角色 | 成员 | 负责工作流 | 可写路径（Workspace 相对） | 主要交付物 |
| --- | --- | --- | --- | --- |
| **R1 数据与接入**（技术负责人） | FEI Wenxiang | 数据模型、迁移、批次接入、去重、共享契约、最终集成 | `services/common/`、`alembic/`、`services/api/app/ingestion.py`、`services/api/app/main.py`（批次/评论/任务/统计部分）、`scripts/reset_database.py`、`docs/`（architecture/README/operations） | 0002+0003 迁移、`POST /review-batches` 与评论/批次/任务读接口、错误清单、幂等、reset 脚本、架构文档 |
| **R2 流水线与可靠性** | XIANG Ke | Job 生命周期、租约/重试、失败重放、可观测性、并发/幂等测试 | `services/worker/`、`observability/`、`scripts/recover_stale_jobs.py`、`scripts/requeue_batch.py`、`tests/unit/test_worker_*` | 原子认领 + 租约回收 + fencing、错误码分类、重试/人工重放、Worker 指标、并发测试 |
| **R3 AI 与评测** | XU Chao | 提取与归组质量、证据校验、评判集、成本控制 | `services/ai/`、`services/common/categories.py`、`scripts/eval_*.py`、`tests/unit/test_ai_*` | 规则基线 → LLM、证据子串校验、同商品归组、标注集与 P/R/F1、成本记录 |
| **R4 复核与产品端** | ZHANG Mingyang | Issue/CommentIssue/IssueAction 状态机与 API、前端、端到端测试、演示 | `services/api/app/issues.py`（待拆出）、`frontend/`、`tests/integration/test_issue_*.py`、`scripts/seed_demo_data.py` | 复核动作 API（409 版本冲突、审计）、问题组看板接真实接口、e2e 演示脚本 |

### 当前文件的分区约定（同一文件多人改时）

| 文件 | 归属 | 规则 |
| --- | --- | --- |
| `services/common/models.py`、`schemas.py`、`categories.py` | R1 主写；R3 可改 `categories.py` | 改前在群里声明；PR 需 R1+R2/R4 中至少 1 人评审 |
| `alembic/versions/*` | R1 唯一写者 | 其他人只提字段需求 issue；迁移只在集成日执行 |
| `services/api/app/main.py` | R1 主写（批次/评论/任务/统计）；R4 将 issue endpoints 拆到 `issues.py` | 拆分前 R4 的 issue 改动需 R1 评审；拆分后各自单写 |
| `services/worker/app/main.py` | R2 | R3 的 AI 契约变化需同步 R2 |
| `services/ai/app/main.py` | R3 | R2 只依赖 HTTP 契约，不读 R3 内部实现 |
| `frontend/` | R4 | 其他线不动；需要接口时按 architecture §8 契约 |
| `tests/` | 各自模块 + R4 端到端 | 谁改坏谁修；集成测试由 R4 维护 |

## 3. 接口交接与契约

- **契约来源**：`services/common/schemas.py` + `docs/architecture.md` §8；API 文档由
  FastAPI 在 `/docs` 自动生成。
- **跨线依赖**（真实 DAG，不是链条）：
  - R1 的批次接口 + Worker 可空跑 → R2 才能联调；
  - R3 的 `ExtractionResult` 契约 → R2 校验与落库逻辑；
  - R2 的失败可见（`error_code`）→ R4 的演示脚本；
  - R1 的读接口 → R4 前端接真实数据。
- **每次 PR 必须写明**：改了哪个契约 / 迁移 / 测试；影响哪条线。
- 共享契约改动流程：开 issue → 改 `schemas.py` → 通知 R2/R3/R4 → 当天更新 mock/fixture。

## 4. Definition of Done（每条线）

1. 代码：通过 `ruff check .`；目标模块有单元测试或集成测试。
2. 契约：请求/响应与 `docs/architecture.md` §8 一致；错误码符合 §8.3。
3. 数据：涉及写库的改动说明事务边界与幂等/唯一约束。
4. 文档：改契约/迁移时同步 `docs/architecture.md` 或本文；PR 描述写清影响面。
5. 集成：在本地跑 `make test`（或 `pytest -q tests/unit tests/integration`）通过。

## 5. 串行关口与变更流程（当前状态）

| 关口 | 状态 | 证据 |
| --- | --- | --- |
| 契约冻结（schemas/models） | ✅ 已完成 | `services/common/schemas.py`、`models.py`、`docs/architecture.md` §6/§8 |
| 迁移可执行（0002 + 0003） | ✅ 已完成（离线 SQL 校验；本地需跑真实 PG） | `alembic upgrade head --sql`；`scripts/reset_database.py`；`make reset-db` |
| R1 接入链路（批次 → 评论 → Job） | ✅ 已完成 | `services/api/app/ingestion.py`、`POST /review-batches`、集成测试 |
| 静态 UI 五页导航 | ✅ 已完成（mock 数据） | `frontend/`，`/ui/` |
| Worker/AI 规则基线 | ✅ 可跑（R2/R3 继续加固） | `services/worker/app/main.py`、`services/ai/app/main.py` |
| 联调（端到端演示） | ⏳ W6 集成日 | 需先 `make up` + `make seed`，浏览器打开 `/ui/` |

**变更流程**：`main` 保护 → feature 分支 → PR（≤400 行，CI 绿）→ 24h 内评审 → 合并；
迁移只在集成日执行；契约 PR 需至少 2 人评审。

## 6. 风险与边界

- 不让 R3 直接改 Worker 落库逻辑，R2 不让 AI 直接写数据库。
- 前端不在 W5 接真实接口，避免被后端字段变化反复打断；W6 由 R4 逐步替换 mock。
- 迁移一旦在本地/CI apply，后续字段用**新迁移**（0004+），不改历史。
- 评论正文、证据、人工结论属于事实/审计数据：任何线不得用脚本直接改库来"修数据"，
  必须走 API 或明确的数据修复迁移。
