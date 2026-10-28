"""Worker Prometheus metrics (R2). Exposed via a lightweight HTTP port."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

WORKER_JOBS_CLAIMED = Counter(
    "worker_jobs_claimed_total",
    "Jobs claimed by this worker process",
)
WORKER_JOBS_COMPLETED = Counter(
    "worker_jobs_completed_total",
    "Jobs completed successfully",
)
WORKER_JOBS_FAILED = Counter(
    "worker_jobs_failed_total",
    "Jobs that reached terminal failed",
    ["error_code"],
)
WORKER_JOBS_REQUEUED = Counter(
    "worker_jobs_requeued_total",
    "Jobs automatically requeued after a retryable failure",
    ["error_code"],
)
WORKER_QUEUE_DEPTH = Gauge(
    "worker_queue_depth",
    "Pending jobs ready to claim (next_attempt_at due or null)",
)
WORKER_AI_LATENCY = Histogram(
    "worker_ai_request_duration_seconds",
    "Latency of AI /extract-issues calls from the worker",
)
WORKER_EVIDENCE_MISS = Counter(
    "worker_evidence_locate_failures_total",
    "AI issues dropped because evidence was not a body substring",
)

_METRICS_STARTED = False


def start_metrics_server(port: int = 8200) -> None:
    global _METRICS_STARTED
    if _METRICS_STARTED:
        return
    start_http_server(port)
    _METRICS_STARTED = True
