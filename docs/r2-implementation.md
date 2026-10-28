# R2 后台任务实现与验证

本次实现保留现有数据库结构、HTTP AI 契约和用户查询接口，工作位于本地
`feature/r2-worker` 分支。没有合并 main、推送或新增数据库迁移。

## 1. 文件与调用关系

`main.run_worker → run_once → jobs.recover_stale_jobs → jobs.claim_next_pending_job`
随后 `process_job → jobs.load_input_for_claim → analysis.call_ai_service →
validate_ai_result → verify_evidence → jobs.complete_job`。

异常分支：
`policy.classify_error → jobs.handle_job_failure → policy.should_retry /
calculate_retry_delay`。

| 文件 | 职责 |
| --- | --- |
| services/worker/app/main.py | 编排一次任务、持续轮询、外层异常保护、SIGTERM/SIGINT 正常退出 |
| services/worker/app/jobs.py | 行锁领取、原始 JobClaim、受保护的事务保存、重试、回收、人工判断保护 |
| services/worker/app/analysis.py | 固定输入快照、HTTP 调用、编号/版本/类别检查、原文证据定位 |
| services/worker/app/policy.py | 错误分类、是否重试、1/5/25…倍等待（有上限）、安全错误摘要 |
| services/worker/app/settings.py | Worker 专用配置；公共服务地址和 HTTP 超时沿用 common.config |
| services/worker/app/metrics.py | 有界标签的事件计数、处理耗时、任务状态和最近成功轮询时间 |
| scripts/recover_stale_jobs.py | 复用同一回收逻辑的手工巡检入口 |

## 2. 状态与次数

- Job：等待执行/重试为 pending，正在执行为 claimed，最终成功为 completed，
  最终失败为 failed。
- Comment：分别为 queued、analyzing、analyzed、failed。
- attempts 只在一次真正领取时增加；回收不增加。max_attempts=3 表示总共最多三次，
  包括首次执行。
- 自动重试直接把 Job 放回 pending 并设置 next_attempt_at；本次失败单独写
  analysis_runs(status=failed)。下一次领取前保留错误摘要。
- AI 无问题(no)和无法判断(unknown)都属于有效分析结果，不作为系统失败。
- 证据无法在原文定位时丢弃对应关联，结果降为 unknown，并记录警告；
  不把找不到的证据写成已验证。
- 类别归组仍为同平台、同店铺、同商品、同类别的基础规则，不是语义归组。

## 3. 重试与故障处理

| 情况 | 行为 |
| --- | --- |
| 超时、连接错误、HTTP 429/5xx | 未达 Job 上限时等待后重试 |
| 其他 HTTP 4xx | 最终失败，不反复调用 |
| 输出格式、编号、类别或版本错误 | 最多一次自动重试，仍受 Job 总次数限制 |
| 临时数据库连接/操作故障 | 能记录时安排重试；记录也失败时保留 claimed 等待租约回收 |
| 数据库约束错误、未分类程序错误 | 停止自动重试，记录安全错误摘要 |
| Worker 被强制关闭 | 租约到期后回收；达到次数上限时最终失败 |
| 正常 SIGTERM/SIGINT | 不再领取新任务，当前有限时 HTTP 调用结束后退出 |

处理期限应大于 HTTP 超时。默认值为 600 秒与 20 秒。
没有收到模型信息的失败记录明确标 unknown，不伪造模型版本。
进程被强制结束/数据库持续不可用时，不能保证写入该次 AI 调用记录；任务仍可回收。

## 4. 数据正确性

- 每次领取返回不可变 JobClaim(id, comment_id, claimed_at, attempts)。
  process_job 必须接收这份原始凭据，不再接受裸 Job ID。
- 成功和失败写入均在事务中锁住任务并核对状态、领取时间、次数和租约，
  过期凭据不允许改写新任务。
- HTTP 调用期间不持有数据库事务锁。
- 回来保存时重新锁住评论，检查正文、来源和 revision 标记。
  输入变化时旧结果不成为当前结果，新正文重新排队并获得新的尝试预算。
- R1 评论更新查询补充行锁，确保更新与后台保存按顺序执行。
  如果更新后 Worker 强制退出，回收时识别 R1 的 queued 标记并重新安排新输入。
- 成功结果、分析记录、问题关联和完成状态同事务提交；任一步失败全部回滚。
- PostgreSQL 按平台/店铺/商品/类别取得 advisory lock，防止并发重复建组；
  多类别按固定顺序加锁。
- 人工 accepted/rejected、origin=human 或已写人工决定的关联不被 AI 覆盖。
  已失效 AI 建议保留 superseded_at 历史，不再计入当前建议数。
- R4 后续人工写接口应对同一 CommentIssue 使用行锁或原子条件更新；
  已测试并发人工提交与后台重跑的保护。

## 5. 查询与运行信号

现有 GET /jobs/{id}、评论/问题组/批次接口可继续使用，不新增前端依赖。
问题组和汇总计数增加 superseded_at 过滤，避免重跑后计入过期建议。

Worker 在容器内 8200 提供 Prometheus 指标：
worker_job_events_total、worker_attempt_duration_seconds、
worker_jobs、worker_last_poll_timestamp_seconds。

Compose 增加 Worker 指标服务存活检查，Prometheus 增加 worker:8200 采集。
指标服务存活不等于数据库就绪，应结合最近成功轮询时间判断。
未额外暴露宿主机 Worker 端口。

配置（可在 .env 中设置）：

| 环境变量 | 默认 |
| --- | ---: |
| WORKER_LEASE_SECONDS | 600 |
| WORKER_RETRY_BASE_SECONDS | 60 |
| WORKER_RETRY_MAX_SECONDS | 900 |
| WORKER_RECOVERY_LIMIT | 100 |
| WORKER_METRICS_PORT | 8200 |
| WORKER_POLL_SECONDS（原公共配置） | 2 |
| WORKER_REQUEST_TIMEOUT_SECONDS（原公共配置） | 20 |

更换指标端口时，Compose 健康检查和 Prometheus 目标需同步修改。

## 6. 测试与复现

Windows 一键验证（先启动 Docker Desktop，在仓库根目录执行）：
` .\scripts\test_r2.ps1 `

脚本使用随机命名的临时容器和独立测试库，源码只读挂载；自动执行静态检查、58项测试、迁移往返、5项真实HTTP测试，并在结束时清理自己创建的资源。首次需要下载依赖。`-SkipLive` 可跳过真实服务测试。

单元与集成：
`python -m pytest -q tests/unit tests/integration`

真实 PostgreSQL 并发测试通过 WORKER_TEST_DATABASE_URL 启用；
只接受数据库名以 _test 结尾的独立测试库。每个测试新建随机 schema，结束后删除
该测试 schema，不使用业务 schema。没有该变量时，这些测试明确跳过。
CI 已配置独立 *_test 数据库并启用这些测试。

真实服务/故障测试：
在装好测试依赖的隔离 Linux 环境中，将同一个临时测试库迁移到 head，
设置 WORKER_TEST_DATABASE_URL 后运行：
`python tests/support/run_worker_live.py`。
它启动临时 API、Worker、真实规则 AI 服务及仅供测试的 HTTP 故障代理。
不应用于已有正在运行的应用环境；端口 18000、18100、18200、8200 必须空闲。
正常响应来自真实 AI HTTP 服务，故障代理只注入一次/持续 HTTP 503。
结束后关闭全部启动的服务，并检查 Worker 正常退出。

迁移仍使用现有 Alembic 链；不要为了测试在业务库执行 downgrade。

## 7. 本次验证记录（2026-10-29）

- Python 3.11.16，PostgreSQL 16，源码只读挂载到临时测试容器。
- unit + integration：58 passed，含 6 项真实 PostgreSQL 测试。
- 真实 HTTP smoke：5 passed（包含原有 smoke）。
- 真实迁移：upgrade head → downgrade 20260713_0001 → upgrade head 通过。
- 正常 Worker 退出：验证通过。
- Windows 一键脚本：已从头完整执行，检查全部通过，临时资源自动清理。
- R2 语句覆盖率：92%（unit + integration；独立服务进程未计入此覆盖率）。
- Compose 配置：使用现有 Compose 可执行程序和示例环境文件验证通过；本机默认 docker compose 命令暂未发现插件，未修改系统设置。
- 已有 categories.py 行长问题仅作换行修复，不改变类别内容。
- 两条已有依赖库弃用警告仍存在，不影响测试结果。

## 8. 当前边界

本次完成 R2 核心可靠性。人工 retry/recover API、持久化的人工任务操作审计、
批量手工重放工具作为后续扩展，当前没有对外宣称这些接口已存在。
脚本 recover_stale_jobs 可通过
`python -m scripts.recover_stale_jobs` 执行已有过期回收，不重置最终失败任务。

真实平台数据、LLM 与语义归组、前端真实接口连接仍分别由对应模块继续完成。
目前不能把规则分析或静态界面描述为已完成的大模型产品。
