# 实现复核：architecture.md / 0002 迁移 / models.py + schemas.py

> Historical engineering review; findings describe the version reviewed at that time.
> Current implementation: [Architecture](../docs/architecture.md) and [Progress](../docs/progress.md).
>
> 历史工程评审，结论对应当时受评版本。当前实现见[系统架构](../docs/architecture.md)和[项目进度](../docs/progress.md)。

> 历史复核记录：文内校验脚本、参考 SQL 与图表属于当时的过程产物，已在整理中清理；
> 结论保留，作为契约与数据层的复核依据。

复核对象：`docs/architecture.md`（607 行）、`services/common/models.py`（577 行）、`services/common/schemas.py`（352 行）、`alembic/versions/20261027_0002_review_management.py`（322 行）、`assets/fig1_end_to_end_flow.png`；对照 `review/系统设计评审与四人分工.md`（下称"报告"）§3 P0/P1、§4、§5、§6、§7。
复核方式：跑现成三个脚本 + 自写内联 Python 比对（不落盘）+ alembic 离线 SQL + 逐行读代码；除本文件外未改动任何仓库文件。

## 一、总体判断

**可以交给团队继续开发**：数据层骨架达到契约冻结要求——9 张表在文档 §6.2、模型、迁移三方字段一致，约束/索引名在模型与迁移中同时成立，legacy `Case` 过渡方案自洽，迁移可离线 upgrade/downgrade，SQLite `create_all` 可用。**但不能按现状直接进入实现**：3 个 P0 会让 R1/R4 在"批次进度、证据展示、Job 数据纯度"上返工；P1 中还有若干属于"契约冻结前必须定稿"的条目，建议在契约冻结前补齐再冻结。

### 已验证通过（有输出佐证）

1. 静态一致校验 → `RESULT: all static checks passed`：9 表列名集合与迁移一致；`jobs` 恰好新增 6 列（comment_id/batch_id/max_attempts/next_attempt_at/lease_expires_at/error_code）；downgrade 覆盖全部 8 张新表。**注意该脚本只比对列名集合，不比对类型/可空性/默认值**，以下第 2 条由我另行逐列核对。
2. 字段级：文档 §6.2 九行表格 vs `models.py` 的 `__tablename__ + mapped_column` vs 迁移 `create_table`，我用脚本自动比对列名集合，8 张表 `doc=model` 完全一致，`jobs` 唯一"差异"只是文档把注解写进了字段清单（`case_id（legacy 可空）`，格式问题见 §六-17）；类型（String 长度/Text/BigInteger/Float/Boolean/JSON）、可空性、`DateTime(timezone=True)` 逐列核对无实质偏差（`server_default` 差异见 P2-5）。
3. 约束名：文档 §6.2 引用的 `uq_comments_source`、`uq_ingestion_batches_idempotency_key`、`uq_jobs_active_comment`、`ck_jobs_target` 在模型与迁移中都存在；`uq_comment_revisions_version`、`uq_comment_issues_pair`、`ck_*` 枚举 CHECK 名称模型/迁移一致。
4. 运行时约束校验 → 全部 ok：SQLite `create_all` 建表；`unique(platform, shop, product, source_review_id)` 生效；`uq_jobs_active_comment` 部分唯一索引在 SQLite 生效且 `completed` Job 不与之冲突；`analysis_status` CHECK 生效；`ck_jobs_target` 拒绝既无 case_id 又无 comment_id 的 Job；`ExtractionResult` 三态校验、`IssueActionRequest` 必填校验、legacy `JobRead` 与新版 `AnalysisJobRead` 均可用。
5. 旧 API 流程历史校验 → 11 项全 ok：`POST /cases → 201`、case=queued、job=pending、job_type=triage_case、`GET /cases`、`/cases/{id}`、`/jobs/{id}` 均可跑，legacy 与新版模型共存不冲突。
6. `D:\Conda\python.exe -m pytest -q tests/unit` → `2 passed`；`--collect-only tests/unit tests/integration` → `4 tests collected`（integration 实际执行受 tmp_path 沙箱限制，按要求未调试）。
7. 迁移离线校验：`alembic upgrade head --sql` EXIT=0（280 行）；`alembic downgrade head:20260713_0001 --sql` EXIT=0；生成的 up/down SQL 与当时的参考 SQL 逐行一致（仅差 alembic 日志行）；参考 SQL 已在整理中清理。
8. 迁移 `upgrade`/`downgrade` 顺序正确：先 `ALTER TABLE jobs ALTER COLUMN case_id DROP NOT NULL` 再加列/FK/索引；downgrade 先删部分索引与 `ck_jobs_target` → 删 FK → 删列 → `DELETE FROM jobs WHERE case_id IS NULL` → 恢复 `SET NOT NULL` → 按依赖逆序删表（`issue_actions` → `comment_issues` → `issues` → `analysis_runs` → `batch_rows` → `comment_revisions` → `comments` → `ingestion_batches`），无悬挂 FK。
9. 状态机：文档 §7.1 明确"**禁止 failed → claimed**、重试只回 pending"（`architecture.md:280`），§7.4 "重跑只 supersede origin=ai AND status=suggested，不触碰 accepted/rejected"（`:331`），§7.3 "改名/合并/拆分不改状态、dismissed 可人工重开"（`:300-314`）——与报告 §3 P0-3/P0-5/P0-7 结论一致；全文已无 `failed→claimed`、"confirmed 即结束"、"错误清单不落库"、"不进计数"等旧说法（图 1 图注为"不进确认数"，正确）。
10. 图 1（`assets/fig1_end_to_end_flow.png`）12 步与文档 §4.1 编号一一对应，含两条回流环（校验失败重传、可重试回 pending）与关组后提示；路径 `../assets/fig1_end_to_end_flow.png` 从 `docs/` 解析正确（`architecture.md:70`），文件存在。

## 二、P0（阻断/返工，开工前必须改）

### P0-1 批次进度契约缺字段；202 返回的 `job_count` 本身不可知
- **证据**：`BatchRead` 只有导入阶段计数，无 analyzed/failed/进度字段（`schemas.py:71-81`）；但文档 §8.1#2 写"返回 `BatchRead`；analyzed/failed 由 Job 实时聚合"（`architecture.md:347`）、§4.2 写"批次进度由 Job 聚合实时派生"（`:103-105`）。另 §4.1 第 2 步 202 就返回 `{batch_id, status, job_count}`（`:76`、`:147`），而逐行校验在第 3 步异步做（`:77-81`）——202 时无法知道有效行数/Job 数。
- **后果**：R1 实现 `GET /review-batches/{id}` 时无字段可返；R4 的"部分成功"早期演示（验收项 3"成功+失败=接收"）必须改契约后返工；`job_count` 只能填 0 或把校验前移，两种做法都要改文档。
- **改法**：新增 `BatchProgressRead(analyzed_rows, failed_rows, pending_rows, processing_rows, analysis_coverage, as_of, scope)`；`BatchCreateResponse.job_count` 改为 202 时可为 `None`（或用导入阶段行数改名 `declared_rows`），并在文档 §4.1/§8.1 二选一写死。

### P0-2 证据/关联读契约与 ORM 属性名不一致，会**静默**返回空列表
- **证据**：`CommentDetailRead.issues`（`schemas.py:126`）、`IssueDetailRead.links`（`:164`）与 ORM 属性名 `issue_links`（`models.py:291`、`:395`）不一致；实测 `CommentDetailRead.model_validate(comment)` → `issues=[]`、`IssueDetailRead.model_validate(issue)` → `links=[]`，**不报错**（pydantic from_attributes 对缺失属性用默认值）。且 `CommentIssueRead` 无 `comment_id`（`schemas.py:94-105`），IssueDetail 的关联证据无法指回评论。
- **后果**：R4 的复核抽屉/评论详情"原文证据高亮"会拿到空数组而不自知（演示时直接失败）；验收项"未定位到证据的 issue 不出现在 UI"会假通过；证据是本项目核心卖点，属最高优先级返工点。
- **改法**：字段改为 `issue_links` 或在 API 层显式组装 `CommentIssueRead`；`CommentIssueRead` 增加 `comment_id`、`comment_body`（当前版本正文）、`analysis_run_id`；`IssueDetailRead` 补 `product_id/batch_id` 等筛选用字段。建议加一条契约测试：`IssueDetailRead.model_validate(issue)` 后 `len(links)==1`。

### P0-3 `jobs` 缺 status/job_type CHECK，且 `job_type` 默认值仍是 legacy `triage_case`
- **证据**：`models.py:512-521` 中 `job_type` 默认 `JobType.TRIAGE_CASE`、`status` 无 CHECK；迁移 0002 只加 `ck_jobs_target`（`20261027_0002_review_management.py:268-270`），没有 `ck_jobs_status`/`ck_jobs_job_type`；而"同一评论最多一个非终态 Job"的部分唯一索引依赖 status 字面值 `pending/claimed`（`models.py:492-498`）。文档 §6.3 却声明"状态枚举用 String + CHECK"（`architecture.md:252`，唯一例外是 jobs 未说明）。
- **后果**：① R2 建评论 Job 时忘传 `job_type=extract_issues` → 数据静默写成 `triage_case`，legacy 与新域数据混在一起（正是"并存数据污染"风险）；② status 拼写错误会绕过 `uq_jobs_active_comment`，同一评论出现两个活跃 Job，P0-2 的唯一性保障失效且统计虚高。
- **改法**：迁移补 `ck_jobs_status(status IN ('pending','claimed','completed','failed'))` 与 `ck_jobs_job_type(job_type IN ('extract_issues','triage_case'))`，模型同步。`job_type` 默认值：`api/app/main.py:56` 已显式传值，但 **`scripts/seed_demo_data.py:41-46` 依赖默认值**——过渡期可先保留默认 + 加 CHECK，等 0003 删 legacy 时再要求必填；或同 PR 改 seed（小改动）。若 0002 已 apply，用 0002.1 或并入 0003 前补。

## 三、P1（开工前应定稿，否则联调改契约）

- **P1-1 统计口径无契约/无接口**：文档 §4.1#12、§11 要求"所有查询接口返回 `as_of` 与 `scope(product_id,date_from,date_to)`"（`architecture.md:97`、`:478`），但 `schemas.py` 全文无 `as_of`/`scope` 字段，§8.1 接口表也没有统计接口。→ 加 `StatsSummaryRead`（§11 六项 + as_of + scope）与 `GET /stats/summary`，或明确塞进 `GET /review-batches/{id}` 的 meta。
- **P1-2 批次终态由谁写未定义**：§4.2 说"不在批次表另存计数"（`:103-105`），但 `BatchStatus` 又含 `completed/partially_failed`（`models.py:106-112`、`architecture.md:106`）。最后一个 Job 完成时是 Worker 改 batch、还是 API 读时派生？不写清必然出现"批次 status=imported 但页面显示已完成"的双真相或写竞争。→ 建议 `batch.status` 只表达导入阶段，`completed/partially_failed` 读时派生；或指定 Worker 单写者并写清收口条件。
- **P1-3 旧 `GET /jobs/{id}` 对评论 Job 会 500**：`JobRead.case_id` 必填（`schemas.py:322-335`），实测 `JobRead.model_validate(comment_job)` 抛 ValidationError；过渡期 R1/R2 一旦写入评论 Job，任何旧调用方（含 smoke 测试/页面轮询）打到该 id 就会 500。文档 §12.2 只说明"JobRead 仍只接受 case_id 非空的 job"（`:496-497`），未说明接口行为。→ 过渡期按 `job_type` 分流返回 `JobRead` / `AnalysisJobRead`，或在评论 Job 上返回 404/409 并在文档写明。
- **P1-4 "受控类别表"不存在**：§9.2 规则 3 写 `category_id` 来自受控类别表（质量/物流/描述不符/使用体验/其他，版本记 `category_version`）（`:415-416`），报告 P0-9③ 也要求 `Category(id,name,taxonomy_version)`；但 `models.py`/迁移都没有 `categories` 表，只有 `String(40)` 字段。→ R3 只能靠常量，类别扩展时历史数据无法回溯。加 `categories(id,name,taxonomy_version,active)`，或文档降级为"受控常量表 + 版本号常量"并写明校验入口。
- **P1-5 "重跑 supersede"没有落库字段**：§7.4 要求重跑只 supersede `origin=ai AND status=suggested`（`:331`），报告 P0-7④ 还要求 `CommentIssue.comment_version`；但 `LinkStatus` 只有 suggested/accepted/rejected（`models.py:81-85`），`comment_issues` 无 `superseded_at`、无 `comment_version`。→ 实现只能 DELETE suggested 行：审计丢失、旧 run 建议不可追溯、报告 P0-7 只靠代码约定。加 `comment_version int`、`superseded_at timestamptz`（或 LinkStatus 加 `superseded`），重跑 UPDATE 而非 DELETE。
- **P1-6 `content_hash` 降级去重与 NOT NULL 契约冲突**：§4.3 说无稳定编号时降级 `dedupe_mode=content_hash`（`:113-114`），但 `NormalizedComment.source_review_id` 必填（`schemas.py:57`）、`comments.source_review_id` NOT NULL（`models.py:259`）、唯一键含该列。→ 无编号行要么 422、要么伪造 source_review_id 污染唯一键。改：`source_review_id` 可空 + 部分唯一索引 `WHERE source_review_id IS NOT NULL`，内容哈希模式另建 `UNIQUE(platform,shop_id,product_id,content_hash,review_date)` 或明确只做人工判重。
- **P1-7 合并时 `(comment_id, issue_id)` 唯一冲突无规则**：§7.3 "合并：目标组吸收来源组的 comment_issues"（`:313`），但 `uq_comment_issues_pair`（`models.py:406`）在两组都含同一评论时必然冲突。→ 文档写死规则（accepted 优先保留、其余删除并写 `IssueAction(merge_into)`），实现用 `ON CONFLICT`。
- **P1-8 评论详情缺"版本 + AI 输出"契约**：§8.1#5 要返回"原文、版本、AI 输出、关联问题、证据"（`:350`），`CommentDetailRead` 只加了 issues（`schemas.py:125-126`），且没有 `CommentRevisionRead` / `AnalysisRunRead`，`analysis_runs.output_json/model_version/prompt_version` 无任何读契约。→ 补两个 Read 模型挂到 `CommentDetailRead`，否则 R4 无法展示版本与 AI 原始输出、评测也无法回溯。
- **P1-9 `split`/`change` 动作必填字段缺失**：`IssueActionRequest` 只强制 rename/merge_into/accept/reject/change 的 `comment_issue_id`，`split` 无任何必填（`schemas.py:183-197`），`LinkDecision` 的 change 也无目标组。→ split 必填 `payload.split_into[]`（新组名/类别/关联分配），change 必填 `target_issue_id` 或明确是 accepted↔rejected 改判；否则后续合并/拆分页面要现场改契约。
- **P1-10 CI 没有 downgrade 往返，文档却写"CI 同款"**：§12.3 写"升级/回滚/再升级（PostgreSQL，CI 同款）"（`architecture.md:504-511`），但 `.github/workflows/ci.yml:52-54` 只有 `alembic upgrade head`；报告 P1-12/§7 checklist 要求往返。→ CI 加 `alembic downgrade 20260713_0001 && alembic upgrade head`，或先把文档改成"本地命令，CI 暂只跑 upgrade"。

## 四、P2（随文档一并改即可）

- **P2-1 "failed 终态，仅人工重放"自相矛盾**：`architecture.md:269` 写超限 `failed` 终态"仅人工重放"，但 §8.1#11/§10.2 规定 retry 仅 `attempts < max_attempts`（`:356`、`:453`）——用尽后无入口。且 §7.1 租约回收 `attempts+1`（`:278`）与"attempts 只在认领时 +1"（`:274`）字面冲突（报告 P0-3 同样要求回收 +1）。→ 二选一：删"仅人工重放"，或允许人工重放时重置 attempts/提高 max_attempts 并写审计；补一句"attempts 计认领次数（含租约回收）"。
- **P2-2 批次/评论状态机与主流程不自洽**：主流程建 Job 时写 `comments(analysis_status=received)`（`:80-81`），§7.2 却定义 `received → queued`（建 Job 时）→ `analyzing`（`:286-292`），无人写 queued；`BatchStatus.received` 也无人写（默认值，`:106`）。→ 写死"建 Job 即 queued"，或删掉 queued 状态。
- **P2-3 枚举风格不一致**：`analysis_runs.status` 用字符串常量 `("succeeded","failed")`（`models.py:322-324`）没有枚举类；`jobs.error_code` 有 `ErrorCode` 枚举（`:127-134`）但无 DB CHECK（§4.2 只要求存储，可接受，但别声称"枚举 CHECK 全覆盖"）。
- **P2-4 `reopen_count`/`version` 递增规则未写**：字段存在（`models.py:385-386`），但文档未定义"每次 IssueAction version+1、reopen 时 reopen_count+1"，`expected_version` 也是可选（`schemas.py:172-174`）。→ 补规则；契约冻结时决定是否强制必填。
- **P2-5 模型 Python default 与迁移 server_default 不一致**：如 `accepted_rows` 模型无 server_default（`models.py:182`）而迁移有 `server_default="0"`（`migration:61`）——`jobs.max_attempts` 两者都有（`models.py:523-525`）。`Base.metadata.create_all`（SQLite 测试）与迁移后的 PG 行为不同，裸 SQL 插入会踩坑。→ 统一给 NOT NULL 列加 server_default，或统一都不加。
- **P2-6 长度契约不一致**：正文 ≤2000（文档 `:77`、`schemas.py:60`）但 `ExtractionRequest.body` 允许 4000（`schemas.py:238`）；`ExtractedIssue.evidence_text` 500 字符文档未提。→ 统一为 2000，或在文档说明 AI 侧放宽理由。
- **P2-7 几个文档措辞无字段支撑**：`duplicate_suspect`（文档 `:114`）在模型里没有该字段/枚举值（只有 `duplicate_of_id`、`dedupe_mode∈{source_id,content_hash}`，`models.py:142-145`、`:270-272`）；§4.1#8/§9.3 说建组靠"唯一约束 + advisory lock"（`:89`、`:426`），但 `issues` 没有任何唯一约束（`models.py:357-366`）；§11 缺报告 P0-8 要求的"关组后新增数"。→ 改文档用 `duplicate_of_id IS NOT NULL`、明确建组只靠 advisory lock、补关组后新增数公式。
- **P2-8 读契约缺字段**：`IssueRead` 无 `merged_into_id/split_from_id/version`（`schemas.py:132-148`），合并后页面无法显示归属；`IssueActionRead` 无 `issue_id/comment_issue_id`（`:150-158`），审计流水无法关联对象。→ 补字段。
- **P2-9 ORM 关系与 FK ondelete 不一致**：DB 是 `ON DELETE CASCADE`（`models.py:506-508`、`420-425`），但 `Comment.jobs`/`Comment.issue_links`/`Issue.issue_links` 未配 `passive_deletes`/cascade（`models.py:290-291`、`:395-398`），ORM 删除时会尝试把 FK 置 NULL，触发 NOT NULL 或 `ck_jobs_target`。→ 加 `passive_deletes=True`（或按语义 cascade）。
- **P2-10 交付物未提交 + 仓库垃圾**：`git status` 显示 `0002` 迁移、`assets/`、`review/` 均 untracked（`architecture.md`/`models.py`/`schemas.py` 为 M）；工作区还有 `pytest-cache-files-*/`、`review/.pytest-tmp*/`、`docs/~$...docx`、`.dsh_probe.txt`。→ 交接前 `git add` 交付物、补 `.gitignore`，否则队友 clone/切分支拿不到本次交付。
- **P2-11 迁移注释与文档矛盾**：迁移注释说"tests may run migrations on SQLite"（`migration:46-48`），文档说"SQLite 只用于 create_all，不跑迁移"（`architecture.md:517`）；且 0002 含 `alter_column`，在 SQLite 上真跑会失败。→ 改注释，与文档一致。
- **P2-12 旧文档未同步**：`docs/operations.md` 仍是"submit a case / case marked failed"的旧域文案（`operations.md:9-10`、`:26-28`），README 标题仍是 Starter API。属 R1 后续文档计划（报告 P1-15），本次可不改，但需标注"operations/README 待重写"。

## 五、文档与代码不一致逐条清单

| # | 文档位置 | 代码/事实 | 处理 |
| --- | --- | --- | --- |
| 1 | §8.1#2 `:347`、§4.2 `:103-105`（batch 有 analyzed/failed） | `BatchRead` 无这些字段（`schemas.py:71-81`） | P0-1 |
| 2 | §4.1#5 `:350`（评论详情含版本与 AI 输出） | `CommentDetailRead` 只加 issues（`schemas.py:125-126`），无 Revision/AnalysisRun 契约 | P1-8 |
| 3 | §8.1#7 `:352`（IssueDetail 含关联评论）、§4.1#12 `:96-97` | `IssueDetailRead.links` 与 ORM `issue_links` 不同名，实测返回空（`schemas.py:164`） | P0-2 |
| 4 | §4.1 `:97`、§11 `:478`（所有接口返回 as_of/scope） | schemas 无 as_of/scope 字段 | P1-1 |
| 5 | §9.2 `:415-416`（受控类别表） | 无 `categories` 表/模型 | P1-4 |
| 6 | §7.4 `:331`（重跑 supersede） | 无 superseded 状态/`superseded_at`/`comment_version`（`models.py:81-85`） | P1-5 |
| 7 | §6.3 `:252`（状态枚举 String+CHECK） | `jobs.status`/`job_type` 无 CHECK（`models.py:512-521`） | P0-3 |
| 8 | §4.1 `:76`、`:147`（202 返回 job_count） | 校验异步（`:77-81`），202 时不可知 | P0-1 |
| 9 | §7.1 `:269`（failed 终态"仅人工重放"） | §8.1#11/§10.2 仅 attempts<max 可 retry（`:356`、`:453`） | P2-1 |
| 10 | §7.1 `:278`（租约回收 attempts+1） | 与 `:274`/报告"attempts 只在认领时 +1"字面冲突 | P2-1 |
| 11 | §4.1#8 `:89`、§9.3 `:426`（唯一约束兜底建组） | `issues` 无唯一约束（`models.py:357-366`） | P2-7 |
| 12 | §4.3 `:113-114`（content_hash 降级） | `source_review_id` 必填/NOT NULL（`schemas.py:57`、`models.py:259`） | P1-6 |
| 13 | §4.3 `:114`（标 duplicate_suspect） | 无该字段/枚举值（`models.py:142-145`） | P2-7 |
| 14 | §12.2 `:496-497`（旧接口继续可用） | `JobRead` 对评论 Job 抛 ValidationError（`schemas.py:322-335`）→ 500 | P1-3 |
| 15 | §12.3 `:504-511`（升级/回滚/再升级，CI 同款） | CI 只有 `alembic upgrade head`（`ci.yml:52-54`） | P1-10 |
| 16 | §12.3 `:517`（SQLite 不跑迁移） | 0002 注释说"tests may run migrations on SQLite"（`migration:46-48`） | P2-11 |
| 17 | §6.2 `:241` jobs 行把 `case_id（legacy 可空）` 写进字段清单 | 导致字段清单与模型列名不能直接机读比对 | P2（格式） |
| 18 | §4.1 `:77`（正文 ≤2000） | `ExtractionRequest.body` 4000（`schemas.py:238`） | P2-6 |

**结论**：数据层与文档主干可信、可作为实现基线；先关 P0-1/P0-2/P0-3，再冻结契约（P1-1/P1-3/P1-4/P1-5/P1-6/P1-7/P1-9），即可按报告 §5 四线并行开工。
