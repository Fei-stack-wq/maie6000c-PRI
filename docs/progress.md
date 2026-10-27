# 当前进度

> 看板式清单，完成一项勾一项；命令均在仓库根目录执行。

## 1. 一句话状态

单平台初版的最小闭环已经跑通：**CSV 批次接入 → 评论/版本入库 → 逐条 Job → Worker 调用 AI 提取问题与证据 → 问题组聚合 → 静态 UI 查看/筛选/搜索/详情**；真实 PostgreSQL 上完成了迁移、清库重建、种子数据和端到端验证。当前 Worker/AI 仍是规则基线，前端仍是 mock 数据，真实平台入口与质量评测待补。

## 2. 已完成

### 2.1 契约与数据层

| 事项 | 证据 / 位置 |
| --- | --- |
| 数据模型与接口契约（9 张表、状态机、错误码、读模型） | `docs/architecture.md` §6–§9；`services/common/models.py`、`schemas.py` |
| 迁移链：0002 建评论域 + 0003 移除旧 `Case/triage` 骨架、收敛 `jobs` | `alembic/versions/20261027_0002_review_management.py`、`20261027_0003_remove_legacy_case_domain.py` |
| 旧域清理 | `Case`/`triage` 已从 models/schemas/api/worker/ai/seed/tests 移除；`jobs.comment_id` 必填；`job_type` 仅 `extract_issues` |
| 唯一约束 / CHECK / 部分唯一索引 | 评论来源唯一键、`ck_jobs_status`、`ck_jobs_job_type`、单评论仅一个活跃 Job、`analysis_status` CHECK |
| 迁移可逆 | 真实 PostgreSQL `downgrade 20260713_0001 → upgrade head` 均通过；离线 SQL 亦通过 |

### 2.2 R1 数据与接入

| 事项 | 详情 |
| --- | --- |
| **CSV 内容结构定义** | 必填列：`shop_id`、`product_id`、`body`；可选列：`source_review_id`、`review_date`、`rating`；`platform` 由请求传入 |
| **字段校验** | `shop_id`/`product_id` 非空且 ≤64 字符；`body` 非空且 ≤2000 字符；`review_date` 支持 ISO 日期/日期时间；`rating` 为 0–5 整数；单批 ≤5000 行 |
| **解析与规范化** | `services/api/app/ingestion.py` 的 `parse_csv`：表头校验、逐行解析、去 BOM/空白、正文归一化、计算 `content_hash`；缺 `source_review_id` 时生成稳定 `synth:<hash>` 并标记 `dedupe_mode=content_hash` |
| **逐行错误清单** | `batch_rows` 落库行号、列名、错误码（`required`/`too_long`/`invalid_date`/`invalid_rating` 等）；有效行继续入库，批次汇总为部分失败 |
| **去重与版本** | 有来源编号按 `(platform, shop, product, source_review_id)` 去重；无来源编号按内容 hash；正文变化追加 `comment_revisions` 并推进 `version`，重复行计入 `duplicate_rows` |
| **批次幂等** | `POST /review-batches` 支持 `idempotency_key`；重复提交返回同一批次，不重复建评论/Job |
| **建 Job** | 每条有效评论同一事务内建一个 `extract_issues` Job，批次只做汇总；批次进度由 Job/评论状态派生（`imported`/`completed`/`partially_failed`） |
| **CSV 上传验证** | `tests/integration/test_api_case_flow.py` 覆盖批次上传建评论/Job、部分行错误清单、`Idempotency-Key` 幂等、重复上传去重、缺列 422；`tests/integration/test_e2e_flow.py` 覆盖上传 → Worker → AI → 问题组；`tests/unit/test_ingestion.py` 覆盖解析、缺来源编号、坏行保留 |
| **读接口** | 批次进度与错误清单、评论列表/详情（含版本、证据、最近分析）、问题组列表/详情、任务详情、统计汇总；见 `services/api/app/main.py` |
| **重置与种子** | `scripts/reset_database.py`（删 schema 重建 + 迁移）、`scripts/seed_demo_data.py`（6 评论 / 3 问题组 / 6 Job，幂等）；`make reset-db`、`make seed` |
| **待补** | 真实平台入口（商家 CSV / 授权接口）、multipart 文件上传、错误清单 CSV 导出、cursor 分页；当前使用 JSON `csv_text` + `limit/offset` |

### 2.3 R2 流水线

| 事项 | 详情 |
| --- | --- |
| 原子认领 + 租约 | PostgreSQL `FOR UPDATE SKIP LOCKED` 认领 pending Job，写 `claimed`、`lease_expires_at`、`attempts`；轮询间隔与超时可配置 |
| 过期回收 | Worker 启动/循环中把租约过期且未完成的 Job 回收为 pending（attempts 达上限则 failed） |
| AI 调用与落库 | 调用内部 AI `/extract-issues`；记录 `analysis_runs`（模型/prompt/输入 hash/原始输出/耗时）；按评论 upsert 问题组与证据链接 |
| 证据校验 | 校验 AI 返回的证据必须是原文子串；定位失败降级为 `unknown`，不伪造区间 |
| 重跑语义 | 重跑保留历史 `analysis_runs`；旧的 AI `suggested` 关联写 `superseded_at`，人工 `accepted/rejected` 不覆盖 |
| 失败可见 | 记录 `error_code`（AI 超时/非法输出/内部错误等）并把评论标为 failed，支持人工重试 |
| 待补 | fencing token、`retry/recover` 管理接口、批量重放脚本、Worker 指标与并发/幂等专项 |

### 2.4 R3 AI 服务

| 事项 | 详情 |
| --- | --- |
| 规则基线 | `services/ai/app/main.py` 的 `/extract-issues`：受控类别（`services/common/categories.py`，`CATEGORY_VERSION=v1`）、关键词匹配、证据句定位、`has_issue` 三态输出 |
| 输出契约 | `ExtractionResult`（has_issue / issues[] / evidence / category / confidence）；与 R2 的落库逻辑通过 HTTP 契约解耦 |
| 占位能力 | `/suggest-groups` 目前为占位，用于后续同商品归组 |
| 待补 | LLM 替换规则基线、统一证据校验函数、同商品语义归组、标注集与 P/R/F1、成本记录 |

### 2.5 R4 产品端

| 事项 | 详情 |
| --- | --- |
| 五页静态界面 | 批次 / 评论 / 问题组 / 人工复核 / 关于；原生 HTML/CSS/JS，无构建、无外部 CDN；API 挂载 `/ui/` |
| 问题组页 | 顶部搜索 + 状态分段筛选 + 类别/商品筛选；状态色卡片（待确认/已确认/已解决/已忽略）；高/中/低优先级标签；标题/摘要/证据/统计；移动端折叠筛选与横向状态筛选 |
| 问题组详情 | `#/issues/{id}`：状态色 hero、判断依据、AI 建议关联、处理记录时间线、相关评论（评分/平台/日期/证据高亮）；确认/跟进/驳回 mock 动作；返回列表保留筛选与滚动位置 |
| 动效 | 页面进入、卡片错峰入场、筛选刷新、状态指示器滑动、悬停/按下反馈、减少动态效果适配 |
| 其他页面 | 批次上传（mock）、评论三条件筛选与证据高亮、人工复核接受/拒绝/改判 + 本地审计、关于页 API/文档/成员 |
| 待补 | `POST /issues/{id}/actions`、`/comment-issues/{id}/decision`、真实接口替换 mock、e2e 演示脚本 |

### 2.6 集成与质量

| 事项 | 结果 |
| --- | --- |
| 真实 PostgreSQL 清库重建 | 9 张业务表 + `alembic_version`；`cases` 已不存在；种子 comments=6 / issues=3 / jobs=6 |
| 真实端到端 | 真实 Docker 栈上传 3 条评论 → Worker → AI：3 条 analyzed、问题组与证据 `evidence_verified`、重复上传 `duplicate_rows=3` |
| 自动化测试 | `pytest -q`：15 passed, 1 skipped（smoke 需运行环境）；单元覆盖 CSV 解析/校验、AI 规则；集成覆盖批次、幂等、错误清单、评论/问题组、UI、端到端流程 |
| 冒烟 | `SMOKE_BASE_URL=http://127.0.0.1:8000 pytest tests/smoke`：1 passed（真实服务） |
| 迁移 | 离线 SQL 与真实 PostgreSQL 往返均通过 |
| 文档 | architecture / README / operations / team-division / progress 重写并与代码对齐；`review/` 仅保留评审与过程文档 |

## 3. 待完成

| 线 | 事项 | 说明 |
| --- | --- | --- |
| R1 | 真实平台入口验证、multipart 文件上传、错误清单 CSV 导出、cursor 分页 | 目前 JSON 内嵌 CSV + limit/offset |
| R2 | 租约/重试/fencing 完整化、错误码分类、`retry`/`recover` 接口、批量重放、Worker 指标 | 当前为可跑的最小循环 |
| R3 | LLM 提取、统一证据校验、同商品归组、标注集与 P/R/F1、成本记录 | 当前为关键词规则基线 |
| R4 | 复核动作 API、问题组/评论接口接真实数据、e2e 演示 | 读接口已存在；前端 mock 动作待替换 |
| 全组 | 平台数据授权与样本获取、演示材料与最终报告 | 不依赖代码的收尾项 |

## 4. 本地验证命令

```bash
# 数据库（Docker Compose）
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose run --rm api python scripts/reset_database.py --yes   # 清库重建（删除全部数据）
docker compose run --rm api python scripts/seed_demo_data.py         # 演示数据

# 服务
docker compose up --build
# API: http://localhost:8000/docs   UI: http://localhost:8000/ui/

# 测试
make test            # unit + integration（内存 SQLite，无需数据库）
SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q
```

## 5. 验证记录

| 检查 | 结果 |
| --- | --- |
| 单元 + 集成测试 | 15 passed, 1 skipped（smoke 需运行环境） |
| 真实迁移往返 | `downgrade 20260713_0001` → `upgrade head` 均通过，最终版本 `20261027_0003` |
| 真实清库重建 | 9 张业务表 + `alembic_version`；`cases` 不存在 |
| 真实种子数据 | comments=6 / issues=3 / jobs=6（1 条待分析） |
| 真实端到端 | 上传 → Worker → AI → 问题组/证据全部通过；重复上传去重 |
| 真实 smoke | 1 passed |
| UI | 桌面/移动端/筛选/搜索/已忽略/详情均验证；无控制台错误、无横向溢出 |
| 迁移离线 SQL | upgrade / downgrade 均 EXIT=0 |

## 6. 交接注意

1. 本次交付已提交到本地 git，`main` 工作区干净；远程推送由团队决定。
2. **迁移一旦 apply，不再改历史**：后续字段写 0004+；本地重置用 `make reset-db`。
3. 契约变更走 `docs/team-division.md` §5 流程；共享文件单写者（R1）。
4. `frontend/` 目前是 mock 数据；真实接口由 R4 后续接入。
5. 评审/过程文档保留在 `review/`；工具脚本与中间产物已按整理要求清理。
