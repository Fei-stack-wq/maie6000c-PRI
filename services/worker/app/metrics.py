"""Bounded-label worker metrics; the HTTP server starts only with the worker."""
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.common.models import Job

JOB_EVENTS = Counter("worker_job_events_total", "Worker lifecycle events", ["event"])
AI_LATENCY = Histogram(
    "worker_attempt_duration_seconds",
    "Analysis attempt duration including persistence",
)
JOB_STATES = Gauge("worker_jobs", "Current jobs by state", ["status"])
LAST_POLL = Gauge("worker_last_poll_timestamp_seconds", "Last successful database poll")


def update_queue_metrics(db: Session) -> None:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    for status in ("pending", "claimed", "completed", "failed"):
        JOB_STATES.labels(status).set(counts.get(status, 0))
    LAST_POLL.set_to_current_time()
