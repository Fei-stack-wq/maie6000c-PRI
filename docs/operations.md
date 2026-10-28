# 运维与本地运行（Operations）

> 面向本地开发与演示；生产化部署（TLS、备份、密钥管理）不在课程范围内。

## 1. 启停

```bash
cp .env.example .env          # 第一次
docker compose up --build     # db + api + worker + ai
docker compose down --remove-orphans
docker compose down -v --remove-orphans   # 连数据卷一起删（会丢数据）
```

端口：API `8000`（`/docs` 接口文档、`/ui/` 静态界面）、AI `8100`、PostgreSQL `5432`；
可选 `docker compose --profile observability up` 启动 Prometheus `9090`。

## 2. 数据库

```bash
# 迁移到最新
docker compose run --rm api alembic upgrade head

# 清空所有数据并重建 schema（会删除全部数据，带确认）
docker compose run --rm api python scripts/reset_database.py
make reset-db

# 演示数据（幂等：已有 demo 批次时跳过）
docker compose run --rm api python scripts/seed_demo_data.py
make seed
```

迁移链：`0001`（旧骨架，仅历史）→ `0002`（评论域 8 张表 + jobs 扩展）→
`0003`（移除 cases、收敛 jobs）。**不要修改已应用的迁移**，新增字段用新迁移。

## 3. 接口与界面

- API 文档：`http://localhost:8000/docs`（OpenAPI 自动生成）
- 静态界面：`http://localhost:8000/ui/`（批次 / 评论 / 问题组 / 复核 / 关于）
- 健康检查：`/health/live`、`/health/ready`；指标：`/metrics`（API 与 AI 各一份）

## 4. 失败处理

- 分析失败：`jobs.status=failed`、`jobs.error_code` 记录分类（`ai_timeout` / `ai_error` /
  `ai_invalid_output` / `db_error` / `unknown`），评论 `analysis_status=failed`，界面可见。
- Worker 中断：`claimed` 且租约过期的 Job 由 Worker 启动时的巡检退回 `pending`
  （R2 会拆成独立脚本/定时任务）。
- 自动重试已实现；人工 retry API 与批量重放脚本尚未实现。过期任务巡检可执行 `python -m scripts.recover_stale_jobs`。
- 数据库不可用：`/health/ready` 失败，Worker/AI 继续重试；不会伪造分析结果。

## 5. 常见问题

| 现象 | 处理 |
| --- | --- |
| `docker compose up` 后 API 起不来 | 先看 `docker compose logs api`；确认 `alembic upgrade head` 成功、`.env` 已创建 |
| 迁移报 `case_id`/`cases` 相关错误 | 本地库是旧结构：`make reset-db` 重建（会清数据） |
| 界面 404 | 确认 `frontend/` 存在且 API 已重启（静态目录在启动时挂载） |
| 测试需要数据库吗 | 不需要：`tests/` 使用内存 SQLite（`StaticPool`），CI 也跑单元+集成 |
| 想清空演示数据但保留表 | 用 `reset_database.py` 会连表一起重建；只想清数据可用 `TRUNCATE`（注意外键） |

## R2 运行与验证

任务等待重试时为 pending，评论为 queued；next_attempt_at 表示下次允许执行时间。attempts 仅在真正领取时增加，回收不增加。Worker 内部 8200 提供指标，Prometheus 已配置采集。

完整配置、故障处理、测试复现和未实现边界见 [r2-implementation.md](r2-implementation.md)。
