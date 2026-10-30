# Operations / 运行说明

## English

### 1. Midterm demo: quickest start

Start Docker Desktop. In the repository root:

```powershell
# Windows
.\scripts\start_midterm_demo.ps1
```

```bash
# macOS / Linux
docker compose -f compose.midterm.yaml up --build -d --wait
```

Open **<http://localhost:18717/en>** or <http://localhost:18717/zh>.
Keep the sample review, submit it, then start analysis. Use a new round to try retry scenarios.
The [demo instructions](../demo/midterm/README.md) cover the buttons, port changes and shutdown.
This mode builds from repository source, needs no `.env` or API key, and creates its own database.
It can run alongside the original project.

### 2. Original project services

Use this mode for API development and the team's original five-page frontend.

```bash
cp .env.example .env
docker compose up --build -d --wait
```

On Windows, `Copy-Item .env.example .env` is also available. Copy only on first setup;
keep an existing `.env` if it contains your settings.

| Address | Use |
| --- | --- |
| `http://localhost:8000/docs` | Submit real batches and query the backend |
| `http://localhost:8000/ui/` | Original frontend; its business data is mock data |
| `http://localhost:8100/docs` | Rule-analysis API |
| `http://localhost:9090` | Prometheus after `docker compose --profile observability up -d` |

API startup applies the existing migrations. To add prepared sample data, run
`docker compose exec api python -m scripts.seed_demo_data`.
Seeded records are example data, not evidence of a newly executed analysis.
Stop this stack with `docker compose down`; this keeps its data volume.

### 3. Logs and monitoring

| Mode | Check |
| --- | --- |
| Midterm demo | ` .\scripts\start_midterm_demo.ps1 -Action status ` on Windows; otherwise `docker compose -f compose.midterm.yaml ps` |
| Midterm worker log | `docker compose -f compose.midterm.yaml exec midterm-demo sh -c "tail -n 60 /tmp/midterm-worker.log"` |
| Original stack | `docker compose ps` and `docker compose logs --tail 100 api worker ai` |

The demo worker log is created after starting analysis. API and AI child logs are
`/tmp/midterm-api.log` and `/tmp/midterm-ai.log` in the demo container.
Docker Desktop's container log view is useful if a local Compose command is unavailable.

API and AI expose `/health/live`, `/health/ready` and `/metrics`. Worker metrics use port 8200
inside the container/network, not a published host port. The original Prometheus configuration
scrapes `worker:8200`. Metrics are `worker_job_events_total`, `worker_attempt_duration_seconds`,
`worker_jobs` and `worker_last_poll_timestamp_seconds`. A running metrics endpoint alone does not
prove that the worker can reach the database; check the last successful poll and logs.
For the demo, read metrics after starting analysis:

```bash
docker compose -f compose.midterm.yaml exec midterm-demo python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8200/metrics').read().decode())"
```

### 4. Failures and recovery

A retryable failure returns the job to `pending` and the comment to `queued`, with a next-run time.
Final failures remain `failed`. The demo shows failures directly; the original project exposes them
through query APIs, while its mock frontend does not yet show live failures.
Every worker poll checks for expired claims and requeues or finally fails them according to the limit.
The same recovery can be invoked in the original stack:

```bash
docker compose exec worker python -m scripts.recover_stale_jobs
```

This does not restart terminal failed jobs. Manual retry/recover APIs and batch replay are not implemented.
For configuration and error rules, see [R2 implementation](r2-implementation.md).

### 5. Tests

| Check | Command and conditions |
| --- | --- |
| Demo's ten bilingual cases | Idle demo: ` .\scripts\start_midterm_demo.ps1 -Action check `; macOS/Linux command is in the demo instructions |
| Complete R2 checks | Windows with Docker: ` .\scripts\test_r2.ps1 ` creates and removes isolated test resources |
| Unit/integration only | Python 3.11 with `pip install -e ".[dev]"`: `python -m pytest -q tests/unit tests/integration` |
| PostgreSQL locking tests | Included above only with `WORKER_TEST_DATABASE_URL` pointing to a separate PostgreSQL database ending in `_test`; otherwise six tests skip |
| Original-stack smoke | `SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q` runs the basic smoke case; four fault/recovery cases require the isolated runner |

The R2 script runs unit/integration tests, five real-service smoke tests, migration round-trips
and shutdown checks. The earlier recorded run passed 94 unit/integration tests; a later delivery-rule
extension passed 78 analysis unit tests and four live demo regressions separately. Demo acceptance
is a separate ten-case bilingual check. See the [verification record](../templates/submissions/week07/assets/verification.md).

### 6. Troubleshooting and data maintenance

| Problem | Action |
| --- | --- |
| Cannot connect to Docker | Start Docker Desktop with Linux containers |
| Demo port occupied | Windows: add `-Port 18727`; macOS/Linux: set `MIDTERM_DEMO_PORT=18727` for the Compose startup command |
| Warranty/after-sales complaint returns no issue or unknown | This is a known rule-coverage limit, not necessarily an execution failure; inspect the original review |
| Build downloads fail | Check network access and retry the build |
| Demo does not become healthy | Inspect `midterm-demo` container logs; confirm migration and API/AI startup |
| Unknown result for an English review | English rules cover selected phrases; other text usually returns unknown, while positive cues can yield no issue; inspect the source review |

Stopping or starting a new demo round keeps database records. The demo has its own volume;
the original project has a different volume. Deleting a volume or resetting a database is a developer
maintenance action, not part of a normal demonstration. Applied migrations should be followed by
new migrations rather than edited in place. Use downgrade tests only on disposable test databases.

## 中文

### 1. 期中 Demo：最快启动

启动 Docker Desktop，在仓库根目录执行：

```powershell
# Windows
.\scripts\start_midterm_demo.ps1
```

```bash
# macOS / Linux
docker compose -f compose.midterm.yaml up --build -d --wait
```

打开 **<http://localhost:18717/en>** 或 <http://localhost:18717/zh>。
保留示例评论，先提交评论，再启动分析，开始新一轮可切换重试场景。
按钮、换端口和停止方法见 [Demo 运行说明](../demo/midterm/README.md)。
此模式从仓库源码构建，不需要 `.env` 或 API Key，创建独立数据库，可与原项目同时运行。

### 2. 原项目服务

开发 API 或查看组员原五页前端时使用此模式。

```bash
cp .env.example .env
docker compose up --build -d --wait
```

Windows 也可使用 `Copy-Item .env.example .env`。只在首次准备时复制，已有个人配置的 `.env` 应保留。

| 地址 | 用途 |
| --- | --- |
| `http://localhost:8000/docs` | 提交真实批次、查询后台 |
| `http://localhost:8000/ui/` | 原前端，业务数据仍为模拟数据 |
| `http://localhost:8100/docs` | 规则分析 API |
| `http://localhost:9090` | 执行 `docker compose --profile observability up -d` 后的 Prometheus |

API 启动时执行现有迁移。加入预制示例数据可执行
`docker compose exec api python -m scripts.seed_demo_data`。
种子记录是示例数据，不能作为刚刚执行了一次分析的证据。
使用 `docker compose down` 停止此栈，数据卷保留。

### 3. 日志与监控

| 模式 | 检查方法 |
| --- | --- |
| 期中 Demo | Windows 使用 ` .\scripts\start_midterm_demo.ps1 -Action status `；其他平台使用 `docker compose -f compose.midterm.yaml ps` |
| Demo Worker 日志 | `docker compose -f compose.midterm.yaml exec midterm-demo sh -c "tail -n 60 /tmp/midterm-worker.log"` |
| 原项目 | `docker compose ps` 和 `docker compose logs --tail 100 api worker ai` |

点击启动分析后才产生 Demo Worker 日志。API 和 AI 子进程日志分别位于容器内的
`/tmp/midterm-api.log`、`/tmp/midterm-ai.log`。
本机 Compose 命令不可用时，可以在 Docker Desktop 中查看容器日志。

API 和 AI 提供 `/health/live`、`/health/ready` 和 `/metrics`。Worker 指标使用容器／网络内的
8200 端口，不向宿主机发布。原项目 Prometheus 采集 `worker:8200`，指标包括
`worker_job_events_total`、`worker_attempt_duration_seconds`、`worker_jobs` 和
`worker_last_poll_timestamp_seconds`。指标端口能打开不代表数据库连通，应结合最近成功轮询和日志判断。
Demo 启动分析后可读取指标：

```bash
docker compose -f compose.midterm.yaml exec midterm-demo python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8200/metrics').read().decode())"
```

### 4. 失败与回收

可重试失败将任务放回 `pending`、评论放回 `queued`，并设置下次执行时间；最终失败保持 `failed`。
小 Demo 直接展示失败；原项目可通过查询接口查看，模拟前端尚不能展示实时失败。
Worker 每轮检查过期领取，根据剩余次数重新排队或最终失败。原项目也可以手动调用同一回收逻辑：

```bash
docker compose exec worker python -m scripts.recover_stale_jobs
```

它不会重新执行已经最终失败的任务。人工 retry/recover API 和批量重放尚未实现。
配置和错误规则见 [R2 实现说明](r2-implementation.md)。

### 5. 测试

| 检查 | 命令与条件 |
| --- | --- |
| Demo 十个双语用例 | 页面空闲时执行 ` .\scripts\start_midterm_demo.ps1 -Action check `；macOS/Linux 命令见 Demo 说明 |
| 完整 R2 检查 | Windows 启动 Docker 后执行 ` .\scripts\test_r2.ps1 `，脚本创建并清理独立测试资源 |
| 仅单元／集成 | Python 3.11 执行 `pip install -e ".[dev]"` 后运行 `python -m pytest -q tests/unit tests/integration` |
| PostgreSQL 锁测试 | 需将 `WORKER_TEST_DATABASE_URL` 指向名称以 `_test` 结尾的独立 PostgreSQL 测试库，否则六项跳过 |
| 原项目冒烟 | `SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q` 执行基础用例；四项故障／回收用例需要隔离启动脚本 |

完整 R2 脚本运行单元／集成、5 项真实服务冒烟、迁移往返和正常退出检查。
较早记录为 94 项单元／集成通过；后续物流规则扩展另通过 78 项分析单元测试和四例真实 Demo 回归。
Demo 验收是独立的十例双语检查。
结果见 [验证记录](../templates/submissions/week07/assets/verification.md)。

### 6. 问题排查与数据维护

| 问题 | 处理方式 |
| --- | --- |
| 无法连接 Docker | 启动 Docker Desktop 并使用 Linux containers |
| Demo 端口占用 | Windows 加 `-Port 18727`；macOS/Linux 在 Compose 启动命令前设置 `MIDTERM_DEMO_PORT=18727` |
| 保修／售后投诉返回无问题或无法判断 | 属于已知规则覆盖边界，不一定是程序运行失败；应查看原评论 |
| 构建下载失败 | 检查网络后重新构建 |
| Demo 服务不健康 | 查看 `midterm-demo` 容器日志，确认迁移和 API／AI 启动情况 |
| 英文评论返回无法判断 | 英文规则只覆盖部分表达，其他内容通常返回 unknown，但好评表达也可能导致无问题；应核对原文 |

停止或开始新一轮演示都会保留数据库记录。Demo 和原项目使用不同的数据卷。
删除卷、重置数据库属于开发维护，不是正常演示步骤。已经应用的迁移应通过新增迁移继续修改，
不要直接改历史；降级测试仅在可丢弃的测试数据库执行。
