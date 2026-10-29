# R2 Implementation / R2 实现说明

## English

### 1. Files and processing order

`main.run_worker()` loops through `run_once()`: recover expired work, update metrics, claim a due
job, then call `process_job(claim)`. The original `JobClaim` is retained throughout the attempt.

| File under `services/worker/app/` | Role |
| --- | --- |
| `main.py` | Processing order, polling, error boundary and shutdown |
| `jobs.py` | Claim ownership, transactional saving, recovery and state changes |
| `analysis.py` | Input snapshot, HTTP call, output and evidence validation |
| `policy.py` | Error classification and retry decisions |
| `settings.py` | Worker settings |
| `metrics.py` | Event counts, attempt duration, job counts and last poll |

The R1 update path locks existing comments; query counts exclude superseded AI suggestions.
The database schema and AI HTTP response format remain unchanged.

### 2. Success and data protection

A claim changes job/comment states to `claimed`/`analyzing` and increments attempts once.
Worker reads a fixed input snapshot, closes the database session, then sends HTTP outside the lock.
It validates the response ID, schema/category versions and categories, and locates evidence in the
same input. Unlocated issues are discarded and the verdict becomes `unknown`.

On completion, a transaction checks job ownership and input again. If the claim is old, it cannot
write. If text changed, the old result is recorded as discarded/failed with `input_changed`, and the
current input gets a new budget. Otherwise the analysis, issue links, comment result and completed
job commit together. Exceptions roll back partial writes.

Groups currently use platform/shop/product/category, with PostgreSQL advisory locks to avoid
concurrent duplicate groups. This is a category baseline, not semantic grouping.
Unreviewed AI suggestions can be replaced; accepted/rejected, human-created or decided links
are preserved. Old superseded suggestions are not counted as current suggestions.

### 3. Retry and recovery

| Failure | Behaviour |
| --- | --- |
| Timeout, connection failure, HTTP 429/5xx | Retry while the job has attempts remaining |
| Other HTTP 4xx | Final failure |
| Invalid JSON, ID, category or output version | At most one retry, within the total limit |
| Transient database failure | Retry if the outcome can be recorded; otherwise wait for claim expiry |
| Constraint or unexpected program error | Final failure with a short error summary |
| Forced process termination | Recover the expired claim; final failure if the budget is exhausted |

Retries return to `pending`/`queued` with `next_attempt_at`. Default total attempts are three,
including the first. Recovery does not add an attempt. A new claim invalidates the old one for both
success and failure writes. If R1 updated a comment during an interrupted claim, recovery preserves
the new input's chance to run. Normal SIGTERM/SIGINT stops further claims and finishes the current
bounded attempt. A database outage or forced kill may prevent saving the attempt record.

### 4. Settings and metrics

| Environment setting | Full-project default | Midterm override |
| --- | ---: | ---: |
| `WORKER_LEASE_SECONDS` | 600 | 60 |
| `WORKER_RETRY_BASE_SECONDS` | 60 | 3 |
| `WORKER_RETRY_MAX_SECONDS` | 900 | 6 |
| `WORKER_RECOVERY_LIMIT` | 100 | 100 |
| `WORKER_METRICS_PORT` | 8200 | 8200 |
| `WORKER_POLL_SECONDS` | 2 | 0.3 |
| `WORKER_REQUEST_TIMEOUT_SECONDS` | 20 | 10 |

Default retry waits before the second and third attempts are 60 and 300 seconds; the demo uses
3 and 6 seconds. The lease must exceed the HTTP timeout. Metrics and log commands are in
[Operations](operations.md); port 8200 is internal in both configurations.

### 5. Verification and remaining work

The recorded R2 run passed 94 unit/integration tests, including six real PostgreSQL tests, and
five real HTTP smoke tests. Statement coverage was 92%. Migration round-trips and graceful
shutdown passed. These measure implementation behaviour, not analysis accuracy.
Reproduce with ` .\scripts\test_r2.ps1 `; details and conditions are in the
[verification record](../templates/submissions/week07/assets/verification.md).

Manual retry/recover APIs, persistent manual job-operation audit and batch replay remain unimplemented.
`python -m scripts.recover_stale_jobs` only recovers expired/exhausted active work under the existing
rules; it does not restart terminal failed jobs. R4 must protect concurrent review writes when its
write endpoints are added. LLM and semantic grouping belong to the remaining analysis work.

## 中文

### 1. 文件与执行顺序

`main.run_worker()` 持续执行 `run_once()`：回收过期任务、更新指标、领取到期任务，
再调用 `process_job(claim)`，整次执行保留原始 `JobClaim`。

| `services/worker/app/` 下的文件 | 作用 |
| --- | --- |
| `main.py` | 处理顺序、轮询、异常边界和退出 |
| `jobs.py` | 领取归属、事务保存、回收和状态变化 |
| `analysis.py` | 输入快照、HTTP 调用、输出和证据检查 |
| `policy.py` | 错误分类与重试判断 |
| `settings.py` | Worker 配置 |
| `metrics.py` | 事件次数、尝试耗时、任务数和最近轮询 |

R1 更新已有评论时增加行锁，查询计数排除已失效 AI 建议。
数据库结构和 AI HTTP 返回格式保持不变。

### 2. 成功处理与数据保护

领取时任务／评论改为 `claimed`／`analyzing`，尝试次数加一。
Worker 读取固定输入后结束数据库会话，在不持锁的情况下发送 HTTP。
检查回复编号、格式／类别版本和类别，再在同一输入中定位证据；找不到证据的问题丢弃，
判断降为 `unknown`。

完成时在事务中再次检查任务归属和输入。旧领取不能写入；正文变化时，以 `input_changed`
保存旧结果被丢弃／失败的记录，再为当前输入重新分配预算。
输入未变时，分析、问题关联、评论结果和任务完成一起提交；中间异常回滚部分写入。

当前按平台／店铺／商品／类别归组，使用 PostgreSQL advisory lock 防止并发重复建组，
这仍是类别基线，不是语义归组。未经人工处理的 AI 建议可以更新；已接受、已拒绝、
人工建立或已有决定信息的关联保留，失效建议不计入当前建议数。

### 3. 重试与回收

| 失败 | 处理方式 |
| --- | --- |
| 超时、连接错误、HTTP 429／5xx | 次数未用尽时重试 |
| 其他 HTTP 4xx | 最终失败 |
| JSON、编号、类别或输出版本错误 | 总次数范围内最多重试一次 |
| 临时数据库故障 | 能保存决定时重试，否则等待领取到期 |
| 约束错误或未分类程序错误 | 最终失败，保存简短错误摘要 |
| 进程强制结束 | 回收过期领取；预算用尽时最终失败 |

重试回到 `pending`／`queued` 并写 `next_attempt_at`，默认总共最多三次，包含首次。
回收不增加次数。重新领取使旧执行的成功和失败写入都失效。
R1 在中断期间更新正文时，回收保留新输入的执行机会。
正常 SIGTERM／SIGINT 不再领取新任务，完成当前有限时尝试后退出。
数据库中断或强制结束时，可能无法保存该次分析记录。

### 4. 配置与指标

| 环境变量 | 原项目默认值 | 期中 Demo 值 |
| --- | ---: | ---: |
| `WORKER_LEASE_SECONDS` | 600 | 60 |
| `WORKER_RETRY_BASE_SECONDS` | 60 | 3 |
| `WORKER_RETRY_MAX_SECONDS` | 900 | 6 |
| `WORKER_RECOVERY_LIMIT` | 100 | 100 |
| `WORKER_METRICS_PORT` | 8200 | 8200 |
| `WORKER_POLL_SECONDS` | 2 | 0.3 |
| `WORKER_REQUEST_TIMEOUT_SECONDS` | 20 | 10 |

默认第二、三次执行前分别等待 60、300 秒；Demo 为 3、6 秒。
租约必须长于 HTTP 超时。指标和日志命令见 [运行说明](operations.md)，两种配置中的 8200 都是内部端口。

### 5. 验证与待完成项

已有 R2 验证记录为 94 项单元／集成（含六项真实 PostgreSQL）和 5 项真实 HTTP 冒烟通过，
语句覆盖率为 92%，迁移往返和正常退出通过。这些检查实现行为，不表示分析准确率。
使用 ` .\scripts\test_r2.ps1 ` 复现，条件见
[验证记录](../templates/submissions/week07/assets/verification.md)。

人工 retry/recover API、持久化人工任务操作审计和批量重放尚未实现。
`python -m scripts.recover_stale_jobs` 只按现有规则处理过期／次数用尽的活跃任务，
不会重新执行最终失败任务。R4 加入写接口时仍需保护并发人工决定；大模型和语义归组属于后续分析工作。
