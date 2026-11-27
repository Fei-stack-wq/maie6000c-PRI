# ADR 002: Use a separate Worker with PostgreSQL-backed jobs

## Status

Accepted. This record documents an implemented decision.
Recorded on 2026-11-27.

## Context

AI requests can be slow, time out or fail. An upload should not remain open while every review
is analyzed. Unfinished work must remain discoverable after a process restart, and retries
must not allow stale results to overwrite newer state.

## Decision

Save jobs in PostgreSQL in the same transaction as the imported batch and comments.
Run a separate polling Worker to claim jobs, call the AI service and persist analysis results.

Track claim time, attempts and lease expiry. Commit the claim before making remote calls;
check claim ownership and lease validity before saving the result. Use bounded retries and
expired-claim recovery. Coordinate batch stop and result saving through the batch lock.

A database queue keeps task creation atomic with ingestion and avoids another queue service
in the local deployment. It provides retryable processing, not exactly-once external AI calls.

## Alternatives considered

- **Analyze inside the upload request:** fewer moving parts, but longer requests and greater
  coupling between import availability and model latency.
- **In-memory background tasks:** simple to start, but process restarts lose task state unless
  a durable recovery mechanism is added.
- **Celery with Redis or RabbitMQ:** richer queue operations, but adds a broker, configuration
  and coordination between database writes and message publication.

## Consequences

- Uploads can return after validation and persistence while analysis proceeds independently.
- Persisted jobs, attempts and errors support recovery and operational inspection.
- Polling and locking add database load; shared batch/category locks can limit concurrency.
- A crash after a provider call may cause another call and additional cost. Guarded database
  writes do not make the external request exactly-once.
- A dedicated broker should be reconsidered if measured throughput or operational needs
  outgrow the current design.

## 中文摘要

选择独立 Worker 轮询 PostgreSQL 任务表，导入和建任务在同一事务内完成。
通过领取身份、租约、有限重试及过期恢复管理任务，并在保存时阻止迟到结果覆盖。
相比请求内分析或内存任务，该方案支持异步处理和持久化恢复；相比独立消息队列，
减少了部署组件。代价是轮询和锁开销，且外部 AI 调用仍可能重复。

## References

- [Ingestion](../../services/api/app/ingestion.py)
- [Worker orchestration](../../services/worker/app/main.py)
- [Job lifecycle](../../services/worker/app/jobs.py)
- [Retry policy](../../services/worker/app/policy.py)

