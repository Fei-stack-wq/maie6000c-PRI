# Integration verification / 整合验证

## English

Date: 27 November 2026. Local branch: `integrate_v1`. This record covers the batch lifecycle,
independent grouping and bilingual workbench update. Changes have not been pushed by this check.

| Check | Actual result |
| --- | --- |
| Python unit/integration | 474 passed, including PostgreSQL concurrency and stop/completion ordering |
| Frontend | 26 Node tests passed, covering complete catalogs, multi-scope routes, language and DELETE/CSRF |
| Code checks | Ruff, active JavaScript syntax and Git whitespace checks passed |
| Schema | Empty PostgreSQL upgrade to `20261126_0010`, downgrade to initial revision, upgrade again and `alembic check` passed |
| Existing-data migration | A restored copy of the existing 121 reviews upgraded from `0006` to `0010`; no cross-batch issue links remained |
| Legacy grouping | Local repair is idempotent and preserves human-reviewed groups; regression tests passed |
| Real model | Three isolated HTTP/Worker/database reviews completed: zipper fault and delivery delay auto-assigned; uncertain size complaint pending |
| Local deployment | Four services healthy; schema `0010` matches models. Original 121 comments, 121 jobs and 121 analysis runs preserved exactly; zero cross-batch links. Chinese/English pages verified at port 8000. |
| Browser | Batch/product multi-selection, dependent products, Chinese/English board, confirmation, trash/restore, stop/cancelled records and deletion-dialog cancellation checked |

The real model returned confidence 0.95 for each clear fault and 0.55 for the uncertain size
example, with one extraction attempt each. These are observed examples, not fixed outputs or an
accuracy benchmark. Controlled tests cover three attempts before fallback, malformed output,
missing configuration, stale claims, human correction and protection against late saves.

Test stacks used separate PostgreSQL databases. The original database was backed up outside the
repository. No original batch was deleted during browser checks. Old outputs missing confidence
remain pending; incomplete historical imports are flagged. Legacy repair changes only eligible
unreviewed groups using saved data. Evidence and original review text remain the basis for review.

## 中文

日期：2026 年 11 月 27 日；本地分支：`integrate_v1`。本记录覆盖批次管理、独立归组和
中英文工作台更新。本次检查没有推送修改。

| 检查 | 实际结果 |
| --- | --- |
| Python 单元／集成 | 474 项通过，包含 PostgreSQL 并发及停止与保存的先后顺序 |
| 前端 | 26 项 Node 测试通过，覆盖完整选项、多批次路由、语言及 DELETE／CSRF |
| 代码检查 | Ruff、活动 JavaScript 语法和 Git 空白检查通过 |
| 数据库 | 空 PostgreSQL 升至 `20261126_0010`、降回初始版本、再次升级及 `alembic check` 通过 |
| 旧数据迁移 | 原有 121 条评论的备份副本从 `0006` 升至 `0010`；没有跨批次问题关联 |
| 历史归组 | 本地整理重复执行不会再改写，保留人工复核过的组；回归测试通过 |
| 真实模型 | 独立环境中三条评论完成 HTTP／Worker／数据库全流程：拉链故障、物流延迟自动归组，不确定尺码待确认 |
| 本机升级 | 四个服务健康，数据库 `0010` 与模型一致。原有 121 条评论、121 个任务、121 条分析记录逐项比对未变，跨批次关联为零；8000 端口中英文页面验证通过。 |
| 浏览器 | 已检查批次／商品多选、商品联动、中英文分层页面、人工确认、回收站／恢复、停止／取消记录及取消永久删除弹窗 |

本次真实模型对两条明确问题分别返回 0.95 置信度，不确定尺码返回 0.55，均一次提取完成。
这些是实际观察样例，不是固定输出或准确率评测。控制测试覆盖三次尝试后回退、错误输出、
缺少配置、过期领取、人工修正和迟到结果拦截。

测试使用独立 PostgreSQL 数据库，原数据库备份保存在仓库外。浏览器检查没有删除任何原有批次。
旧输出没有置信度时继续待确认，旧版未保留完整的历史导入会显示提示。历史整理只根据保存数据
调整符合条件、未经人工复核的组；人工核查仍以原文及证据为依据。
