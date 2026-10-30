"""Pure retry decisions. Never store exception bodies, credentials or review text."""
from dataclasses import dataclass

import httpx
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError

from services.common.models import ErrorCode
from services.worker.app.settings import WorkerSettings


class InvalidAIOutput(ValueError):
    pass


class CommentNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Failure:
    code: str
    retryable: bool
    message: str


def classify_error(exc: Exception) -> Failure:
    if isinstance(exc, CommentNotFound):
        return Failure(ErrorCode.COMMENT_NOT_FOUND.value, False, "Comment no longer exists.")
    if isinstance(exc, InvalidAIOutput):
        return Failure(ErrorCode.AI_INVALID_OUTPUT.value, True, "AI output failed validation.")
    if isinstance(exc, httpx.TimeoutException):
        return Failure(ErrorCode.AI_TIMEOUT.value, True, "AI request timed out.")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return Failure(
            ErrorCode.AI_ERROR.value, status == 429 or status >= 500,
            f"AI service returned HTTP {status}.",
        )
    if isinstance(exc, httpx.TransportError):
        return Failure(ErrorCode.AI_ERROR.value, True, "AI service connection failed.")
    if isinstance(exc, SQLAlchemyError):
        transient = isinstance(exc, (OperationalError, InterfaceError)) or (
            isinstance(exc, DBAPIError) and exc.connection_invalidated
        )
        return Failure(ErrorCode.DB_ERROR.value, transient, "Database operation failed.")
    return Failure(ErrorCode.UNKNOWN.value, False, "Unexpected processing error.")


def should_retry(failure: Failure, attempts: int, max_attempts: int) -> bool:
    # Invalid output gets at most one automatic retry; transport failures use the job limit.
    limit = min(max_attempts, 2) if failure.code == "ai_invalid_output" else max_attempts
    return failure.retryable and attempts < limit


def calculate_retry_delay(attempts: int, settings: WorkerSettings) -> float:
    delay = settings.retry_base_seconds
    for _ in range(max(0, min(attempts - 1, 32))):
        delay = min(settings.retry_max_seconds, delay * 5)
    return min(delay, settings.retry_max_seconds)
