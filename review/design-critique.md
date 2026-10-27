# Proposal 设计评审：状态机、实体与流程的独立挑错

**评审对象**：`docs/商品评论管理与重复问题发现系统_单平台初版Proposal.docx`（71 段 + 5 表，§1–§8）与两张配图（`docs/63b9dc336972503ecf1ac2a068e8634b.png` 端到端流程、`docs/2cb810f6cb909fc1743d720c27856de6.png` 三条状态机）；现状约束参考 `docs/architecture.md`（现有 Pitch 分析骨架）。只评设计，不评代码实现。

**结论先行**：范围判断与产品边界站得住，但系统设计不闭合。三处会直接返工：① 状态机只有“状态集合”没有“迁移表 / 上限 / 触发者”，两张图互相矛盾；② 评论没有分析状态，`has_issue`、证据、正文版本、审计信息无字段可落；③ Job 粒度（一条评论一个 Job 还是一批一个 Job）未定义，导致“部分成功”和统计口径无法实现。建议进实现前先补：1 页状态迁移表 + 1 页实体约束表 + 1 页接口表。

## 一、总体判断（哪些没问题，不凑数）

- **骨架复用方向正确**：提交即返回、后台 Worker、事务性落库、失败可见、可插拔 AI，§1 的复用清单与现有 `architecture.md` 的核心链路一致，改造量可控。
- **产品边界克制且合规**：单平台、单入口、只处理文本、同商品内归组、不自动操作平台、不把评论数说成缺陷率（§5）——这些是课程项目里最容易膨胀的地方，Proposal 守住了。
- **状态集合本身选得对**：Job 4 态、Issue 4 态、评论关联 3 态（表 0）没有多余状态，问题只在于没有迁移定义和所有者。
- **图 2 的“实线 = 端到端图已覆盖，虚线 = §4.2 保留”是加分写法**：主动声明两图关系，比强行画全更诚实。可惜虚线边恰好全是未定义的边（见 P0-2/P0-4）。
- **风险表覆盖了最容易翻车的几类**：入口权限、字段不完整、误合并、证据幻觉、PII 与 prompt 注入，覆盖面对课程交付足够。
- **需要说清的是**：下文 P0 不是“写得不够细”，而是按现文写下去必然出现两种互斥实现（例如重试回到哪个状态、确认后是否关闭），这类不确定会在联调时才暴露。

## 二、P0：进实现前必须解决

### P0-1 命名冲突：“Review”同时是评论、复核动作、复核记录

- **为什么错**：§4.3 定义 “Review（评论原文与来源）”；同节又定义 “ReviewRecord（人工修改及跟进记录）”；接口是 `POST /issues/{id}/review`（“保存复核”）；图 1 写 “更新Review（suggested）”；§7.2 AI 输出字段叫 `review_id`。同一个词承担“评论 / 人工复核动作 / 复核记录”三种含义，而表 0 又把 `suggested/accepted/rejected` 归属于“评论关联”（即 ReviewIssue）。
- **后果**：`suggested` 到底写在 Review 还是 ReviewIssue 无法判定（Review 在表 0 里没有任何状态）；AI 契约的 `review_id` 与 `/issues/{id}/review` 在同一份文档里指两个东西，实现期必然各写一套；复核记录与评论实体在日志/权限/统计上不可区分。
- **建议改法**：评论实体改名 `Comment`（字段 `id, platform, shop_id, product_id, source_review_id, review_date, rating, body, content_hash, analysis_status, has_issue`）；关联表 `CommentIssue`；人工动作统一落不可变表 `IssueAction`（见 P1-5）；接口改 `POST /issues/{id}/actions`（body 带 `action`）；AI 契约字段改 `comment_id`；`/review-batches` 若保留，文档里注明它指“评论批次”并避免与复核同段出现。

### P0-2 状态机矛盾①：Job 重试的目标状态，两图不一致，且与现有骨架相反

- **为什么错**：图 1 的虚线是 `Job failed` → **`Worker 认领Job (Job claimed)`**，标注“重试 attempts+1”；图 2 的虚线是 `failed` → **`pending（待领取）`**。而 `architecture.md` 现状写的是 “pending → claimed → completed/failed”“Claiming … increments attempts”“The initial version does not automatically retry failed Jobs … If controlled retry … is added later, it will create a new Job while preserving previous Jobs and results.”
- **后果**：回到 `claimed` 等于让“已领取”承担排队语义，`claimed_at` 无法表达“谁正在处理”，Worker 的 `SELECT … FOR UPDATE SKIP LOCKED` 会与重试互相踩；`attempts+1` 若同时出现在“重试边”和“认领时”（现状），一次重试会加两次；两图不一致意味着前端状态文案和统计（排队/处理中/失败）会各写一版。另外两图的虚线语义相反：图 2 注释把虚线定义为“§4.2 保留、本版主流程未画入”，而图 1 恰恰用虚线画了重试，读者无法判断虚线到底表示“已实现”还是“未实现”。
- **建议改法**：重试**只回 `pending`**；`attempts` 只在认领时 +1；新增 `max_attempts`（默认 3，可配置）与 `next_attempt_at`；`failed` 只能由 `claimed` 进入，且必须写 `error_code, error_message, completed_at`；重试触发方只允许两种——`POST /jobs/{id}/retry`（人工）或 Worker 扫描 `failed AND attempts < max_attempts`（自动），二者都要幂等（同 Job 并发重试只有一个成功，其余 409）。图 1 的虚线改指 `pending`，并删除“attempts+1”标注。

### P0-3 状态机矛盾②：`confirmed` 之后被画成“结束、维持关闭”，`resolved` 在端到端图里不存在

- **为什么错**：图 1 的 `确认 Issue: proposed → confirmed` 分支直接向下箭头指向绿色终点框“**结束：维持关闭 / 新评论只作提示，不进计数**”。但 `confirmed` 在表 0/图 2 是“人工已确认”，不是关闭；关闭态是 `resolved（已记录处理完成）`，而图 1 从未出现 `resolved`，也没有 §4.1 第 6 步的“人工记录措施并更新问题组状态”“后续收到同类评论时保留新增记录，提示人工查看”。
- **后果**：开发按图 1 实现会把 `confirmed` 当终态，`resolved` 与跟进记录永远走不到；按正文实现则图 1 的终点框和 `POST /review-batches`→Job→复核的主流程少一段，验收时“人工跟进记录”无法演示。
- **建议改法**：端到端图补齐 `confirmed → resolved`（记录跟进，写 `IssueAction(action=resolve)`）；删除“确认→结束”的边；把绿色终点框移到 `dismissed` 与 `resolved` 之后，文案改为“进入人工跟进/已关闭，后续同类评论生成 suggested 关联并提示”。`confirmed` 的出口只能是 `resolve`、`dismiss`（误确认）、`merge/split`，不能是“结束”。

### P0-4 状态机矛盾③：`dismissed` 标注“终态”，正文却说可以“重新打开已关闭的问题组”；图 2 自称“与 01 对齐”但并未对齐

- **为什么错**：图 2 把 `dismissed` 标为“人工驳回（**终态**）”，唯一虚线重开是 `resolved → confirmed`；但 §4.1 第 6 步写“**由人工决定是否重新打开已关闭的问题组**”，未限定只对 `resolved`。§4.3 又说“对已确认问题组……排序或提示”，没有说明驳回后同类评论如何处理。图 2 标题下方注释“与 01 端到端图对齐，并保留 §4.2 的定义”，实际上重试边、确认后的终点、`resolved` 的缺失都与图 1 不一致。
- **后果**：“已关闭”到底指 `resolved` 还是 `resolved + dismissed` 无法回答；若驳回后不能重开，误驳回一次就永久丢失该问题组，只能新建组，计数与历史被拆成两份；若能重开，图 2 缺边、表 0 缺语义，前端不知道按钮该不该出现。
- **建议改法**：在文档中二选一并写死：方案 A（推荐）——`dismissed` 允许 `dismissed → confirmed`（重开，记 `reopen_count`、`IssueAction(action=reopen, reason)`，图 2 补虚线）；方案 B——`dismissed` 终态，同类新评论只能新建 `proposed` 组并在 UI 中提示“曾驳回”，同时把 §4.1 的“已关闭”改为“已处理（resolved）”。另外补规则：`resolved` 重开后该组历史计数保留，页面同时给“重开前 / 重开后”两个口径。

### P0-5 Review 没有分析状态，`has_issue` 三态与证据无处落库

- **为什么错**：§5 要求“页面分别显示**接收量、成功分析量和失败量**”，图 1 的 AI 输出是“has_issue 三态 · 类别 · 原文证据”，图 1 终点还写“新评论只作提示，不进计数”；但表 0 只定义 Job / Issue / 评论关联三种状态，Review（评论）本身没有任何状态字段，也没有 `has_issue`、`analysis_status`、证据定位结果字段。
- **后果**：“成功分析量”只能从 Job 推，而 Job 与评论是一对多还是一对一还没定（P0-6），一推就错；“有具体问题 / 无具体问题 / 无法判断”三种结果没有持久化位置，页面无法筛选“无法判断”、无法计算失败率；证据片段只存在于 AI 返回体里，刷新即丢，验收项“可定位的 AI 问题证据”没有落点。
- **建议改法**：`Comment` 增加 `analysis_status ∈ {received, queued, analyzing, analyzed, failed}`、`has_issue ∈ {yes, no, unknown}`、`analysis_run_id`、`analysis_error`；证据落到 `CommentIssue.evidence_text / evidence_start / evidence_end / evidence_verified`；`has_issue=unknown` 计为“成功分析但结果未知”，单列，不算失败；`analysis_status=failed` 才计入失败量。

### P0-6 Job 粒度与“部分成功”未定义：一条评论一个 Job，还是一批一个 Job？

- **为什么错**：图 1 是单数“事务落库 + 创建 Job, Review / Job Pending”，§4.1 第 3 步“API 将**评论与对应 Job** 事务性落库，返回接收结果和**任务编号**；批量接收可采用 202”；而 §4.1 第 2 步又要求“文件方案提供批量上传、校验和预览”，图 1 有“行数上限”“错误清单 行号+原因”。如果一批只建一个 Job，那么“输出有效?”为否时整批 `failed`，同批已成功分析的评论算什么；如果每条评论一个 Job，202 返回的单个“任务编号”指哪一个，`GET /jobs/{id}` 如何看到批次进度？
- **后果**：整批失败会让已分析结果回滚或丢失，重试成本按批放大；逐条 Job 又缺批次聚合，接收量/成功量/失败量三个数对不上；`IngestionBatch`（“接收批次与结果”）没有状态字段，无法表达“部分成功”。
- **建议改法**：明确 **1 条评论 : 1 个 Job**（AI 调用、重试、幂等的最小单元），`Job` 增加 `comment_id`、`batch_id`，唯一约束“同一 comment 同时最多一个非终态 Job”；`IngestionBatch` 增加 `status ∈ {received, validating, rejected, imported, completed, partially_failed}` 与 `accepted_rows / duplicate_rows / invalid_rows`（导入阶段字段）；202 返回 `{batch_id, status, job_count}`，**不返回单个 job_id**；`GET /batches/{id}` 返回批次进度与失败清单，`GET /jobs/{id}` 只查单条；`analyzed_rows / failed_rows` 由 Job 聚合实时派生，**不在批次表另存计数**（避免双真相）。批内单条失败不改动同批其他 Job，批次按计数展示“部分成功”。

### P0-7 重跑会覆盖人工结论：正文变更 / prompt / 模型升级都没有版本与“只写 suggested”规则

- **为什么错**：§4.3 只说“若同一来源评论的正文发生变化，保留可追溯的更新记录并重新分析，更新受影响的关联和统计”；§7.2 说“Worker 将提取结果与同一商品的问题组关联，并更新基于去重记录的统计”；风险表写“正文变更后重新分析并更新统计”。全文没有 `analysis_run`、`model_version`、`prompt_version`，也没有“重跑不得修改 accepted/rejected”的规则；而图 2 明确 `accepted/rejected` 是人工结论、`suggested` 是 AI 建议。
- **后果**：换模型或改 prompt 后重跑，人工接受/拒绝的关联可能被覆盖成 suggested、被删除或改挂到别的组；`resolved/dismissed` 组被重新打开或计数回退；“去重记录”更不可复现——同一个数字在两次重跑后不同，无法解释。
- **建议改法**：引入 `AnalysisRun(id, comment_id, job_id, model_version, prompt_version, category_version, created_at)`；AI 只允许写 `origin=ai, status=suggested` 的行；重跑规则显式写入文档：① 旧 run 的 suggested 行置 `superseded_at`（或删除，仅限 `origin=ai AND status=suggested`）；② `accepted/rejected` 行永不修改；③ 人工改判只写新 `IssueAction`，并在 `CommentIssue` 上保留 `decided_by/decided_at`；④ 正文变更追加 `CommentRevision`，`CommentIssue.comment_version` 记录结论对应的版本。

### P0-8 统计口径不可计算，且图 1 与 §5 直接冲突；“AI 建议数 vs 人工确认数”没有定义

- **为什么错**：§5 写“问题数量表示已取得数据中提及该问题的**去重评论条数**；同一评论对同一问题只计一次”，而图 1 终点写“**新评论只作提示，不进计数**”，图 2 注释写“suggested 不计入人工确认数，页面分开显示「AI 建议数」与「人工确认数」”——文档从未定义这两个数分别怎么算。去重键（§4.3“平台 + 店铺 + 来源评论编号”）也不含商品维度，与 §5“分母为同一商品……的成功分析有效评论数”不同口径。
- **后果**：同一个 Issue 的“评论数”在关组前后含义不同，无法复现；`suggested` 是否计入问题数、`rejected` 是否扣减、`dismissed` 组是否显示、`unknown` 是否算“有效评论”，四个问题各写一版就是四种统计；验收时无法判断统计是否正确。
- **建议改法**：写死六个口径（文档原样收录）：① 接收量 = `SUM(IngestionBatch.accepted_rows)`，重复行单列 `duplicate_rows`；② 成功分析量 = `COUNT(Comment WHERE analysis_status='analyzed')`（`has_issue` 三态都算成功，unknown 单独展示）；③ 失败量 = `COUNT(Comment WHERE analysis_status='failed')`；④ 问题提及数 = `COUNT(DISTINCT comment_id) FROM CommentIssue WHERE issue_id=? AND status='accepted'`；⑤ AI 建议数 = `CommentIssue WHERE origin='ai'` 的总数，其中 `suggested` 单列；⑥ 人工确认数 = `status='accepted'`。关组后新评论仍建 suggested 关联，问题数按 accepted 实时算，另设“关组后新增数”，**删除“不进计数”**；所有查询接口返回 `as_of` 与 `scope(product_id, date_from, date_to)`。

## 三、P1：进实现前应解决（否则联调返工或口径难自证）

### P1-1 去重键缺商品维度；无稳定编号时没有可执行规则

- **为什么错**：§4.3 定“平台 + 店铺 + 来源评论编号”，但 §5 的统计分母、§7.1 的“保留来源标识、商品编号”与 §4.3 的归组范围都以“商品”为单位；风险表同一句又写“平台、店铺及稳定来源标识”。若平台的评论编号只在商品内唯一（导出文件常见），缺 `product_id` 会把不同商品的评论当同一条删掉。
- **后果**：跨商品误合并 → 问题组里出现别的商品的评论，归组和计数全错；没有稳定编号时“验证替代标识”无法实施，只能靠正文相同，而 §4.3 已禁止正文相同即删除。
- **建议改法**：唯一键 `UNIQUE(platform, shop_id, product_id, source_review_id)`，并在文档注明“来源编号作用域（平台/店铺/商品）需在入口验证阶段确认”；无稳定编号时降级为 `dedupe_mode ∈ {source_id, content_hash+review_date+rating}`，命中只标记 `duplicate_suspect` 不物理删除，交人工判重；`Comment` 增加 `dedupe_mode` 与 `duplicate_of_id`。

### P1-2 归组写在分析事务里：并发 Worker 会重复建组，重试会重复关联

- **为什么错**：图 1 把“同商品归组、更新 Review、关联已有 Issue 或新建候选 Issue（proposed）”放在“输出有效”之后、同一条流水线上；§4.3 只有一句“分析重试采用更新或唯一约束，避免重复归组和重复计数”，没说是哪个唯一约束；也没有说明两个 Worker 同时分析同一商品的两条评论时，谁先建组。
- **后果**：同一商品同一问题出现两个 `proposed` 组（AI 建议数虚高、人工要手工合并）；重试后 `CommentIssue` 重复插入（评论数虚高）；人工刚合并的组被重跑再拆开。
- **建议改法**：把归组拆成**可重跑的后处理步骤**（`AnalysisRun` 完成后触发，或 Worker 内二级任务）：先按 `(product_id, category)` 召回已有 `proposed/confirmed` 组，命中则 upsert `CommentIssue(comment_id, issue_id)`（唯一约束兜底），未命中才建新组；建组用 `INSERT … ON CONFLICT (product_id, category_id, normalized_title) WHERE status='proposed'` 或对 product 维度加 advisory lock；明确“只关联 proposed/confirmed，不自动关联 resolved/dismissed”。

### P1-3 `POST /review-batches` 的同步/异步未定；错误清单“不落库”与“失败可见”冲突

- **为什么错**：§4.1 第 2 步要“批量上传、校验和预览”，第 3 步又要“事务性落库……批量接收可采用 202”；图 1 是“校验通过？”→ 否 →“错误清单 行号+原因，**不落库**”。202 意味着响应里没有校验结果，预览与错误清单必须异步拿；而“不落库”又不产生批次记录，没有可查询的接收结果。
- **后果**：前端无法实现“预览后再确认”的两步交互；失败批次无记录，用户重传无法识别、无法审计“哪些行被拒”；验收项“可见的任务失败”不覆盖校验失败；“不落库”还让“行号”失去意义（用户改完文件后行号已变）。
- **建议改法**：两段式：`POST /batches`（multipart + `Idempotency-Key`）→ 201 `{batch_id, status:'validating'}`，落 `IngestionBatch`（含 `source_type, file_ref, file_hash, declared_rows, idempotency_key`）；异步校验后 `GET /batches/{id}` 返回 `invalid_rows, errors[{row_no, field, reason}]`（明细可只保留前 N 条汇总，但计数必须存）；校验通过由服务端自动 `imported` 并建 Job，或 `POST /batches/{id}/commit` 显式确认。若坚持单请求同步校验，则改为 `422 + errors[]`、不建 Job，并在文档里删掉“预览”。

### P1-4 `claimed` 卡死：已知但不恢复，却要求“失败可见/有限重试”，且无人工恢复入口

- **为什么错**：图 2 注释承认“Job 若因 Worker 中断停在 `claimed`，首版不自动恢复，需人工核查（见 architecture.md）”；但 §7.3 说“现有失败记录之外，按需要实现**有限重试及恢复**”，风险表说“配置超时、**有限重试**和错误状态”。`claimed` 无租约、无 `lease_expired_at`、无恢复接口，而 Job 停在 claimed 时既不算成功也不算失败。
- **后果**：“接收量 = 成功 + 失败 + 处理中”的等式永远不闭合，页面显示“处理中”永不结束；`max_attempts` 形同虚设（因为根本没走到 failed）；也没有任何接口能把卡死 Job 拉回队列，只能改库。
- **建议改法**：首版允许不自动恢复，但必须补齐：① `claimed_at` + `lease_timeout`（如 15 分钟）作为“卡住”的判定依据并在 UI 单列“超时处理中”；② `POST /jobs/{id}/recover`（人工，写 `error_code=LEASE_EXPIRED`，attempts+1，回 `pending`，不计失败）；③ 统计把“处理中超时”单独展示，不混入失败量；或直接接受恢复则 `claimed → pending` 并记 `lease_expired_count`。

### P1-5 ReviewRecord 与 ReviewIssue 职责重复；合并/拆分/改判没有字段和日志表

- **为什么错**：§4.3“ReviewIssue（评论与问题关联）”与“ReviewRecord（人工修改及跟进记录）”都声称承载人工调整；表 0 又说评论关联“保留人工调整记录”。同时 §4.1 第 5 步要求“改名、合并、拆分或驳回”，但文档没有 `merged_into_id`、`split_from_id`、`reopen_count`，也没有记录“改前/改后”的字段。
- **后果**：同一次“接受关联”可能写两张表，也可能都不写；两个开发者各选一个实现，数据不一致；合并后原组的评论去向、统计迁移无法追溯，验收“人工归类和跟进记录”只能演示 UI。
- **建议改法**：职责二分为——`CommentIssue` 只存**当前状态**（`status, origin, evidence, decided_by, decided_at`）；`IssueAction`（不可变，替代 ReviewRecord）存**每次动作**（`issue_id, action ∈ {confirm, dismiss, reopen, rename, merge_into, split, followup, resolve}, from_status, to_status, payload JSONB, operator, note, created_at`）；`Issue` 增加 `merged_into_id, reopen_count, resolved_at, created_by(ai/manual)`；跟进措施明确是 `IssueAction(action=followup, payload={measure, owner, due_at})` 还是独立 `FollowUp` 表，二选一写死。另补两条状态机**联动规则**，否则两套状态会各自漂移：① `Issue` 处于 `resolved/dismissed` 时新到的 AI 建议只落 `suggested` 并在 UI 提示，不自动改 `Issue.status`；② 一组内 `accepted` 通过改判归零时 `Issue` 不自动转 `dismissed`，只提示人工“是否驳回”。

### P1-6 AI 契约不完整：三态的取值、证据定位规则、类目体系、归组建议字段都缺

- **为什么错**：§7.2 只给“输出示例：review_id、has_issue、issues[{category, description, evidence}]”，没说 `has_issue` 的枚举值（yes/no/unknown？）、`issues` 为空时是否等价的 no、`category` 是否受控词表（§4.3 说“可先使用质量、物流、描述不符、使用体验等大类”，未固定）、`evidence` 是原文子串还是改写、定位失败怎么办；§4.3 又说“相似度阈值由人工标注样本调整”，但没给默认值、没给 `related_issue_id`/`similarity` 输出字段，归组建议只存在于 Worker 内部逻辑。
- **后果**：AI 服务与 Worker 的契约无法写测试用例；evidence 定位失败时“保留未知或转人工”（风险表）没有落点，最可能实现成“静默丢弃”或“整条 Job 失败”；`category` 不受控则 `GET /issues?category=` 与按类目统计不稳定；阈值不可追溯，重跑后归组结果不可解释。
- **建议改法**：写死契约：`{comment_id, has_issue: "yes"|"no"|"unknown", issues: [{category_id, description, evidence_text}], model_version, prompt_version}`，并加四条校验规则——① `has_issue='no' ⇒ issues=[]`，`has_issue='yes' ⇒ issues 非空`；② `evidence_text` 必须是对规范化正文（统一全半角/空白/emoji 保留）的精确子串，Worker 计算 `evidence_start/end` 并写 `evidence_verified`，定位失败则该 issue 不落库、`has_issue` 降级为 `unknown`、Job 记 `warnings` 不直接 failed；③ `category_id` 来自受控表 `Category(id, name, taxonomy_version)`，阈值写配置并记录 `similarity_threshold_version`，命中结果落 `CommentIssue.similarity`；④ **一条评论多个问题**时每个 issue 独立一行 `CommentIssue`、各自定位证据，`UNIQUE(comment_id, issue_id)` 保证同一问题只计一次。

### P1-7 5 个拟定接口不够：缺批次/详情/动作/分页/幂等/错误码

- **为什么错**：§4.1 只给 `POST /review-batches`、`GET /reviews`、`GET /jobs/{id}`、`GET /issues`、`POST /issues/{id}/review`。但页面要“按商品、日期、类别和状态筛选”、要“展示评论数和原文”、要“改名/合并/拆分/驳回/记录跟进/重开”，这些都需要参数和接口；`POST /issues/{id}/review` 一个口承担全部动作，既无 `expected_version` 也无幂等键，两个页面同时打开会互相覆盖。
- **后果**：前端无法分页/筛选（`GET /reviews`、`GET /issues` 无参数定义），无法查看问题组明细和原文（没有 `GET /issues/{id}`），无法做动作（合并/拆分/重开没有接口），并发复核会丢失更新。
- **建议改法**：补 `GET /batches/{id}`、`GET /comments?product_id&date_from&date_to&analysis_status&has_issue&cursor`、`GET /comments/{id}`、`GET /issues?product_id&status&category_id&date_from&date_to&sort=comment_count&cursor`、`GET /issues/{id}`（含关联评论+证据+actions）、`POST /issues/{id}/actions`（`action` + `expected_version`，冲突 409）、`POST /comments/{id}/links/{link_id}/decision`（accept/reject/改判）、`POST /jobs/{id}/retry`、`POST /jobs/{id}/recover`；统一错误码 `400/404/409/413/422/429`，422 返回 `{field, row_no, reason}` 数组，写接口支持 `Idempotency-Key`。

### P1-8 验收标准与风险表漏掉会直接导致返工的点

- **为什么错**：§8 验收重点是“一种已验证入口、可查评论及来源、可定位证据、人工归类跟进、可见任务失败”。但本次设计的三个高危项没有验收句：重传/重试/重跑不重复计数且不覆盖人工结论；Job 粒度与部分成功的展示；状态机所有边的可操作（重开、改判、驳回）。风险表 9 行覆盖了入口、字段、计数、误合并、证据幻觉、缺陷率误读、授权限流、样本偏差、PII，但没有“人工结论被重跑覆盖”“并发复核冲突”“批次部分成功”“LLM 成本/超时/分片”“日期时区”五项。
- **后果**：实现“看起来都做了”，验收时才发现“重跑后 accepted 变成 suggested”“一批失败后计数对不上”“两个标签页互相覆盖”这类只能返工的问题；风险表也无法支撑后续排期。
- **建议改法**：验收补 5 条可测句：① 同一批次重复上传两次，接收量与问题数不变（幂等）；② 正文变更重跑后，已 accepted/rejected 的关联状态不变；③ 批内 1 条 AI 失败，批次显示 `partially_failed` 且失败量与成功量之和 = 接收量；④ 全部状态迁移可经接口触发且非法迁移返回 409；⑤ 证据定位率 ≥95%，未定位的证据不出现在 UI。风险表补上上述 5 项及应对（乐观锁 + 幂等键、批内隔离、成本上限、`review_date` 时区与缺失回退）。

### P1-9 “复用现有骨架”被高估：人工复核、重试、恢复在现状里都不存在

- **为什么错**：§1 复用清单写“可插拔 AI 服务与**人工复核**”，§7.3 写“按需要实现有限重试及恢复”。但 `architecture.md` 明确 “A formal approval system and stored review records are outside the initial scope”“The initial version does not automatically retry failed Jobs”“automatic recovery is outside the initial scope”。
- **后果**：排期按“复用”估，实际人工复核（实体、接口、页面、审计）和重试/恢复都是新增；同时现有 `jobs.pitch_id` 是非空外键、`pitches` 与 `analysis_results` 是另一套语义，Proposal 只说“Job 在现有基础上调整关联”，没写迁移方案，联调时会被旧表/旧接口拖住。
- **建议改法**：把 §1 复用清单拆成“直接复用 / 改造复用 / 新增”三列；明确旧 `pitches/analysis_results` 与旧接口的去留（建议保留骨架、新增 `comments` 域，Job 增加可空 `pitch_id` 与 `comment_id` 二选一约束，或新建 `analysis_jobs` 避免污染旧表）；把人工复核、重试、恢复列入“新增”并给工作量与验收。

## 四、P2：可以后置，但要写进文档

### P2-1 具体限额缺失：图 1 有“编码·行数上限”，全文没有数值

- **为什么错**：图 1 的“校验与规范化”框写“必需字段·编码·行数上限”，但 §4、§5 没有任何一项给出数值或字段清单；`POST /batches` 也没有请求体上限描述。
- **后果**：实现者各自拍脑袋，CSV 10 万行与 100 行的处理方式不同（同步/异步、内存/流式），到联调才发现要改接口形态。
- **建议改法**：写死单批 ≤5,000 行、单文件 ≤10MB、正文 ≤2,000 字符、必填 `product_id`/`review_date`/`body`；超限返回 413/422，超出上限时提示拆分批次。

### P2-2 商品/店铺标识没有规范化

- **为什么错**：§5 只说“保留平台、店铺和商品标识”，实体清单里没有 `Product`/`Shop`，`product_id` 只是字符串；归组范围键与统计范围键都依赖它。
- **后果**：同一商品在不同批次里 `product_id` 写法不同（或只有商品名）时，归组被拆成多个组，统计分母也分裂；多平台扩展时无法建立商品映射。
- **建议改法**：最小化 `Product(platform, product_id, title)` 与 `Shop(platform, shop_id, name)`，`Comment.product_id` 外键；导入时校验商品标识存在，缺失的行进错误清单。

### P2-3 日期语义混用

- **为什么错**：§5 的统计要“同一商品、同一时间范围”，但没区分 `review_date`（平台评论日期）与 `received_at`（接收时间）；§7.1 把“日期”列为必须保留的字段但没规定语义。
- **后果**：延迟导入的历史评论会让“按日期统计”把旧评论算进本期；缺失评论日期时不同实现用不同回退，跨批次不可比。
- **建议改法**：统计与筛选一律用 `review_date`；缺失时用 `received_at` 并在 UI 标注“日期回退”，接口返回 `date_basis`。

### P2-4 老骨架迁移方案缺一句话

- **为什么错**：§4.3 只写“Job 在现有基础上调整关联”，但 `architecture.md` 里 `jobs.pitch_id` 是非空外键，`pitches`/`analysis_results`/旧测试是另一套语义。
- **后果**：迁移时非空外键无法直接对应评论，旧表/旧接口/旧测试的去留不定，前期会卡在 schema 上。
- **建议改法**：明确保留骨架、新增评论域：`Job.pitch_id` 改为可空 + 新增可空 `comment_id` + `CHECK (pitch_id IS NOT NULL OR comment_id IS NOT NULL)`，或直接新建 `analysis_jobs`；旧 Pitch 接口与测试标注“保留但不在首版流程”。

### P2-5 术语表缺失

- **为什么错**：review / comment / issue / link / action / batch 在正文里混用（P0-1 的根因），图和表各自造词。
- **后果**：文档、接口、表名、UI 文案四套术语，读者与实现者需要不断翻译，评审成本上升。
- **建议改法**：§4 前加 6 行术语表：`Comment（评论）/ Issue（问题组）/ CommentIssue（评论关联）/ IssueAction（人工动作）/ IngestionBatch（接收批次）/ Job（单条分析任务）`，全文只允许这些词。

### P2-6 评测口径未定义标注单位

- **为什么错**：§7.3 要求评估“是否包含问题、包含哪些问题、哪些评论应归同组”的 Precision/Recall/F1 与“归组建议准确性”，但没定义标注单位（评论级/问题级）、多标注者一致性、`unknown` 是否进分母。
- **后果**：指标不可复现，模型升级时无法比较；`unknown` 被算进正例或负例会让效果数字随意变化。
- **建议改法**：写明：提取按“评论×问题”对计算 P/R/F1，归组按“评论对是否同组”计算；`unknown` 单列为“不可判定”，不进 P/R 分母；至少 2 人标注并报告一致性。

## 五、修订后的状态机与实体建议（一页小结）

**表 A Job（保留 4 态；`attempts` 只在认领时 +1，重试回 `pending`）**

| 当前 | 事件 / 触发者 | 目标 | 必须同时写入 | 约束 |
| --- | --- | --- | --- | --- |
| — | 批次导入（API 事务，与 Comment 同事务） | pending | `batch_id, comment_id, attempts=0` | 同一 comment 最多一个非终态 Job |
| pending | Worker 认领（`FOR UPDATE SKIP LOCKED`） | claimed | `claimed_at, attempts+=1` | `attempts ≤ max_attempts`（默认 3） |
| claimed | AI 有效且结果落库事务提交 | completed | `completed_at, analysis_run_id` | 结果/关联/状态同事务 |
| claimed | 超时 / 调用失败 / 校验失败 | failed | `completed_at, error_code, error_message` | 不写任何 result |
| failed | `POST /jobs/{id}/retry` 或 Worker 扫描 | pending | `claimed_at=null, next_attempt_at` | 仅 `attempts < max_attempts`；禁止 `failed→claimed` |
| claimed | 租约超时（`claimed_at + lease_timeout`） | pending | `leased_count+=1, attempts+=1` | 首版可不自动恢复，但保留 `POST /jobs/{id}/recover` |
| failed | 人工放弃 | failed（终态） | — | 批次计 `failed_rows` |

**表 B Issue（人工只改状态/属性；改名、合并、拆分不改变 status，写 `IssueAction`）**

| 当前 | 事件 | 目标 | 说明 |
| --- | --- | --- | --- |
| — | AI 归组未命中已有组 | proposed | `created_by=ai`；人工也可手建 `created_by=human` |
| proposed | 人工确认 | confirmed | 记 `decided_by/decided_at` |
| proposed | 人工驳回 | dismissed | 必须选“是否可重开”（见 P0-4） |
| confirmed | 记录跟进 | resolved | 写 `followup` action + `resolved_at` |
| resolved | 人工重开 | confirmed | `reopen_count+=1`，保留历史计数口径 |
| confirmed | 人工驳回（误确认） | dismissed | 建议允许；若不允许须写明 |
| dismissed | 人工重开（方案 A） | confirmed | 补虚线边，记 reopen reason |
| 任意 | 合并到 X | `merged_into_id=X`，原组从活跃列表/计数排除 | `CommentIssue` 改挂 X，保留 action 审计 |
| 任意 | 拆分 | 原组保留，新建 N 组 | `split_from_id` 记录来源 |

**表 C CommentIssue（AI 只能写 suggested；accepted/rejected 只能由人工写）**

| 当前 | 事件 | 目标 | 说明 |
| --- | --- | --- | --- |
| — | AI 归组建议 | suggested | `origin=ai, analysis_run_id, evidence_*` |
| — | 人工手工关联 | accepted | `origin=human`，直接计入问题数 |
| suggested | 人工接受 | accepted | 记 `decided_by/at`；唯一进入问题计数的状态 |
| suggested | 人工拒绝 | rejected | 保留行，不删除 |
| accepted / rejected | 人工改判 | 互转 | 写 `IssueAction`，不改 `origin` |
| suggested | 同评论新 run | superseded（或删，仅限同 run） | 不触碰 accepted/rejected |
| 任意 | Issue 合并 | `issue_id` 改挂 | 唯一约束 `UNIQUE(comment_id, issue_id)` 兜底 |

**表 D 实体职责与关键约束（取代原文“主要新增实体”一段）**

| 实体 | 唯一职责 | 主键 | 关键字段 / 唯一约束 |
| --- | --- | --- | --- |
| Comment（原 Review） | 一条来源评论的当前正文+来源+分析状态 | uuid | `UNIQUE(platform, shop_id, product_id, source_review_id)`；`analysis_status, has_issue, content_hash, dedupe_mode` |
| CommentRevision | 正文版本历史 | uuid | `UNIQUE(comment_id, version)`；`body, content_hash, created_at` |
| IngestionBatch | 一次上传/拉取的接收与校验结果 | uuid | `UNIQUE(idempotency_key)`；`status, file_hash, accepted/duplicate/invalid/analyzed/failed_rows` |
| Issue | 商品内问题组当前状态 | uuid | `product_id, category_id, status, merged_into_id, reopen_count, resolved_at` |
| CommentIssue | 评论↔问题组当前关联与人工决策 | uuid | `UNIQUE(comment_id, issue_id)`；`origin, status, evidence_text/start/end/verified, similarity, analysis_run_id, decided_by/at` |
| IssueAction（替代 ReviewRecord） | 不可变动作/跟进日志 | bigint | `issue_id, action, from_status, to_status, payload, operator, note, created_at` |
| Job | 单条评论的一次分析执行 | bigint | `comment_id, batch_id, status, attempts, max_attempts, error_code, claimed_at, completed_at` |

**表 E 接口修订（原 5 个 → 12 组；原则：查询必分页、写必带 `Idempotency-Key` 或 `expected_version`）**

| 接口 | 作用 | 原方案缺什么 |
| --- | --- | --- |
| `POST /batches`（原 `/review-batches`） | 上传并返回 batch_id/status | 幂等键、只返回单 job_id |
| `GET /batches/{id}` | 接收量/重复量/无效量/错误摘要/进度 | 完全缺失（错误清单不落库） |
| `GET /comments` | 评论列表：商品/日期/分析状态/has_issue + cursor | 无参数定义 |
| `GET /comments/{id}` | 原文、版本、AI 输出、关联问题、证据 | 完全缺失 |
| `GET /issues` | 商品/状态/类目/日期/排序 + cursor | 无参数定义 |
| `GET /issues/{id}` | 明细 + 评论列表 + 计数口径 + actions | 完全缺失 |
| `POST /issues/{id}/actions` | confirm/dismiss/reopen/rename/merge/split/followup/resolve | 原 `POST /issues/{id}/review` 无动作枚举、无乐观锁 |
| `POST /comments/{id}/links/{link_id}/decision` | 接受/拒绝/改判 | 完全缺失 |
| `GET /jobs/{id}` | 单 Job 状态/attempts/error | 未定义返回字段 |
| `POST /jobs/{id}/retry` | 人工重试 | 原方案只有图里虚线，无接口 |
| `POST /jobs/{id}/recover` | 卡死回收 | 完全缺失 |
| `GET /health/live`、`/health/ready` | 沿用现状 | — |
