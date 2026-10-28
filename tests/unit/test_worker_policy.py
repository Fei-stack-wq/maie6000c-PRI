from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from services.worker.app.policy import (
    InvalidAIOutput, calculate_retry_delay, classify_error, should_retry,
)
from services.worker.app.settings import WorkerSettings


@pytest.mark.parametrize("status,retryable", [(400, False), (401, False), (429, True), (503, True)])
def test_http_retry_classification(status, retryable):
    response = httpx.Response(status, request=httpx.Request("POST", "http://ai/extract-issues"))
    failure = classify_error(httpx.HTTPStatusError("SECRET", request=response.request,
                                                 response=response))
    assert failure.retryable is retryable
    assert "SECRET" not in failure.message


def test_transport_database_and_unknown_policies():
    assert classify_error(httpx.ReadTimeout("secret")).code == "ai_timeout"
    assert classify_error(httpx.ConnectError("secret")).retryable
    assert classify_error(OperationalError("sql", {}, Exception("secret"))).retryable
    assert not classify_error(IntegrityError("sql", {}, Exception("secret"))).retryable
    failure = classify_error(RuntimeError("secret"))
    assert failure.code == "unknown" and not failure.retryable
    assert "secret" not in failure.message


def test_retry_budget_and_bounded_backoff(worker_settings):
    timeout = classify_error(httpx.ReadTimeout("timeout"))
    invalid = classify_error(InvalidAIOutput("invalid"))
    assert should_retry(timeout, 1, 3)
    assert not should_retry(timeout, 3, 3)
    assert should_retry(invalid, 1, 3)
    assert not should_retry(invalid, 2, 3)
    assert [calculate_retry_delay(n, worker_settings) for n in (1, 2, 3, 4)] == [1, 5, 25, 25]
    assert calculate_retry_delay(1000000, worker_settings) == 25


def test_invalid_worker_settings_are_rejected():
    with pytest.raises(ValueError):
        WorkerSettings(retry_base_seconds=60, retry_max_seconds=10)
    with pytest.raises(ValueError):
        WorkerSettings(lease_seconds=0)


def test_aware_normalizes_sqlite_timestamps():
    from services.worker.app.jobs import aware

    stamp = datetime(2026, 10, 29)
    assert aware(stamp) == stamp.replace(tzinfo=timezone.utc)
