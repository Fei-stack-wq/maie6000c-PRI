# Integration verification / 整合验证

## English

Date: 26 November 2026. Branch: `integrate_v1`. Sources: local frontend/model commit `b711f33`, semantic grouping `d3d0671`, human review `4c25ec7`. Local merges and fixes only; no push or remote CI claim.

| Check | Actual result |
| --- | --- |
| Python unit/integration | 446 passed against a separate PostgreSQL 16 database, including concurrency and 16 key-free retry tests |
| Frontend | 12 Node tests passed; all active JavaScript parsed successfully |
| Code quality | Ruff and Git whitespace checks passed |
| Database | Upgrade to 20261121_0006, downgrade to the initial revision, upgrade again, and alembic check passed in the isolated database |
| Real semantic model | MiniLM sentence_transformers backend loaded successfully; 3 HTTP/Worker/PostgreSQL grouping smoke tests passed |
| Authenticated workflow | One live reviewer/viewer test passed: login, idempotent CSV import, acceptance, confirm/follow-up/resolve/reopen, manual evidence, changed-source recheck, viewer write denial |
| Browser | Uploaded 10 CSV rows; all completed. Accepted an association, confirmed its issue and reloaded; decisions and notes persisted |
| Independent demo | All 10 Chinese/English normal/no/unknown/retry/final-failure cases passed, with evidence, database and metrics assertions |

One merge regression was caught before completion: Worker category-lock calls did not match human regrouping's shared ordering. The integrated code prepares remote hints before write locks, acquires category locks once in a shared sorted order, then preserves human decisions and advances review versions. The full concurrency suite passed after the fix.

The model has at most three extraction attempts; network failure, 429 and malformed JSON were simulated without provider charges. Tests cover success on attempt three, exhausted fallback, and persisted llm_attempts=3 while Job.attempts remains 1. Missing Key makes zero provider calls. These controlled tests do not measure unrestricted model accuracy or promise every outage will recover.

The original database was backed up outside the repository before the default stack upgrade. Test stacks used separate databases; no global cleanup or volume deletion was used. Historical completed reviews are not automatically regrouped. Grouping failure can still use the category baseline; the extractor still permits one issue per category per review.

## 中文

日期：2026 年 11 月 26 日；分支：`integrate_v1`。来源为本地前端／模型提交 `b711f33`、语义归组 `d3d0671`、人工复核 `4c25ec7`。仅本地合并和修正，不表示已推送或运行远端 CI。

| 检查 | 实际结果 |
| --- | --- |
| Python 单元／集成 | 独立 PostgreSQL 16 中 446 项通过，包含并发及 16 项无密钥重试测试 |
| 前端 | 12 项 Node 测试通过；活动 JavaScript 语法检查通过 |
| 代码检查 | Ruff 和 Git 空白检查通过 |
| 数据库 | 隔离库升级到 20261121_0006、降回初始版本、再次升级及 alembic check 均通过 |
| 真实语义模型 | MiniLM sentence_transformers 后端成功加载；3 项真实 HTTP／Worker／数据库归组冒烟测试通过 |
| 账号流程 | 1 项具名复核员／只读成员验收通过：登录、幂等导入、接受、确认／跟进／解决／重开、人工证据、原文变化重核、只读禁止写入 |
| 浏览器 | 上传 10 条 CSV 并全部完成；接受关联、确认问题、刷新后决定与备注仍保留 |
| 独立 Demo | 10 项中英文正常／无问题／未知／重试／最终失败场景通过，验证证据、数据库和运行指标 |

合并检查捕获过一个问题：Worker 的类别锁调用方式与人工改归组的共享锁顺序不一致。现已在写锁之前准备远程建议，一次性按共享顺序获取类别锁，保留人工决定并推进复核版本。修正后完整并发测试通过。

模型最多尝试三次；网络故障、429 和错误 JSON 使用模拟提供方响应验证，没有调用收费模型。覆盖第三次成功、耗尽后回退，以及 llm_attempts=3 而 Job.attempts 仍为 1 的保存情况。缺少 Key 时不发送提供方请求。这些控制测试不代表不受限评论准确率，也不保证所有故障都能恢复。

默认数据库升级前已在仓库外备份。测试使用独立数据库，未进行全局清理或删除数据卷。已完成的历史评论不会自动重新归组；归组失败仍可能使用类别基线；提取器每条评论每个类别仍最多一个问题。
