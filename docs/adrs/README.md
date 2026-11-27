# Architecture Decision Records / 架构决策记录

These short records explain the choices implemented in the product review system.
They complement [architecture](../architecture.md) and [operations](../operations.md).

这些简短记录解释商品评论系统中已实现的技术选择，补充架构与运行文档。

## Review status / 审阅状态

Drafted on 2026-11-27 against main commit
`d996daa62aa225233e101ff8091fc3e5a0a35ba1`.
The architecture choices are implemented; these retrospective records are accepted for inclusion.
Alternatives are documented as technical comparisons, not as a claim that the team benchmarked
or formally discussed every option.

基于上述 main 提交于 2026-11-27 起草。技术选择已有实现，事后补充的决策记录已确认纳入仓库。
替代方案属于技术比较，不表示团队已经对所有方案做过基准测试或正式讨论。

## Index / 索引

| Record | Decision / 决策 |
| --- | --- |
| [ADR 001](001-database-choice.md) | PostgreSQL for persistent relational data / PostgreSQL 关系型持久化 |
| [ADR 002](002-background-processing.md) | A separate Worker with PostgreSQL-backed jobs / 独立 Worker 与数据库任务队列 |
| [ADR 003](003-ai-integration.md) | Hosted extraction, local semantic grouping and evidence-based review / 外部模型提取、本地语义归组与证据复核 |
| [ADR 004](004-local-deployment.md) | Docker Compose for local deployment / Docker Compose 本地部署 |

These records explain design decisions; they do not certify release readiness or fix defects.
Verification scope and known limitations remain in the
[final milestone](../../templates/submissions/week13/README.md).

这些记录说明设计决策，不代表最终版本已经验收或缺陷已修复。
验证范围及已知限制见最终里程碑文档。

