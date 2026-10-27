# 当前进度与串行关口（W5 → W6 起点）

> 更新时间：2026-10-27。看板式清单，完成一项勾一项；命令均在仓库根目录执行。

## 1. 一句话状态

**W5 串行关口已完成**：契约冻结、迁移可执行、R1 接入链路打通、静态 UI 五页可跳转；
四条工作流（R1–R4）可以并行进入 W6。系统目前是**可演示的最小闭环骨架**
（规则基线 AI + 简化 Worker），不是最终质量版本。

## 2. 已完成

| # | 事项 | 证据 / 位置 |
| --- | --- | --- |
| 1 | 数据结构与契约冻结（9 表、状态机、接口） | `docs/architecture.md` §6–§8；`services/common/models.py`、`schemas.py` |
| 2 | 迁移链：0002 建评论域 + 0003 移除旧骨架、收敛 jobs | `alembic/versions/20261027_0002…`、`…_0003…` |
| 3 | 旧数据/旧代码清理 | `Case`/`triage` 已从 models/schemas/api/worker/ai/seed/tests 移除 |
| 4 | R1 批量接入：CSV 解析、逐行校验、错误清单、去重 upsert、评论版本、建 Job | `services/api/app/ingestion.py`；`POST /review-batches`、`GET /review-batches/{id}`、`/errors` |
| 5 | R1 读接口：评论列表/详情、问题组列表/详情、任务、统计汇总、幂等键 | `services/api/app/main.py` |
| 6 | 静态 UI：批次/评论/问题组/复核/关于 五页导航（mock 数据） | `frontend/`；API 挂载 `/ui/` |
| 7 | Worker/AI 规则基线可跑（认领→AI→落库） | `services/worker/app/main.py`、`services/ai/app/main.py` |
| 8 | 数据库重置与种子数据 | `scripts/reset_database.py`、`scripts/seed_demo_data.py`、`make reset-db` / `make seed` |
| 9 | 测试基线：ingestion 单测、AI 单测、API 集成（内存 SQLite） | `tests/unit/`、`tests/integration/`，`make test` |
| 10 | 团队分工与边界文档 | `docs/team-division.md` |

## 3. 尚未完成（W6–W11，按线）

| 线 | 事项 | 说明 |
| --- | --- | --- |
| R1 | 真实入口验证（商家 CSV / 接口）、multipart 文件上传、cursor 分页、错误清单 CSV 导出 | 目前 JSON 内嵌 CSV 与 limit/offset |
| R2 | 租约/重试/fencing 完整化、错误码分类、`retry`/`recover` 接口、批量重放脚本、Worker 指标 | 当前 Worker 是可跑的最小循环 |
| R3 | LLM 提取、证据校验函数统一、同商品归组、标注集与 P/R/F1、成本记录 | 当前为关键词规则基线 |
| R4 | `POST /issues/{id}/actions`、`/comment-issues/{id}/decision`、问题组看板接真实接口、e2e 演示 | 读接口已存在，动作未实现 |
| 全组 | 在真实 PostgreSQL 上跑一次 `upgrade → downgrade → upgrade`；W6 集成日联调 | 本机当前无 Docker/PG，只能用离线 SQL + SQLite 验证 |

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
```

## 4.1 验证记录（2026-10-27，真实 Docker + PostgreSQL）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 单元 + 集成测试 | `pytest -q`（内存 SQLite） | 15 passed, 1 skipped（smoke 需运行环境） |
| **真实迁移往返** | `alembic downgrade 20260713_0001` → `alembic upgrade head`（PostgreSQL 容器） | 均 EXIT=0，最终版本 `20261027_0003` |
| **真实清库重建** | `python scripts/reset_database.py --yes` | 数据库清空并按 0001→0002→0003 重建，最终 9 张业务表 + `alembic_version`，`cases` 已不存在 |
| **真实种子数据** | `python scripts/seed_demo_data.py` | comments=6 / issues=3 / jobs=6（1 条待分析） |
| **真实端到端** | `python review/_e2e_real.py`（上传 → Worker → AI → 问题组） | REAL E2E OK：3 条全部 analyzed、证据 `evidence_verified`、重复上传 duplicate=3 |
| 真实 smoke | `SMOKE_BASE_URL=http://127.0.0.1:8000 pytest tests/smoke` | 1 passed |
| **UI 真实浏览器** | headless Chrome 截图 `review/ui-{batches,issues,reviews}.png` | 五页导航/激活态/看板渲染正常 |
| 迁移离线 SQL | `alembic upgrade head --sql` / `alembic downgrade head:20260713_0001 --sql` | 均 EXIT=0 |
| 模型/迁移/契约静态一致 | `python review/_check_impl.py` | all static checks passed |
| 文档 vs 模型一致性 | `python review/_check_docs.py` | all doc/code checks passed |
| 运行时约束/契约 | `python review/_validate_runtime.py` | all runtime checks passed |
| 演示数据 → API 读接口 | `python review/_validate_demo_api.py` | DEMO + API VALIDATION OK |
| 种子脚本幂等 | `python review/_validate_seed.py` | SEED VALIDATION OK |
| 前端 JS 语法 | `node --check frontend/app.js` | 通过（5 页路由 + hashchange） |

> 结论：契约、迁移、清库重建、种子数据、Worker/AI 链路、UI 与真实 PostgreSQL 均已跑通；
> 剩余的真实平台入口验证属于 R1 的 W6 数据获取工作。

## 5. 交接注意

1. 本次交付已提交到本地 git（commit `W5 serial gate`），`main` 工作区干净；远程推送由团队决定。
2. **迁移一旦 apply，不再改历史**：后续字段写 0004+；本地重置用 `make reset-db`。
3. 契约变更走 `docs/team-division.md` §5 流程；共享文件单写者（R1）。
4. `frontend/` 目前是 mock 数据；W6 起 R4 按 `docs/architecture.md` §8 逐步接真实接口。
5. 一次性脚本（Proposal 提取、图表生成、校验）统一放在 `review/`；`review/ui-*.png` 为界面验收截图。
