# Repo 审计：现有骨架 vs Proposal《商品评论管理与重复问题发现系统（单平台初版）》

> 历史审计记录：记录的是改造前仓库状态，引用的 Proposal 图/提取脚本已在整理中清理；
> 当前实现进度以 `docs/progress.md` 为准。

审计基准：仓库 `F:\HKUST\MAIE6000c\Assignments\maie6000c-PRI`，HEAD `c044a7a`（2026-10-27）。Proposal docx、两张流程图与 `scripts/_extract_proposal.py` 目前均未纳入 git（`git status` 显示为 untracked）。
一句话结论：**可复用的是"API/Worker/AI/DB 四段式异步管道 + Job 四态 + 健康检查/compose"，不可复用的是全部业务语义（Case/Pitch/Triage）**。Proposal 需要的 Review / IngestionBatch / Issue / ReviewIssue / ReviewRecord 五张表、批量接收入口、has_issue 三态、原文证据定位、人工复核闭环、去重幂等，代码里一处都没有。

## 1. 现有骨架真实能力（逐项判断，不按 README 自述）

| # | 模块/能力（实际做到什么） | 证据（file:line） | 与 Proposal 的关系 |
|---|---|---|---|
| 1 | 四服务 compose（db/api/worker/ai）+ 单镜像 Dockerfile + JSON 日志 | `compose.yaml:18-68`、`Dockerfile:1-17`、`services/common/config.py:26-49` | **可复用**（部署骨架、日志） |
| 2 | 提交即返回：POST 建 case + job，同事务一次 commit，返回 201 | `services/api/app/main.py:45-63`、`:124-132` | 可复用模式；需改造为 `/review-batches` + 202 |
| 3 | 查询 API：GET /cases、/cases/{id}、/jobs/{id}，404 处理 | `services/api/app/main.py:135-156` | 需改造（改 `/reviews` `/issues` 并加筛选/计数） |
| 4 | Job 状态机：pending/claimed/completed/failed 四态枚举 | `services/common/models.py:24-28` | **可复用（枚举值恰好等于 Proposal §4.2）** |
| 5 | Worker 轮询：取最老 pending → claimed + claimed_at + attempts+1 → 调 AI → 完成/失败 | `services/worker/app/main.py:20-36`、`:57-100`、`:105-136` | 需改造（关联键、并发、重试、失败粒度） |
| 6 | AI 服务是独立 FastAPI、HTTP 边界、可替换 | `services/ai/app/main.py:73-87`、`compose.yaml:18-31` | **边界可复用**，实现需替换 |
| 7 | AI 实现：关键词命中打分 + 截断摘要，无 LLM、无 prompt、无模型调用 | `services/ai/app/main.py:20-50` | Proposal §7.2 允许作**基线**，但必须换成新契约 |
| 8 | 持久化：SQLAlchemy 2.0 + psycopg + 连接池 + SQLite 测试兼容 | `services/common/db.py:15-59`、`config.py:13` | 可复用（加行锁/约束即可） |
| 9 | 分析结果：内联写回 `cases.ai_label/ai_summary/ai_confidence`，无历史 | `services/common/models.py:51-53`、`worker/app/main.py:92-95` | **需删除 + 需新增** analysis 留存表 |
| 10 | 失败可见：捕获异常 → job.failed + error(截断 1000) + case.failed | `worker/app/main.py:39-54`、`:132-136` | 需改造（error_code/脱敏/per-review 失败） |
| 11 | 健康检查：api/ai 的 live+ready；api ready 探测 DB | `api/app/main.py:108-121`、`ai/app/main.py:53-70` | 可复用；**Worker 完全没有** |
| 12 | Metrics：api 请求数/延迟/case 数，ai triage 数/延迟（Prometheus） | `api/app/main.py:32-42`、`:79-100`、`ai/app/main.py:17-18` | 需改造（path 高基数、无 job/AI 失败指标） |
| 13 | 迁移：0001 建 cases/jobs，无任何唯一约束、无分析结果表 | `alembic/versions/20260713_0001_create_initial_tables.py:18-47` | 需新增迁移；旧表需处置 |
| 14 | 测试：4 个文件约 6 用例，SQLite `create_all` 建库 | `tests/conftest.py:10-24`、`tests/unit/test_ai_service.py`、`tests/integration/` | 需新增（契约/worker/迁移/复核） |
| 15 | CI：ruff + alembic upgrade + pytest(unit/integration)，带 Postgres service | `.github/workflows/ci.yml:12-52` | 可复用，需补迁移往返/worker 测试 |
| 16 | 文档：README/architecture/operations/week04 全部是 Pitch 项目 | `README.md:1-9`、`docs/architecture.md:3-65`、`docs/operations.md`、`templates/submissions/week04/README.md:5-16` | **需删除/重写**（见 §2 表 C） |
| 17 | 指标/领域常量：`CASES_CREATED`、`JobType.TRIAGE_CASE`、seed 工单数据 | `api/app/main.py:42`、`models.py:31-32`、`scripts/seed_demo_data.py:6-25` | **需删除**（旧领域） |

### 关键判断（结论式回答）

- **Job 状态机是否够用？** 值够，边不够。四态与 Proposal 完全一致（`models.py:24-28`），但代码只实现 `pending→claimed→completed/failed` 单向（`worker:20-36,92-100`），没有图 2 状态机 1 的 `failed→pending` 重试边；`attempts` 只在领取时 +1（`worker:33`）且无上限配置，实际永远等于 1，是死字段。Job 与单 Case 1:1 硬绑定（`models.py:76-80` 非空 `case_id`），无法表达"一个批次任务"。
- **claim 是否并发安全？** 否。`claim_next_pending_job` 是"先 SELECT 再 UPDATE+COMMIT"（`worker:21-35`），无 `FOR UPDATE`/`SKIP LOCKED`、无版本号/租约；两个 Worker 副本会领到同一 Job，`attempts+1` 与 AI 调用都会重复。`process_job` 完成/失败写入也不校验状态（`worker:83-100`、`39-54`），过期 Worker 可覆盖已重领的 Job。
- **AI 契约能否承载 has_issue 三态与 evidence？** 不能。`TriageResponse` 只有 `label/summary/confidence` 三个字段（`schemas.py:59-62`），无 `review_id`、无 `has_issue∈{true,false,unknown}`、无 `issues[{category,description,evidence}]`、无多问题、`summary` 还限 500 字；Worker 用它硬校验（`worker:81`），换真 LLM 后必然大面积校验失败。
- **有分析结果留存与 model/prompt 版本吗？** 没有。结果被覆盖写回 Case 行（`worker:92-95`），无 raw output、无 `model_identifier`、无 `prompt_version`；`config.py:10-18` 也没有模型/prompt/供应商配置项。注意 `docs/architecture.md:59-65` 声称有 `analysis_results` 表及这两个字段，但迁移和 models 里都不存在——文档本身也不是真相。
- **有 Issue / ReviewIssue 相关表吗？** 没有。全仓 Python 仅 `cases`/`jobs` 两张表（`models.py:35-114`、迁移 0001），grep `issue|review|platform|source_review|evidence` 在 services 下零命中；人工复核、改名/合并/拆分/驳回、跟进记录全部无落点。
- **错误处理与重试能力？** 只有"捕获所有异常→标失败"。无错误分类、无重试/退避、无 `max_attempts`（`config.py:10-18`）、无幂等；`job.error` 原样通过 `JobRead` 暴露给调用方（`schemas.py:40`、`api:151-156`），可能带内部 URL/输入片段，违反 `docs/architecture.md:114` 的"不暴露内部栈"。
- **Metrics / 健康检查？** API/AI 有，Worker 没有：worker 无 HTTP 端口、无 healthcheck（`compose.yaml:54-68`）、Prometheus 只抓 api/ai（`observability/prometheus.yml:5-11`）；API 指标把 `request.url.path` 当标签（`api:88-91`），`/cases/{uuid}` 会造成 Prometheus series 基数爆炸。
- **迁移与测试覆盖？** 迁移仅 1 个且无唯一约束/CHECK；pytest 用 SQLite `create_all`（`conftest.py:16`）绕过 alembic，**迁移从未被测试覆盖**；Worker、AI 契约、失败重试、迁移往返、Issue 流程均无用例。

## 2. 差距清单

### 表 A：Proposal 需要但代码没有的表/字段/接口/流程

| Proposal 要素 | 代码现状 | 动作 |
|---|---|---|
| Review（platform、shop、product_id、review_date、正文、source_review_id、ingested_at、analysis_status） | 只有 `cases(title, description, status, ai_*)`（`models.py:35-69`、迁移 0001） | 新增 + 改造（`cases` 改 `reviews`，删 `title`，`description`→`body`） |
| IngestionBatch（文件名/入口、接收行数、成功/失败数、校验错误清单、来源） | 无 | 新增 |
| Issue（product_id、category、标题、状态 proposed/confirmed/resolved/dismissed、建议数/确认数） | 无 | 新增 |
| ReviewIssue（review_id、issue_id、suggested/accepted/rejected、evidence、来源） | 无 | 新增 |
| ReviewRecord（改名/合并/拆分/驳回/跟进措施、操作人、备注） | 无 | 新增 |
| Job 改造（关联对象、job_type 取值、error_code、max_attempts、next_attempt_at） | `case_id` 非空 + `TRIAGE_CASE`（`models.py:76-85`） | 改造 |
| 分析产物留存（has_issue、raw output、model_identifier、prompt_version） | 无（只有覆盖写回 3 个 ai_* 字段） | 新增（analysis_runs） |
| 去重/幂等约束：unique(platform,shop,source_review_id)、unique(review_id,issue_id) | 0001 无任何 unique（迁移 0001:18-47） | 新增（必须进 0002 迁移） |
| POST /review-batches（201/202、批量校验、错误行号不落库） | 无；仅有 POST /cases | 新增 |
| GET /reviews（按 product/date/category/status 筛选）、GET /issues（同样筛选+计数） | 只有 GET /cases（limit only，`api:135-140`） | 新增/改造 |
| POST /issues/{id}/review（确认/改名/合并/拆分/驳回/记录措施） | 无 | 新增 |
| GET /jobs/{id} | 已有（`api:151-156`） | 可复用，补 error_code/attempts/时间 |
| 统计口径（接收量/成功分析量/失败量、去重评论数、AI 建议数 vs 人工确认数） | 无 | 新增聚合查询 |
| CSV/接口入口适配（`python-multipart`、编码、行列上限、预览） | 依赖清单无 `python-multipart`（`pyproject.toml:11-22`），无上传代码 | 新增 |
| 真实模型接入（provider/key/model/timeout/prompt 版本、prompt 注入防护） | 无 LLM SDK、无 key/model 配置（`pyproject.toml:11-22`、`config.py:10-18`、`.env.example:1-9`） | 新增 |
| Worker 可观测（health/metrics/queue depth/失败计数） | 无（`compose.yaml:54-68` 无 healthcheck） | 新增 |

### 表 B：会误导实现的遗留（必须在开工前删干净）

| 遗留 | 证据 | 处理 |
|---|---|---|
| `Case` / `CaseStatus`（含从未使用的 `NEW`、`TRIAGED`） | `models.py:17-21,35-69` | 删除，替换为 Review/Issue 语义 |
| `CaseCreate` / `CaseRead`（含 `ai_*` 对外字段） | `schemas.py:15-31` | 删除，按 Review 重写 |
| `TriageRequest` / `TriageResponse` | `schemas.py:53-62`、`ai/app/main.py:35-50`、`worker:75-100` | 删除，替换 Analyze 契约 |
| `ai_label` / `ai_summary` / `ai_confidence` 内联列 | `models.py:51-53`、迁移 0001:24-26 | 0002 迁移 drop |
| `JobType.TRIAGE_CASE` 及所有断言 | `models.py:31-32`、`api:56`、`tests/integration/test_api_case_flow.py:26` | 改为评论分析任务类型 |
| 服务标题/指标名 `Starter API`、`CASES_CREATED`、`api_cases_created_total` | `api:30,42`、`ai:15` | 改名或删除 |
| seed 数据是"登录/发票/宕机"工单 | `scripts/seed_demo_data.py:6-25` | 换成箱包评论（拉链/肩带/容量/色差/无问题） |
| smoke 断言 `status=="triaged"` 与 triage 标签集合 | `tests/smoke/test_smoke_cases.py:37-50` | 按新流程重写 |
| 根路由 `/` 返回 `service="api"` 尚可留；health 语义需复审 | `api:103-116` | 保留+扩展 |

### 表 C：三方不一致（必须写进给评审的说明）

1. `README.md:1-9`、`docs/architecture.md:3-135`、`docs/operations.md`、`templates/submissions/week04/README.md:5-16` 描述的是 **Pitch 反馈助手**（pitches/jobs/analysis_results 三表、POST /pitches、/analyse-pitch）；但 `models.py`、迁移、seed、tests 实现的是 **Case/Job triage**（cases/jobs 两表、POST /cases、/triage）；正式 Proposal（docx）要求的又是 **商品评论** 领域。三套语义互不相同，其中没有任何一套被完整实现。
2. `docs/architecture.md:59-65` 描述的 `analysis_results` 表与 `model_identifier`/`prompt_version` 字段在代码中不存在，不能当作既有能力假设。
3. Proposal docx、两张流程图（`docs/63b9...png`、`docs/2cb8...png`）和 `scripts/_extract_proposal.py` 还是 untracked；若队友 clone 仓库看不到 Proposal，实现基线会继续漂移。

## 3. 具体缺陷与修改建议

### P0（不修就跑不通/一定出错）

| # | 问题（一句话） | 证据 | 改法（文件/函数/表/字段） | 验证方式 |
|---|---|---|---|---|
| P0-1 | 数据模型与 Proposal 五实体完全不对应，评论/问题组无处可存 | `models.py:35-114`、迁移 0001:18-47 | 重写 `services/common/models.py`：reviews、ingestion_batches、issues、review_issues、review_records、analysis_runs；重写 `schemas.py`；新增迁移 0002 | `alembic upgrade head` 后 `\d` 查表；插入一条 review+issue+review_issue 集成用例 |
| P0-2 | API 全链路仍是 case/triage，Proposal 要求的入口/查询接口均不存在 | `api/app/main.py:124-156` | 重写 `api/app/main.py`：POST /review-batches(202)、GET /reviews、GET /issues、POST /issues/{id}/review；保留 GET /jobs/{id} | TestClient 用例覆盖 5 个接口 + 422/404/202 |
| P0-3 | Job 与单 case 强绑定且失败即把 case 标 failed，批次/逐条隔离无法表达 | `models.py:76-80`、`worker:46-52` | `Job.case_id`→`review_id`(可空)+`batch_id`(可空)，补 `error_code/next_attempt_at`；失败只改该 review 的 analysis_status | 建 3 条评论 1 批次 → 3 个 pending job；1 条失败不影响其余 2 条 |
| P0-4 | AI 契约无法表达 has_issue 三态、多问题、evidence、模型/prompt 版本 | `schemas.py:59-62`、`worker:75-100` | 新 `AnalyzeRequest(review_id, body, product_id)`；`AnalyzeResponse(review_id, has_issue, issues[{category,description,evidence}], model_identifier, prompt_version)`；worker 校验 evidence 必须为原文子串，否则降级 unknown | 契约单测：有/无/未知三态、多问题、evidence 不在原文时判无效并转人工 |
| P0-5 | 无去重与幂等约束，重传 CSV 或重试会重复计数/重复归组（Proposal §4.3 明确要求） | 迁移 0001 无 unique；`scripts/seed_demo_data.py:31-48` 无 upsert | 0002 加 `uq_reviews_source(platform, shop, source_review_id)`、`uq_review_issue(review_id, issue_id)`；入库走 ON CONFLICT/查询后插入 | 连发两次相同批次：review 数与 issue 计数不变（集成测试） |
| P0-6 | 没有 Issue/ReviewIssue 状态机与复核接口，"确认/改名/合并/拆分/驳回/记录措施"无法实现 | 无相关表/接口 | 新增状态转换白名单（proposed→confirmed/dismissed，confirmed→resolved，resolved→confirmed；suggested→accepted/rejected 可改判；dismissed 终态）；POST /issues/{id}/review 记 ReviewRecord，合并/拆分写关联变更记录 | 合法/非法转换各测一次；dismissed 后再改返回 409 |

### P1（功能对但会出错/难运维）

| # | 问题 | 证据 | 改法 | 验证 |
|---|---|---|---|---|
| P1-1 | claim 非并发安全，无租约/幂等 | `worker:20-36` | 改 `with_for_update(skip_locked=True)` 或 `UPDATE jobs SET status='claimed' WHERE id=(SELECT id … FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *` | 两个 session 并发领取，只成功一个 |
| P1-2 | 完成/失败写入不校验当前状态，过期 Worker 可覆盖；无信号处理，SIGTERM 会留在 claimed | `worker:39-54`、`:83-100`、`:105-136` | 完成/失败 `UPDATE … WHERE status='claimed' AND claimed_at=:seen_claimed_at`；加 SIGTERM handler 处理完当前 Job 再退 | 模拟重领后旧 worker 提交被拒；`docker stop` 后无 claimed 残留 |
| P1-3 | 无有限重试/退避，AI 瞬时失败即永久 failed | `worker:132-136`、`config.py:10-18` | 加 `worker_max_attempts`、`worker_retry_backoff_seconds`、`next_attempt_at`；ATTEMPTS<max 时回 pending，否则 failed | AI 连续 503 两次后成功→completed；第 3 次仍失败→failed |
| P1-4 | 错误原样暴露且不可分类 | `schemas.py:40`、`worker:48` | 存 `error_code`（AI_TIMEOUT/AI_INVALID_OUTPUT/DB_ERROR…）+ 安全 message；API 只返回 code/短文案，完整错误进日志 | 令 AI 抛错，断言响应不含 traceback/URL/输入 |
| P1-5 | 无分析产物留存与 model/prompt 版本，无法回溯/评测 | `worker:92-95`、`config.py:10-18` | 新增 `analysis_runs(id, review_id, has_issue, raw_json, model_identifier, prompt_version, error, created_at)`；配置加 provider/model/prompt_version | 重跑后旧 run 仍在；按 prompt_version 可统计 |
| P1-6 | Worker 无 health/metrics，失败不可观测 | `compose.yaml:54-68`、`prometheus.yml:5-11` | Worker 起轻量 HTTP（或把 worker 统计写 DB，由 API `/metrics` 汇总）；指标：claimed/completed/failed/queue_depth/ai_latency；compose 加 healthcheck | up 后 `/metrics` 出现 worker 指标；失败一次计数 +1 |
| P1-7 | API metrics 以原始 path 为标签，UUID 路径导致基数爆炸 | `api:88-91` | 用 `request.scope["route"].path`（路由模板）或只对已知路由打标签 | 请求 100 个不同 case_id 后 series 数不增长 |
| P1-8 | 测试用 SQLite `create_all` 绕过 alembic，迁移与模型漂移不可见；0001 也无约束 | `tests/conftest.py:10-24` | 用 CI 的 Postgres service 跑一个 upgrade→downgrade→upgrade 迁移测试；单测可继续 SQLite | CI 新增 migration round-trip job |
| P1-9 | 批次内一条评论失败会拖垮整批（无逐条隔离/失败计数） | `worker:57-100` 单次异常全批失败 | reviews 加 analysis_status(success/failed/unknown) + 批次计数在 worker 内逐条推进 | 3 条中 1 条 AI 失败，另 2 条成功且批次显示 2/1 |
| P1-10 | LLM 接入前置条件缺失（SDK/key/model/timeout/prompt 文件） | `pyproject.toml:11-22`、`config.py:10-18`、`.env.example:1-9` | 加 provider SDK、`ai_provider/ai_model/ai_api_key/ai_timeout`、prompt 模板文件；`/health/ready` 校验配置完整 | 缺 key 时 ready 返回 503、/analyze 返回明确错误 |

### P2（质量/边界/卫生）

- **枚举无 DB 约束**：status 是 `String(20)` 可写任意值（迁移 0001:23,37），改 String+CHECK（跨库一致），避免脏状态导致 API 500。
- **评论字段校验沿用 case 规则**：`title` 必填 3-200、`description` 5-4000（`schemas.py:15-17`）会拒绝无标题或"好/差评"类短评，批量入口需独立校验；正文上限可放宽。
- **CSV 健壮性**：编码探测（utf-8-sig/GBK）、行数/大小上限、错误清单带行号（图 1 明确"不落库"）、去重预检。
- **prompt 注入**：Proposal 风险表要求"评论视作数据、不执行其中指令"，实现 prompt 时需分隔+系统指令约束；evidence 定位失败应转 unknown，不得编造。
- **链路关联 ID**：API→Worker→AI 传 `x-request-id`/`review_id`，日志可串（`api:92-100`、`worker:125`、`ai:79-86`）。
- **ready 语义**：DB 故障时 `/health/ready` 抛 500 而非 503（`api:113-116`）。
- **seed/演示数据**：换成箱包评论样例（拉链、肩带、容量、色差、无具体问题），保留一条"AI 不可用→job failed"的演示路径。
- **仓库卫生**：`tests/integration/test_api_integration.py python`（已提交、764B，因不以 `.py` 结尾**永不被 pytest 收集**，等于一个隐藏的重复测试）；`.dsh_probe.txt`；Proposal docx 与流程图未提交。建议删除/改名/提交。
- **confidence 语义**：`ai:47` 的分数与 `schemas.py:62` 的 confidence 不能被当作校准概率，UI/排序不得据此下结论（Proposal §7.2 明确）。

## 4. 迁移 / 测试 / CI 演进建议

### Alembic

1. **不要改 0001 历史**（CI 已 `alembic upgrade head`，课程评审看迁移链）；新增 `alembic/versions/2026xxxx_0002_review_management.py`，`down_revision="20260713_0001"`。
2. 0002 内容（顺序有意义）：建 `ingestion_batches`→`reviews`→`issues`→`review_issues`→`review_records`→`analysis_runs`；`jobs` 加 `review_id/batch_id/error_code/next_attempt_at`、迁走 `case_id`；drop `cases.ai_label/ai_summary/ai_confidence`；最后处理 `cases`/`jobs.case_id`。
3. **旧表二选一**（推荐 a）：
   a) 保守迁移：`cases` 保留数据 → 新建 `reviews` 后按 `description→body`、`created_at→ingested_at`、`platform='demo'` 搬迁，再 drop `cases` 与 `jobs.case_id`；本地 3 条 seed 数据可接受。
   b) 激进迁移：确认无真实数据后 0002 直接 `drop_table("jobs")`/`("cases")` 并按新结构重建（downgrade 恢复 0001 形态）。课程脚手架数据无价值时更快，但 less impressive。
4. 约束/索引一并进迁移：`uq_reviews_source(platform,shop,source_review_id)`、`uq_review_issue(review_id,issue_id)`、`ix_issues(product_id,status)`、`ix_reviews(product_id,review_date)`、`ix_jobs(status,created_at)`；status 用 CHECK 而非 PG enum（SQLite 测试友好）。
5. 若测试仍用 SQLite，列改名/删约束必须 `op.batch_alter_table`；**更推荐测试统一到 Postgres** 与 compose 一致。
6. `downgrade()` 必须真实可跑（CI 加 `alembic downgrade base && alembic upgrade head`）。

### 测试缺口（按优先级）

- **契约测试**：AnalyzeRequest/Response 三态、多 issue、evidence 必须原文可定位、版本字段必填。
- **Worker 单测**（不依赖 PG，可用 SQLite+override）：claim 只领一次、失败重试到上限、完成事务原子性、过期 claim 写入被拒、error_code 映射。
- **API 集成**：POST /review-batches 的 202/校验错误行号/重复批次幂等；GET /reviews 与 /issues 的筛选+计数；POST /issues/{id}/review 合法/非法转换；已关闭 Issue 收到同类评论→提示不进计数。
- **迁移**：upgrade/downgrade 往返 + 关键约束存在性断言。
- **smoke**：新 E2E（上传→job→issue→复核→跟进），并保留"AI 不可用→job failed 且不伪造结果"。
- 现有 `tests/integration/test_api_case_flow.py:24-27`、`tests/smoke/test_smoke_cases.py:37-50`、`tests/unit/test_ai_service.py` 的旧领域断言全部重写；隐藏文件 `test_api_integration.py python` 合并或删除。

### CI

- 保留 `ruff` + `alembic upgrade` + pytest（`.github/workflows/ci.yml:45-52`）；新增迁移往返 step、Postgres-backed 测试 step（已有 PG service，`ci:12-25`）。
- 加一个 `docker compose build`（或至少 `docker compose config`）防止 compose/Dockerfile 漂移；smoke 可选（`docker compose up -d` + `--wait` 后再跑，耗时约 1–2 分钟）。
- 注意 `ci:29` 的 `AI_SERVICE_URL=http://localhost:8100` 指向并不存在的服务；一旦加 worker 集成测试，要么用 `httpx.MockTransport`/TestClient 注入，要么在 CI 里启动 AI 服务。
- 可选：pytest-cov 阈值（`pyproject.toml:24-29` 已装 pytest-cov 但未启用）。

## 5. 给 Lead 的 3 条最重要结论

1. **"管道可留、语义全换"**：四服务骨架、Job 四态、事务性建任务、JSON 日志、health/compose 可直接复用；但 `models.py`/`schemas.py`/`api/main.py`/`worker/main.py`/`ai/main.py` 五处必须一次性替换为评论领域，先落 1 个 0002 迁移 + 1 个 schema 替换 PR，再并行拆 3 个 PR（批量入口/去重、AI 证据与版本、Issue 复核闭环），否则会有人在 Case/Triage 上继续写代码。
2. **三件事必须在写 AI 之前定死**：①新 AI 契约（`review_id, has_issue∈{true,false,unknown}, issues[{category,description,evidence}], model_identifier, prompt_version`）；②Job 关联（推荐 Job↔Review 1:1 + IngestionBatch 汇总计数，改动最小且支持逐条失败隔离）；③去重唯一键 `(platform, shop, source_review_id)` 与 `(review_id, issue_id)`——这三项晚定会连带返工迁移、计数口径和评测脚本。
3. **文档/演示物先对齐再开工**：README、architecture、operations、week04 README 仍是 Pitch 项目，且 Proposal docx 与两张流程图还未提交 git；建议第一步提交 Proposal+图、重写根 README 与 architecture 为商品评论领域（week04 作为历史产物保留并注明），否则验收时文档与实现互相矛盾，评委无法判断需求基线。
