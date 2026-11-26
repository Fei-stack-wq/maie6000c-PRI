# Operations / 运行说明

## English

### Quick start

Start Docker Desktop. From the repository root:

```powershell
.\scripts\start_product_ui.ps1
```

Open <http://localhost:8000/ui/>. Use the language selector at the top right.
The script keeps your existing `.env`, builds the services and applies migrations through
`20261126_0010`. First-time CPU model installation/download can take several minutes.
Startup also performs the one-time local repair of unreviewed legacy groups; no provider requests
are used for that repair. Old uploads with unrecoverable occurrence information are marked on screen.

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
```

Stopping the whole stack keeps its data volume. The page's **Stop remaining analysis** button
instead cancels unfinished records in one batch and keeps other batches running.

### Using batches and results

1. Upload a UTF-8 CSV with `shop_id,product_id,body`. Optional columns are
   `source_review_id,review_date,rating`. Each file belongs to one platform.
2. Open batch progress. Completed, failed, queued and cancelled counts are separate.
3. Comments and Issue groups offer complete batch/product options with multiple selection.
   Product choices follow the selected batches. Empty selection means all.
4. The issue board lists batch → product → category, with grouped entries above pending entries.
   Check evidence before confirming; use Review / reassign to correct either kind.
5. Stop cancels unfinished work permanently for that batch. Late results are ignored. Completed
   `no` and `unknown` reviews remain visible; cancelled records are available in the imported-record view.
6. Move a batch to Trash to hide it, Restore to bring its saved content back, or Delete permanently
   to remove that batch only. Restoring does not resume cancelled jobs. Permanent deletion is irreversible.

Each deliberate upload has independent snapshots/jobs, even if the source IDs or file are unchanged.
The same upload request's idempotency key protects network retries from creating another batch.
Do not remove the PostgreSQL volume when updating the application.

### Model and identity configuration

Keep the provider Key in ignored local `.env`. The configurable fields remain `LLM_PROVIDER`,
`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_API_KEY_HEADER` and `LLM_TIMEOUT_SECONDS`.
`LLM_PROVIDER=heuristic` runs without an external Key. The standard prompt is now
`review-extraction-v2`; the adapter upgrades the old standard v1 name when an existing `.env` retains it.

Configured model failures receive at most two retries before keyword fallback. Missing configuration
falls back immediately. Model attempts and Worker job attempts are separate. Rule fallback and
uncertain/unsupported results remain pending; high confidence alone cannot trigger automatic adoption.
MiniLM grouping runs locally and needs no extra provider Key.

Local demo identity writes real data. For named local accounts, use session mode and set
`REVIEW_COOKIE_SECURE=false` only for local HTTP. HTTPS deployments use secure cookies.
Create accounts interactively, without putting passwords in command arguments:

```bash
docker compose exec -it api python -m services.api.app.auth.manage create reviewer1 --role reviewer
docker compose exec -it api python -m services.api.app.auth.manage create viewer1 --role viewer
```

Reviewers can upload and change data; viewers can read. Account changes revoke existing sessions.
Business requests use same-origin session/CSRF checks. The workbench is a shared team workspace,
not a per-store authorization system.

### Monitoring and checks

| Check | Command / location |
| --- | --- |
| Services/logs | Docker Desktop, or `docker compose ps` and `docker compose logs --tail 100 api worker ai` |
| Health | API/AI `/health/live` and `/health/ready` |
| Metrics | API/AI `/metrics`; Worker port 8200 inside the network |
| Real grouping backend | `docker compose exec ai python -m scripts.probe_grouping_backend` |
| Python tests | Python 3.11: `pip install -e ".[dev]"`, then `python -m pytest -q tests/unit tests/integration` |
| PostgreSQL concurrency | Set `WORKER_TEST_DATABASE_URL` to an isolated database whose name ends in `_test` |
| Frontend | Node 22+: `node --test tests/frontend/*.cjs` |
| Migration consistency | In an isolated database: `alembic upgrade head` then `alembic check` |
| Windows isolated checks | `.\scripts\test_r2.ps1` |

The startup script handles machines without a registered `docker compose` command. Docker Desktop's
log view is also available. Never run migration round-trips or destructive tests against the project database.
Downgrades refuse data states that cannot fit the older schema without loss; restore a backup instead.

### Separate midterm demo

```powershell
.\scripts\start_midterm_demo.ps1
```

Open <http://localhost:18717/en> or <http://localhost:18717/zh>. This demonstration uses an independent
database and retains its original controls. `/ui/legacy/` and `/ui/previous/` are archived frontend previews.

## 中文

### 快速启动

启动 Docker Desktop，在仓库根目录运行：

```powershell
.\scripts\start_product_ui.ps1
```

打开 <http://localhost:8000/ui/>，右上角切换中英文。
脚本保留现有 `.env`，构建服务并迁移到 `20261126_0010`；首次安装 CPU 模型及下载权重可能需要数分钟。
启动时还会一次性整理未人工处理的旧归组，直接使用已保存输出，不调用外部模型。
旧版无法完整还原的批次记录会在页面标明。

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
```

关闭整套服务会保留数据卷。页面的“停止剩余分析”只取消某个批次的未完成记录，其他批次继续运行。

### 使用批次与结果

1. 上传 UTF-8 CSV，必填 `shop_id,product_id,body`；可选
   `source_review_id,review_date,rating`。每个文件对应一个平台。
2. 批次详情分别显示完成、失败、等待和取消数量。
3. 评论和问题组提供完整的批次、商品多选项；商品随批次联动，不指定时查看全部。
4. 问题看板按“批次 → 商品 → 类别”排列，上方已归组、下方待确认。先核对证据，再确认；两种内容均可调整归组。
5. 停止后不再继续该批次的未完成任务，迟到结果不落库。完成的 no、unknown 评论仍保留；取消内容在原始导入记录中查看。
6. 移到回收站用于隐藏，恢复带回原有内容，永久删除仅清除该批次。恢复不会重启取消任务，永久删除不能撤销。

每次主动上传都保存独立正文和任务，即使来源编号或文件相同。相同请求的幂等编号用于避免网络重试重复建批次。
更新应用时不要删除 PostgreSQL 数据卷。

### 模型与身份配置

Key 保存在已忽略的本地 `.env`。继续使用 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_MODEL`、
`LLM_API_KEY`、`LLM_API_KEY_HEADER`、`LLM_TIMEOUT_SECONDS`。
`LLM_PROVIDER=heuristic` 不调用外部模型。标准提示词更新为 `review-extraction-v2`，
已有 `.env` 保留旧标准 v1 名称时，适配器会使用新版并记录新版名称。

模型已配置但调用失败时最多重试两次，再回退关键词；缺少配置立即回退。
模型次数与 Worker 任务次数分开计算。规则回退和不明确的结果保持待确认，不能只凭模型自报高分自动通过。
MiniLM 归组在本地运行，不需要额外提供方 Key。

本地演示身份会写真实数据。具名本地账号使用 session 模式，仅本地 HTTP 设置 `REVIEW_COOKIE_SECURE=false`；
HTTPS 部署使用安全 Cookie。交互式创建账号，不把密码放入命令参数：

```bash
docker compose exec -it api python -m services.api.app.auth.manage create reviewer1 --role reviewer
docker compose exec -it api python -m services.api.app.auth.manage create viewer1 --role viewer
```

复核员可上传和修改，只读成员只能查看。账号变更会撤销已有会话；业务请求使用同源、会话和 CSRF 检查。
当前是小组共享工作区，不提供按店铺划分的账号授权。

### 运行检查

| 检查 | 命令／位置 |
| --- | --- |
| 服务和日志 | Docker Desktop，或 `docker compose ps`、`docker compose logs --tail 100 api worker ai` |
| 健康状态 | API／AI 的 `/health/live`、`/health/ready` |
| 指标 | API／AI 的 `/metrics`；Worker 使用网络内部的 8200 端口 |
| 真实归组后端 | `docker compose exec ai python -m scripts.probe_grouping_backend` |
| Python 测试 | Python 3.11：`pip install -e ".[dev]"` 后运行 `python -m pytest -q tests/unit tests/integration` |
| PostgreSQL 并发 | `WORKER_TEST_DATABASE_URL` 指向独立且名称以 `_test` 结尾的数据库 |
| 前端 | Node 22+：`node --test tests/frontend/*.cjs` |
| 迁移一致性 | 独立数据库中运行 `alembic upgrade head`、`alembic check` |
| Windows 隔离检查 | `.\scripts\test_r2.ps1` |

启动脚本兼容没有注册 `docker compose` 命令的机器，也可在 Docker Desktop 查看日志。
迁移往返和删除测试不能针对项目数据库执行。新数据无法无损放回旧结构时，降级会被阻止，应通过备份恢复。

### 独立期中 Demo

```powershell
.\scripts\start_midterm_demo.ps1
```

打开 <http://localhost:18717/en> 或 <http://localhost:18717/zh>。它继续使用独立数据库和原有控制方式。
`/ui/legacy/`、`/ui/previous/` 是保留的前端历史预览。
