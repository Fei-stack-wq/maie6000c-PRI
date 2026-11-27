# ADR 004: Use Docker Compose for local deployment

## Status

Accepted. This record documents an implemented decision.
Recorded on 2026-11-27.

## Context

The product requires PostgreSQL, API, Worker and AI processes, with consistent addresses and
configuration across team machines. A final demonstration needs a documented way to build,
start, inspect and stop these services while retaining database state.

## Decision

Define the local stack in Docker Compose with separate database, API, Worker and AI services.
Serve the frontend from the API. Use a named PostgreSQL volume, service health checks and
dependency ordering. Provide a PowerShell launcher that creates a missing `.env` from the
example and uses the `maie6000c-pri` Compose project.

Build the CPU grouping model into the AI image. Run migrations and the legacy grouping repair
before API startup. Keep Prometheus optional through the observability profile.

Compose fits a single-machine course demonstration while preserving service boundaries.
It is the local deployment mechanism, not a high-availability production platform.

## Alternatives considered

- **Manual host setup:** avoids containers, but requires each machine to reproduce database,
  Python, model dependencies, ports and process startup consistently.
- **A single application container:** simplifies the apparent entry point, but complicates
  process supervision and couples service lifecycle and failure handling.
- **Kubernetes:** supports richer orchestration, but adds cluster and configuration complexity
  beyond the current single-machine deployment requirement.

## Consequences

- One Compose definition describes service networking, configuration and persistent storage.
- Health-based dependencies improve startup ordering, but a healthy process does not prove that
  a live provider call or the complete business workflow succeeds.
- Docker resources and initial network downloads are required; the AI image can be slow to build.
- Retaining the named volume preserves database state; deleting it removes that protection.
- Migration or legacy-repair failure prevents API startup. The known legacy-regrouping defect
  therefore remains a release concern.
- Containerization improves environment consistency but is not proof of exact build reproducibility:
  the current build also downloads dependencies and model weights. Clean-environment rehearsal
  and recorded verification are still required.

## 中文摘要

使用 Docker Compose 管理数据库、API、Worker 和 AI 服务，前端由 API 提供。
命名数据卷保留数据库，健康检查和依赖顺序辅助启动，PowerShell 脚本简化本地操作。
相比手工配置，环境更一致；相比 Kubernetes，更适合单机课程演示。
代价是 Docker 资源、首次构建和下载成本；健康检查不等于业务验证，
迁移或旧数据整理失败仍会阻断启动，最终仍需全新环境演练。

## References

- [Compose stack](../../compose.yaml)
- [Image build](../../Dockerfile)
- [Startup launcher](../../scripts/start_product_ui.ps1)
- [Operations](../operations.md)

