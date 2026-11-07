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
This mode builds from source and creates its own database. Rule mode starts without a key;
model mode uses the configuration in section 7.
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
| `http://localhost:8100/docs` | Model/rule analysis API |
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
| Warranty/after-sales complaint returns no issue or unknown | Inspect source/reason to identify rule or model output, then check the original review; rule coverage and model interpretation can both be limited |
| Build downloads fail | Check network access and retry the build |
| Demo does not become healthy | Inspect `midterm-demo` container logs; confirm migration and API/AI startup |
| Unknown result for an English review | Check analysis source and original text; unknown is a saved result, and rule mode has limited phrase coverage |

Stopping or starting a new demo round keeps database records. The demo has its own volume;
the original project has a different volume. Deleting a volume or resetting a database is a developer
maintenance action, not part of a normal demonstration. Applied migrations should be followed by
new migrations rather than edited in place. Use downgrade tests only on disposable test databases.

### 7. AI configuration

`run_extraction()` supports three outcomes: configured rules, model output, and rule fallback
after an expected model-call failure. Configure these keys in the local `.env` at the repository
root. The gateway and model below are the course setup used in our local development.

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://hkust.azure-api.net/hkust-genai/v1
LLM_MODEL=gemini-2.5-flash-lite
LLM_API_KEY=YOUR_LOCAL_KEY
LLM_API_KEY_HEADER=api-key
LLM_TIMEOUT_SECONDS=8
LLM_PROMPT_VERSION=review-extraction-v1
```

Use `LLM_PROVIDER=heuristic` for local rule mode. `LLM_API_KEY` is a local credential;
keep it out of committed examples. These are supported settings in `config.py`; the current
`.env.example` does not yet list the `LLM_*` keys, so add them locally when enabling model mode.
The ordinary Compose passes `.env` into its services; the demo Compose passes these keys to the
controller, whose analysis child process inherits them.

After changing source or configuration, use the command for the running stack:

```powershell
# Ordinary project stack
docker compose up --build -d --wait --force-recreate ai api worker

# Standalone demo (Windows)
.\scripts\start_midterm_demo.ps1
```

For the demo on macOS/Linux, use
`docker compose -f compose.midterm.yaml up --build -d --wait --force-recreate midterm-demo`.
Stop and start a new round after restarting the demo.

| Setting or signal | Current behaviour |
| --- | --- |
| Source | `llm` for model output; `heuristic` for rules |
| Fallback | `fallback_reason` records errors such as `no_api_key`, `timeout`, `auth_error`, `rate_limited` or `schema_violation` |
| Persistence | Source/reason are saved in `AnalysisRun.output_json`, exposed by comment details and demo attempt history |
| Model timeout | Configurable, default 8 seconds; demo forwarding waits 15 seconds and its Worker waits 22 seconds, including the 3-second presentation delay |
| Logs | `llm_fallback` in AI logs; the demo log is `/tmp/midterm-ai.log` |

An expected model-call failure invokes rules and returns a successful analysis response when
fallback succeeds. Worker retries apply to errors reaching the Worker, including the demo's
injected HTTP 503s. A provider HTTP 429 currently triggers rule fallback.

For a configuration check, run the applicable command. Both print only provider, model and timeout:

```bash
docker compose exec ai python -c "from services.common.config import get_settings; s=get_settings(); print(s.llm_provider, s.llm_model, s.llm_timeout_seconds)"
docker compose -f compose.midterm.yaml exec midterm-demo python -c "from services.common.config import get_settings; s=get_settings(); print(s.llm_provider, s.llm_model, s.llm_timeout_seconds)"
```

Set `LLM_PROVIDER=heuristic` and recreate the demo before running its ten-case checker, which
asserts `rule-baseline-2`. Existing test counts describe earlier rule-mode runs. Dedicated mocked
adapter/fallback tests, review-write tests and a labelled model-evaluation set remain pending.

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
此模式从仓库源码构建并创建独立数据库，可与原项目同时运行。规则模式无需密钥，模型模式配置见第 7 节。

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
| `http://localhost:8100/docs` | 模型／规则分析 API |
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
| 保修／售后投诉返回无问题或无法判断 | 先看来源／回退原因判断当前路径，再核对原文；规则覆盖和模型理解都可能有局限 |
| 构建下载失败 | 检查网络后重新构建 |
| Demo 服务不健康 | 查看 `midterm-demo` 容器日志，确认迁移和 API／AI 启动情况 |
| 英文评论返回无法判断 | 检查分析来源和原文；unknown 是已保存结果，规则模式的表达覆盖有限 |

停止或开始新一轮演示都会保留数据库记录。Demo 和原项目使用不同的数据卷。
删除卷、重置数据库属于开发维护，不是正常演示步骤。已经应用的迁移应通过新增迁移继续修改，
不要直接改历史；降级测试仅在可丢弃的测试数据库执行。

### 7. 模型配置

`run_extraction()` 支持主动规则、模型输出和已分类模型故障后的规则回退。
在仓库根目录的本地 `.env` 中配置以下键；地址和模型为本地开发使用的课程配置。

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://hkust.azure-api.net/hkust-genai/v1
LLM_MODEL=gemini-2.5-flash-lite
LLM_API_KEY=YOUR_LOCAL_KEY
LLM_API_KEY_HEADER=api-key
LLM_TIMEOUT_SECONDS=8
LLM_PROMPT_VERSION=review-extraction-v1
```

本地规则模式设置 `LLM_PROVIDER=heuristic`。`LLM_API_KEY` 是本地凭据，提交的示例中应留空。
这些配置已由 `config.py` 支持；当前 `.env.example` 尚未列出 `LLM_*`，启用模型时需在本地添加。
普通 Compose 通过 `.env` 向服务传值；Demo Compose 将这些键传给控制器，分析子进程继承配置。

修改源码或配置后，按正在使用的模式执行：

```powershell
# 普通项目服务
docker compose up --build -d --wait --force-recreate ai api worker

# 独立 Demo（Windows）
.\scripts\start_midterm_demo.ps1
```

macOS/Linux 的 Demo 使用
`docker compose -f compose.midterm.yaml up --build -d --wait --force-recreate midterm-demo`。
Demo 重启后重新提交一轮评论。

| 配置或信号 | 当前行为 |
| --- | --- |
| 来源 | 模型结果为 `llm`，规则结果为 `heuristic` |
| 回退 | `fallback_reason` 保存 `no_api_key`、`timeout`、`auth_error`、`rate_limited`、`schema_violation` 等原因 |
| 保存 | 来源和原因存入 `AnalysisRun.output_json`，由评论详情和 Demo 尝试记录展示 |
| 模型超时 | 可配置，默认 8 秒；Demo 转发等待 15 秒，Worker 等待 22 秒，其中包含 3 秒演示延迟 |
| 日志 | AI 日志中的 `llm_fallback`；Demo 日志位于 `/tmp/midterm-ai.log` |

已分类模型故障触发规则，回退成功后返回有效分析响应。只有继续传到 Worker 的错误才进入任务重试，
例如 Demo 注入的 HTTP 503。提供方返回 HTTP 429 时，当前处理为规则回退。

按运行模式选一条命令检查配置，输出仅含提供方、模型名和超时：

```bash
docker compose exec ai python -c "from services.common.config import get_settings; s=get_settings(); print(s.llm_provider, s.llm_model, s.llm_timeout_seconds)"
docker compose -f compose.midterm.yaml exec midterm-demo python -c "from services.common.config import get_settings; s=get_settings(); print(s.llm_provider, s.llm_model, s.llm_timeout_seconds)"
```

十例 Demo 检查会断言 `rule-baseline-2`，运行前设置 `LLM_PROVIDER=heuristic` 并重建 Demo。
已有测试数字对应较早的规则模式运行；专门的适配器／回退模拟测试、审核写入测试和模型标注评测集仍待补充。
