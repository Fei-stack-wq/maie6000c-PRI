# Development Progress / 开发进度

## English

### 1. Current snapshot — 29 October 2026

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

### 1. 当前状态——2026 年 10 月 29 日

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
