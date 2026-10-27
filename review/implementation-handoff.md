# 实现交接说明（契约与数据层阶段）

> 注：本文是契约/数据层阶段的交接记录。后续 0003 已移除旧骨架，R1 接入链路、
> Worker/AI 基线与静态 UI 均已完成；**最新状态以 `docs/progress.md` 为准**，
> 分工边界见 `docs/team-division.md`。文内校验脚本与参考 SQL 属于当时的过程产物，
> 已在整理中清理。

> 本次交付把评审报告 §4 从"设计"落成"文档 + 数据层代码 + 迁移"，
> 目标是让 R1–R4 可以并行开工，而不是等一个人写完再交接。
> 复核记录见 `review/impl-review.md`（P0×3 / P1×10 / P2×12）。

## 1. 交付内容

| 文件 | 变更 | 说明 |
| --- | --- | --- |
| `docs/architecture.md` | **重写**（约 648 行） | 按报告 §4：目标架构、9 张表、4 条状态机、14 组接口、AI 契约与证据校验、失败重试、统计口径、迁移与测试 |
| `assets/fig1_end_to_end_flow.png` | 新增 | 重绘的图 1（12 步主流程 + 校验重传 / 重试 / 关组提示三条回流） |
| `services/common/models.py` | **重写** | 新领域 8 张表 + `jobs` 扩展；`Case` 标记 LEGACY 保留，0003 删除 |
| `services/common/schemas.py` | **重写** | 新契约 + legacy 契约保留；`ExtractionResult` / `IssueActionRequest` / `BatchProgressRead` / `StatsSummaryRead` 等 |
| `services/common/categories.py` | 新增 | 受控类别常量 + `CATEGORY_VERSION`（R3 直接用） |
| `alembic/versions/20261027_0002_review_management.py` | 新增 | 8 张新表 + `jobs` 扩字段 + 约束/索引；**不删 `cases`**；downgrade 可回 0001 |
| `.github/workflows/ci.yml` | 修改 | 增加 `downgrade → upgrade` 往返步骤 |
| `review/` | 新增 | 评审报告、独立评审与过程文档（工具脚本与中间产物已清理） |

## 2. 关键决策（已写进 architecture.md）

1. **1 条评论 : 1 个 Job**，批次只做汇总；`uq_jobs_active_comment` 保证同评论最多一个非终态 Job。
2. **Job 重试只回 `pending`**，禁止 `failed→claimed`；`attempts` 计认领次数（含租约回收），自动重试上限 `max_attempts=3`，人工重放清零并写审计。
3. **`dismissed` 可人工重开**（方案 A）；改名/合并/拆分只写 `issue_actions`，不改状态。
4. **AI 只写 `suggested`**；`accepted/rejected` 永不因重跑覆盖；重跑把旧 AI 建议写 `superseded_at`。
5. **批次状态只持久化导入阶段**；`completed/partially_failed` 由接口读时聚合派生，避免双写。
6. **过渡策略**：0002 追加、legacy 接口继续可用；0003 删 `cases`、`ai_*`、旧接口与旧测试。

## 3. 本地验证（历史记录）

> 以下命令与结果记录于契约/数据层阶段；对应校验脚本与参考 SQL 已按整理要求清理。
> 真实 PostgreSQL 迁移往返、端到端与 UI 验收结果见 `docs/progress.md`。

- models/migration/schemas 静态一致：all static checks passed。
- 文档 §6.2 字段 vs 模型 vs 迁移：all doc/code consistency checks passed。
- SQLite 建表 + 约束 + 契约 + legacy：全部 ok（仅一个活跃 Job、`ck_jobs_*`、`CommentDetailRead` 非空列表）。
- 旧 API 流程历史校验：11 项 ok（`POST /cases`、`GET /cases`、`GET /jobs`）。
- 迁移离线 SQL：`upgrade head --sql` 与 `downgrade head:20260713_0001 --sql` 均 EXIT=0（参考 SQL 已清理）。
- 旧单元测试：2 passed（当时 integration 受本地 tmp 权限限制，未执行）。

运行环境：`D:\Conda\python.exe`（含 SQLAlchemy/Pydantic/FastAPI），`PYTHONPATH=仓库根`。

## 4. 复核结论的关闭情况

复核给了 3 个 P0，均已在本轮修复并加回归校验：

| P0 | 修复 |
| --- | --- |
| P0-1 批次进度契约缺失 | 新增 `BatchProgressRead`（analyzed/failed/pending/processing/coverage/scope）；202 改为 `{batch_id, status, declared_rows}`，`job_count` 由进度接口给出；文档 §4.1/§4.2/§8.1 同步 |
| P0-2 证据列表静默为空 | `Comment.issues` / `Issue.links` 只读别名；`CommentIssueRead` 增加 `comment_id/analysis_run_id/comment_version/superseded_at`；`CommentDetailRead` 增加 `revisions`/`latest_analysis_run`；回归脚本断言关联非空 |
| P0-3 jobs 无枚举 CHECK/默认值污染 | 迁移与模型新增 `ck_jobs_status`/`ck_jobs_job_type`/`ck_jobs_type_target`（extract_issues 必须挂 comment，triage_case 必须挂 case）；回归脚本验证混写被拒 |

P1 中已一并处理的：`as_of/scope` 与统计契约（`QueryScope`/`StatsSummaryRead`）、批次终态派生规则、旧 `GET /jobs` 不再 500（`JobRead.case_id` 可空 + 按 job_type 分流）、受控类别常量模块、`superseded_at/comment_version`、无稳定编号的合成 `source_review_id` 契约、合并冲突规则、评论详情版本/AI 输出契约、split/change 必填校验、CI 迁移往返。

尚未做（当时有意留给 R1–R4 后续）：

- API / Worker / AI 的具体实现（当次只落契约与数据层；当前已完成最小实现）。
- `server_default` 在模型与迁移之间的完全对齐（P2-5，仅影响裸 SQL 插入，ORM 插入不受影响）。
- `error_code` 的 DB CHECK（P2-3，保持应用层枚举便于扩展）。
- `docs/operations.md`、`README.md` 重写（当前已完成）。
- 前端 / 演示页面（当前已完成静态界面；真实接口待接入）。

## 5. 接手顺序（按角色）

1. **R1**：先 `git add` 本次交付物（`0002`、`assets/`、`review/`、`models/schemas/categories`、`docs/architecture.md`、`ci.yml`）；本地跑一次真实 `alembic upgrade/downgrade/upgrade`；然后按 §8.1 建批入口与查询接口。
2. **R2**：按 §7.1/§9.1 实现原子认领、租约、fencing、重试与错误分类；`attempts` 语义见 §6.3；不要复用 legacy 的 `JobRead`。
3. **R3**：`categories.py` 已给常量与版本；先实现"规范化正文 + 证据子串校验"函数（Worker 与 AI 共用），再实现提取与归组。
4. **R4**：先按 `CommentIssueRead`/`IssueDetailRead` 定稿复核抽屉的数据契约（证据非空由服务端组装），再做 `issue_actions` 与页面。

## 6. 注意

- **不要再改 0002/0003**：迁移历史已 apply；后续字段用 0004+。
- 交付物已提交到本地 git；远程推送由团队决定。
- 迁移目标 PostgreSQL；SQLite 只用于 `create_all` 单测。

