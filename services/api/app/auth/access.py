from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.config import get_settings
from services.common.db import get_db
from services.common.models import ReviewSession, ReviewUser, utcnow

COOKIE = "pri_review_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {
    "/",
    "/health/live",
    "/health/ready",
    "/metrics",
    "/auth/session",
    "/auth/login",
    "/auth/logout",
    "/project-docs/architecture",
    "/project-docs/human-review",
    "/project-docs/operations",
    "/project-docs/readme",
}


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(token.encode(), b"pri-review-csrf-v1", hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    mode: str
    token: str = ""
    expires_at: datetime | None = None

    def read(self) -> dict:
        return {
            "mode": self.mode,
            "authenticated": True,
            "username": self.username,
            "role": self.role,
            "can_review": self.role == "reviewer",
            "csrf_token": csrf_token(self.token) if self.token else None,
            "expires_at": self.expires_at,
        }


def principal(request: Request, db: Session) -> Principal | None:
    settings = get_settings()
    if settings.review_auth_mode == "demo":
        operator = settings.review_demo_operator.strip()
        if not operator or len(operator) > 64:
            raise HTTPException(503, detail={"code": "review_identity_unavailable"})
        return Principal(operator, "reviewer", "demo")
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        return None
    session = db.get(ReviewSession, token_hash(token))
    if session is None:
        return None
    query = select(ReviewUser).where(ReviewUser.id == session.user_id)
    if request.method not in SAFE_METHODS:
        # Role changes, logout and business writes serialize on the user row.
        query = query.with_for_update()
    user = db.scalar(query.execution_options(populate_existing=True))
    session = db.scalar(
        select(ReviewSession)
        .where(
            ReviewSession.token_hash == token_hash(token),
        )
        .execution_options(populate_existing=True)
    )
    if not user or not user.enabled or not session or aware(session.expires_at) <= utcnow():
        return None
    return Principal(user.username, user.role, "session", token, aware(session.expires_at))


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if (
        (origin is not None and origin != expected)
        or (request.headers.get("sec-fetch-site") == "cross-site")
        or request.headers.get("x-review-request") != "1"
    ):
        raise HTTPException(403, detail={"code": "csrf_failed"})


def check_csrf(request: Request, identity: Principal) -> None:
    check_origin(request)
    provided = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(provided.encode(), csrf_token(identity.token).encode()):
        raise HTTPException(403, detail={"code": "csrf_failed"})


def require_access(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    if request.url.path in PUBLIC_PATHS:
        return None
    identity = principal(request, db)
    if identity is None:
        raise HTTPException(401, detail={"code": "login_required"})
    if request.method not in SAFE_METHODS and identity.mode == "session":
        check_csrf(request, identity)
        if identity.role != "reviewer":
            raise HTTPException(403, detail={"code": "review_permission_denied"})
    from services.api.app.batches import guard_resource
    guard_resource(request, db)
    return identity


def review_operator(identity: Principal = Depends(require_access)) -> str:
    return identity.username
