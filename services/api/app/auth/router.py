from datetime import timedelta
import hashlib
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from services.api.app.auth.access import (
    COOKIE,
    Principal,
    aware,
    check_csrf,
    check_origin,
    principal,
    token_hash,
)
from services.api.app.auth.passwords import DUMMY_HASH, normalize_username, verify_password
from services.common.config import get_settings
from services.common.db import get_db
from services.common.models import ReviewLoginThrottle, ReviewSession, ReviewUser, utcnow

router = APIRouter(prefix="/auth", tags=["Authentication"])
WINDOW = timedelta(minutes=15)


def throttle(db: Session, username: str, address: str) -> ReviewLoginThrottle:
    """Shared fixed-window limits, with sorted locks even on first-time attempts."""
    keys = [
        ("ip:" + hashlib.sha256(address.encode()).hexdigest(), 30),
        ("user:" + hashlib.sha256(username.encode()).hexdigest(), 5),
    ]
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    now = utcnow()
    account = None
    for key, limit in sorted(keys):
        db.execute(
            insert(ReviewLoginThrottle)
            .values(
                key=key,
                window_start=now,
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=["key"])
        )
        bucket = db.scalar(
            select(ReviewLoginThrottle)
            .where(
                ReviewLoginThrottle.key == key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if aware(bucket.window_start) + WINDOW <= now:
            bucket.window_start, bucket.attempts = now, 0
        if bucket.attempts >= limit:
            db.rollback()
            raise HTTPException(
                429, detail={"code": "login_rate_limited"}, headers={"Retry-After": "900"}
            )
        bucket.attempts += 1
        db.flush()
        if key.startswith("user:"):
            account = bucket
    return account


@router.get("/session")
def session_info(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    identity = principal(request, db)
    return (
        identity.read()
        if identity
        else {
            "mode": "session",
            "authenticated": False,
            "username": None,
            "role": None,
            "can_review": False,
            "csrf_token": None,
            "expires_at": None,
        }
    )


async def login_body(request: Request) -> tuple[str, str]:
    settings = get_settings()
    if settings.review_auth_mode != "session":
        raise HTTPException(409, detail={"code": "login_disabled_in_demo"})
    check_origin(request)
    # Bound the body and return a fixed error; validation never reflects passwords.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(422, detail={"code": "invalid_login"})
    try:
        data = json.loads(body)
        if (
            request.headers.get("content-type", "").split(";")[0] != "application/json"
            or not isinstance(data, dict)
            or set(data) != {"username", "password"}
            or not isinstance(data["username"], str)
            or not isinstance(data["password"], str)
            or not 1 <= len(data["password"]) <= 256
        ):
            raise ValueError
        username = normalize_username(data["username"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(422, detail={"code": "invalid_login"}) from None
    return username, data["password"]


@router.post("/login")
def login(
    request: Request,
    response: Response,
    credentials: tuple = Depends(login_body),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    username, password = credentials
    bucket = throttle(db, username, request.client.host if request.client else "unknown")
    user = db.scalar(select(ReviewUser).where(ReviewUser.username == username).with_for_update())
    correct = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not correct or not user or not user.enabled:
        db.commit()  # Persist failed attempts, including unknown and disabled accounts.
        raise HTTPException(401, detail={"code": "invalid_credentials"})
    bucket.attempts = 0
    now = utcnow()
    db.execute(
        delete(ReviewSession).where(
            ReviewSession.user_id == user.id,
            ReviewSession.expires_at <= now,
        )
    )
    old_token = request.cookies.get(COOKIE, "")
    if old_token:
        db.execute(delete(ReviewSession).where(ReviewSession.token_hash == token_hash(old_token)))
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(hours=settings.review_session_hours)
    db.add(ReviewSession(token_hash=token_hash(token), user_id=user.id, expires_at=expires))
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.review_session_hours * 3600,
        secure=settings.review_cookie_secure,
        httponly=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return Principal(user.username, user.role, "session", token, expires).read()


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    identity = principal(request, db)
    if identity and identity.mode == "session":
        check_csrf(request, identity)
        db.execute(
            delete(ReviewSession).where(
                ReviewSession.token_hash == token_hash(identity.token),
            )
        )
        db.commit()
    else:
        check_origin(request)
    response.delete_cookie(
        COOKIE,
        path="/",
        secure=get_settings().review_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"logged_out": True}
