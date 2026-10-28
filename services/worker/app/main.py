"""R2 entry point: one bounded attempt at a time, no database lock across AI HTTP."""
import logging
import signal
import threading
from time import perf_counter

from prometheus_client import start_http_server
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_session_factory
from services.worker.app import analysis, jobs
from services.worker.app.jobs import JobClaim
from services.worker.app.metrics import AI_LATENCY, JOB_EVENTS, update_queue_metrics
from services.worker.app.policy import classify_error
from services.worker.app.settings import get_worker_settings

configure_logging()
logger = logging.getLogger("services.worker.main")


def claim_next_pending_job(db: Session) -> JobClaim | None:
    """Return the original claim, not just an ID; callers must retain it."""
    return jobs.claim_next_pending_job(db, get_worker_settings())


def recover_stale_jobs() -> int:
    with get_session_factory()() as db:
        return jobs.recover_stale_jobs(db, get_worker_settings())


def process_job(claim: JobClaim) -> str:
    """Run and record one attempt; database failures remain recoverable by lease."""
    if not isinstance(claim, JobClaim):
        raise TypeError("process_job requires the original JobClaim, not a job ID")
    factory = get_session_factory()
    snapshot = None
    started = perf_counter()
    outcome = "stale"
    try:
        with factory() as db:
            snapshot = jobs.load_input_for_claim(db, claim)
        if snapshot is None:
            return outcome
        shared = get_settings()
        raw, latency_ms = analysis.call_ai_service(
            snapshot, shared.ai_service_url, shared.worker_request_timeout_seconds,
        )
        result = analysis.validate_ai_result(raw, snapshot)
        verified = analysis.verify_evidence(result, snapshot)
        if verified.invalid_evidence_count:
            JOB_EVENTS.labels("invalid_evidence").inc(verified.invalid_evidence_count)
            logger.warning("evidence_not_located", extra={
                "job_id": claim.id, "comment_id": claim.comment_id,
                "count": verified.invalid_evidence_count,
            })
        with factory() as db:
            outcome = jobs.complete_job(db, claim, snapshot, verified, latency_ms)
    except Exception as exc:  # noqa: BLE001 - attempt boundary
        failure = classify_error(exc)
        logger.warning("job_attempt_failed", extra={
            "job_id": claim.id, "comment_id": claim.comment_id,
            "error_code": failure.code, "exception_type": type(exc).__name__,
        })
        try:
            with factory() as db:
                outcome = jobs.handle_job_failure(
                    db, claim, snapshot, failure, get_worker_settings(),
                    max(0, round((perf_counter() - started) * 1000)),
                )
        except Exception as recording_exc:  # noqa: BLE001 - DB may still be unavailable
            outcome = "recording_failed"
            logger.error("job_failure_recording_unavailable", extra={
                "job_id": claim.id, "exception_type": type(recording_exc).__name__,
            })
    finally:
        if snapshot is not None:
            AI_LATENCY.observe(perf_counter() - started)
        JOB_EVENTS.labels(outcome).inc()
        logger.info("job_attempt_finished", extra={
            "job_id": claim.id, "comment_id": claim.comment_id,
            "attempt": claim.attempts, "outcome": outcome,
        })
    return outcome


def run_once() -> str:
    recover_stale_jobs()
    with get_session_factory()() as db:
        update_queue_metrics(db)
        claim = claim_next_pending_job(db)
    return process_job(claim) if claim else "idle"


def run_worker(stop_event: threading.Event | None = None, serve_metrics: bool = True) -> None:
    shared = get_settings()
    worker = get_worker_settings()
    if worker.lease_seconds <= shared.worker_request_timeout_seconds:
        raise ValueError("Worker lease must exceed the AI request timeout")
    stop = stop_event if stop_event is not None else threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def request_stop(signum, frame):
            stop.set()
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, request_stop)
    metrics_server = None
    try:
        if serve_metrics:
            metrics_server = start_http_server(worker.metrics_port)
        logger.info("worker_started")
        while not stop.is_set():
            try:
                outcome = run_once()
                if outcome in ("idle", "recording_failed"):
                    stop.wait(shared.worker_poll_seconds)
            except Exception as exc:  # noqa: BLE001 - recovery/claim may lose DB access
                logger.error("worker_poll_failed", extra={"exception_type": type(exc).__name__})
                stop.wait(shared.worker_poll_seconds)
    finally:
        if metrics_server:
            server, thread = metrics_server
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        logger.info("worker_stopped")


if __name__ == "__main__":
    run_worker()
