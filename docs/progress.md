# Development Progress / 开发进度

## English — integrated state, 26 November 2026

`integrate_v1` combines the model/frontend branch with semantic grouping and human review. The default UI uses the team's modular workbench; original static and previous read-only versions remain archived. Model attempts are limited to three before marked rule fallback; absent configuration uses rules without a provider request. Source, fallback reason and model attempts are shown in comment details.

The integrated path is CSV import → persisted reviews/jobs → model/rule extraction → semantic grouping → saved evidence → human review → issue follow-up. Review/version protection, sessions, manual evidence, rechecks and merge/split are retained. Completed historic imports are not automatically regrouped.

Verification so far: 446 Python unit/integration tests passed against isolated PostgreSQL, including the added key-free retries; 12 frontend tests passed. Migrations through `20261121_0006` and `alembic check` passed. See [integration verification](integrate-v1-verification.md) for live checks and exact limits. These local results do not imply remote CI or unrestricted model accuracy.

Remaining work: representative quality evaluation, real-platform ingestion adapters as required by the team, and operator-driven failed-job replay. Review extraction still permits at most one issue per category per review.

## 中文——2026 年 11 月 26 日整合状态

`integrate_v1` 已整合模型／前端、语义归组和人工复核。默认入口采用组员的模块化工作台，原静态设计和上次只读前端单独归档。模型最多尝试三次后回退规则；缺少配置时不发送外部请求。评论详情显示来源、回退原因及模型尝试次数。

整合流程为 CSV 导入 → 评论／任务落库 → 模型／规则提取 → 语义归组 → 保存证据 → 人工复核 → 问题跟进。保留复核版本保护、会话身份、人工证据、原文重核和合并／拆分。已完成的历史批次不会自动重新归组。

已验证：隔离 PostgreSQL 环境中 446 项 Python 单元／集成测试通过，包含新增无密钥重试测试；12 项前端测试通过；数据库迁移到 `20261121_0006` 及 `alembic check` 通过。真实运行检查与限制见[整合验证记录](integrate-v1-verification.md)。这些本地结果不代表远端 CI 已运行，也不代表不受限评论的模型准确率。

后续工作：代表性质量评测、团队需要的真实平台数据适配、人工发起失败任务重放。提取器目前每条评论每个类别最多一个问题。

---

The following sections are historical milestone records. / 下文为历史里程碑记录。

## English

### 1. Historical snapshot — 29 October 2026

The working path is review submission → database/job creation → background rule analysis →
evidence validation → saved results shown in the midterm demo. The original product frontend still
uses mock data. The midterm interface uses the project backend and its own PostgreSQL database.

### 2. Completed and remaining work

| Area | Completed | Remaining |
| --- | --- | --- |
| Data/ingestion | Nine domain tables, migrations, CSV/JSON checks, row errors, deduplication, revisions and queries | Real platform samples, direct file upload, error export and pagination improvements |
| Background jobs | Claim ownership, retries, expiry recovery, transactional saves, evidence validation, changed-input requeue and metrics | Manual task retry/recover endpoints, batch replay and persistent task-operation audit |
| Analysis | Chinese/English rule issues, three-way result and source evidence; category grouping | LLM extraction, semantic grouping, labelled evaluation and cost records |
| Product frontend | Five-page layout, filtering/detail views and mock review interactions | Live API data and persistent human decisions/follow-up |
| Midterm demo | Separate source build/database, Chinese and English URLs, normal/retry/failure scenarios, startup/check/stop scripts | No further demo features planned for this milestone |

Members: FEI, Wenxiang; XIANG, Ke; XU, Chao; ZHANG, Mingyang.

A known limitation from demo use is missed warranty/after-sales complaints, including refusal to
provide a warranty. Results may be `no` or `unknown`. Improving rule coverage and measuring missed
and wrongly flagged complaints are analysis work; the current milestone remains a processing demo.

### 3. Verification

Recorded checks on 29 October: 94 unit/integration tests including six PostgreSQL tests; five real
HTTP smoke tests; migration round-trip and graceful shutdown; ten bilingual demo cases;
restart persistence of five jobs/eight analysis attempts in an isolated test run.
The R2 statement coverage record is 92%; it is not an analysis-quality score.
The later delivery-rule extension passed 78 analysis unit tests and four live demo regressions,
separately from the earlier full-suite run. The developer checked English-page buttons.
Commands, conditions and the result screenshot are indexed in the
[verification record](../templates/submissions/week07/assets/verification.md).

### 4. Next steps

1. Collect representative reviews and evaluate missed and wrongly flagged complaints.
2. Implement and evaluate model extraction and semantic grouping.
3. Connect the product frontend and persist human review and follow-up.
4. Add manual task replay and task-operation records.

## 中文

### 1. 历史状态——2026 年 10 月 29 日

已接通评论提交 → 入库建任务 → 后台规则分析 → 证据检查 → 结果保存并在期中 Demo 展示。
原产品前端仍使用模拟数据。期中界面使用项目后台和独立的 PostgreSQL 数据库。

### 2. 已完成与待完成

| 方面 | 已完成 | 待完成 |
| --- | --- | --- |
| 数据／接入 | 九张业务表、迁移、CSV／JSON 检查、错误行、去重、版本和查询 | 真实平台样本、直接文件上传、错误导出和分页改进 |
| 后台任务 | 领取归属、重试、过期回收、事务保存、证据检查、正文更新重排队和指标 | 人工任务重试／回收接口、批量重放、持久化任务操作审计 |
| 分析 | 中英文规则、三态结果和原文证据；按类别归组 | 大模型提取、语义归组、标注评测与成本记录 |
| 产品前端 | 五页布局、筛选／详情和模拟复核交互 | 真实接口数据、人工决定与跟进落库 |
| 期中 Demo | 独立源码构建／数据库、中英文地址、正常／重试／失败场景、启停与检查脚本 | 本阶段不再扩展演示功能 |

成员：FEI, Wenxiang；XIANG, Ke；XU, Chao；ZHANG, Mingyang。

Demo 使用中已发现拒绝保修等售后投诉可能漏检，结果可能是 `no` 或 `unknown`。
扩展规则和评估漏检、误判属于后续分析工作，本阶段仍以处理流程演示为主。

### 3. 验证情况

10 月 29 日已有记录：94 项单元／集成（含六项 PostgreSQL）、5 项真实 HTTP 冒烟、
迁移往返及正常退出、独立 Demo 十例双语，以及一次隔离测试中重启后保留五个任务／八次分析。
R2 语句覆盖率记录为 92%，不是分析准确率。
后续物流规则扩展另通过 78 项分析单元测试和四例真实 Demo 回归，与较早完整测试分开记录。
开发者已检查英文页按钮。
命令、条件和结果截图见 [验证记录](../templates/submissions/week07/assets/verification.md)。

### 4. 下一步

1. 收集有代表性的评论，评估漏检和误判。
2. 实现并评测模型提取和语义归组。
3. 产品前端接真实接口，保存人工复核和跟进记录。
4. 增加人工任务重放及任务操作记录。
