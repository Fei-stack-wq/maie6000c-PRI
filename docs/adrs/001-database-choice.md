# ADR 001: Use PostgreSQL for persistent relational data

## Status

Accepted. This record documents an implemented decision.
Recorded on 2026-11-27.

## Context

Batches, comments, analysis jobs, issue groups and review actions have related identities and
must survive application restarts. Importing a batch and creating its jobs should be atomic.
Concurrent API and Worker processes also require database transactions and explicit locking.

## Decision

Use PostgreSQL as the application database, SQLAlchemy for models and database access, and
Alembic for schema migrations. Store database files in a named Docker volume.

Keep source comments, model analysis runs and human review history as separate relational records.
Use foreign keys, uniqueness constraints and transactions to enforce the relevant data rules.
Comment identity includes its batch so a new upload request can preserve an independent snapshot.

This fits the existing relational queries and PostgreSQL row/advisory locking used by the Worker
and review operations. SQLite remains useful for fast tests, but does not replace PostgreSQL
concurrency validation.

## Alternatives considered

- **SQLite:** convenient for tests and lightweight local use; it would require a different
  concurrency approach for the current multi-process locking design.
- **MySQL:** a viable relational database, but switching would require adapting and revalidating
  PostgreSQL-specific locking and migrations without a demonstrated project need.
- **Files or a document store:** possible for simpler records, but atomic updates and the
  existing relationships would require more application-level consistency logic.

## Consequences

- Related records and task creation can be committed atomically.
- Persisted state survives container replacement while the database volume is retained.
- The database is an additional service to start, migrate, back up and maintain.
- Independent upload snapshots consume extra storage and may repeat analysis.
- SQLite test success does not establish PostgreSQL locking behavior; database-specific tests
  remain necessary.

## 中文摘要

选择 PostgreSQL 保存批次、评论、任务、问题组及复核历史，配合 SQLAlchemy 和 Alembic。
原因是数据关系明确，需要事务、约束、并发控制及重启后持久化。
SQLite 适合快速测试，MySQL 也可行，但当前锁和迁移实现依赖 PostgreSQL。
代价是增加数据库运维责任、独立快照存储及 PostgreSQL 专项测试需求。

## References

- [Models](../../services/common/models.py)
- [Database access](../../services/common/db.py)
- [Migrations](../../alembic/versions/)
- [Compose database and volume](../../compose.yaml)

