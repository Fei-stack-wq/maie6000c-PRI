"""Authentication boundaries use the real API, database, cookies and password hashes."""

from datetime import timedelta
import hashlib

import pytest
from pydantic import ValidationError

from services.api.app.auth.access import COOKIE, token_hash
from services.api.app.auth.manage import manage_user
from services.api.app.auth.passwords import hash_password, verify_password
from services.api.app.main import app
from services.common.config import Settings, get_settings
from services.common.models import (
    CommentIssue,
    IssueAction,
    ReviewLoginThrottle,
    ReviewSession,
    ReviewUser,
    utcnow,
)

PASSWORD = "Local-test-password-2026"
LOGIN_HEADERS = {"X-Review-Request": "1", "Origin": "http://testserver"}


@pytest.fixture()
def enable_auth(monkeypatch):
    def enable(secure=False):
        monkeypatch.setenv("REVIEW_AUTH_MODE", "session")
        monkeypatch.setenv("REVIEW_COOKIE_SECURE", str(secure).lower())
        get_settings.cache_clear()

    yield enable
    get_settings.cache_clear()


@pytest.fixture()
def accounts(session_factory):
    with session_factory() as db:
        for name, role in [("alice", "reviewer"), ("bob", "viewer"), ("carol", "reviewer")]:
            manage_user(db, "create", name, role=role, password=PASSWORD)


def login(client, username="alice", password=PASSWORD, **kwargs):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers=kwargs.get("headers", LOGIN_HEADERS),
    )


def auth_headers(response):
    assert response.status_code == 200, response.text
    return {**LOGIN_HEADERS, "X-CSRF-Token": response.json()["csrf_token"]}


@pytest.mark.parametrize("document", ["architecture", "readme", "human-review", "operations"])
def test_public_project_docs_are_local_text_without_unlocking_business_data(
    client, enable_auth, document,
):
    enable_auth()
    response = client.get(f"/project-docs/{document}")
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/plain')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.text.startswith('# ')
    assert client.get('/comments').status_code == 401


def test_project_docs_do_not_expose_arbitrary_repository_files(client):
    for name in ['.env', 'alembic.ini', 'services', '..%2F.env', '%2E%2E%2FREADME.md']:
        assert client.get('/project-docs/' + name).status_code == 404


def business_routes():
    prefixes = ("/review-", "/comments", "/comment-issues", "/issues", "/jobs", "/stats")
    return [route for route in app.routes if route.path.startswith(prefixes)]


def route_path(route):
    path = route.path
    for key in ("link_id", "comment_id", "issue_id", "batch_id", "job_id"):
        path = path.replace("{" + key + "}", "1")
    return path


def test_every_business_route_requires_login(client, enable_auth):
    enable_auth()
    assert not client.get("/auth/session").json()["authenticated"]
    for route in business_routes():
        for method in route.methods:
            response = client.request(
                method, route_path(route), json={} if method == "POST" else None
            )
            assert response.status_code == 401, (method, route.path, response.text)
    assert client.get("/health/live").status_code == 200
    assert client.get("/ui/").status_code == 200


def test_session_cookie_and_db_never_store_plaintext_credentials(
    client,
    session_factory,
    accounts,
    enable_auth,
):
    enable_auth()
    result = login(client, " ALICE ")
    assert result.status_code == 200
    assert result.json()["username"] == "alice"
    assert result.json()["can_review"]
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Max-Age=28800" in cookie
    token = client.cookies.get(COOKIE)
    with session_factory() as db:
        session = db.query(ReviewSession).one()
        assert session.token_hash == token_hash(token) != token
        user = db.query(ReviewUser).filter_by(username="alice").one()
        assert user.password_hash != PASSWORD and verify_password(PASSWORD, user.password_hash)
    info = client.get("/auth/session")
    assert info.json() == result.json()
    assert info.headers["Cache-Control"] == "no-store"
    assert PASSWORD not in result.text and token not in result.text


def test_https_cookie_is_secure(client, accounts, enable_auth):
    enable_auth(secure=True)
    assert "Secure" in login(client).headers["set-cookie"]


def test_reviewer_decision_uses_authenticated_actor_and_keeps_receipts(
    client,
    session_factory,
    review_candidate,
    review_payload,
    accounts,
    enable_auth,
):
    item = review_candidate()
    enable_auth()
    headers = auth_headers(login(client))
    payload = review_payload(item)
    path = f"/comment-issues/{item['link']['id']}/decisions"
    first = client.post(path, json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert client.post(path, json=payload, headers=headers).json() == first.json()
    with session_factory() as db:
        assert db.query(IssueAction).one().operator == "alice"
        assert db.get(CommentIssue, item["link"]["id"]).decided_by == "alice"
    assert client.get("/review-queue").json()["operator"] == "alice"
    # UUID receipts are bound to the actor; another reviewer cannot impersonate its sender.
    carol = auth_headers(login(client, "carol"))
    assert client.post(path, json=payload, headers=carol).status_code == 409


def test_viewer_reads_but_all_business_writes_are_denied(
    client,
    session_factory,
    review_candidate,
    accounts,
    enable_auth,
):
    item = review_candidate()
    enable_auth()
    result = login(client, "bob")
    headers = auth_headers(result)
    assert result.json()["role"] == "viewer" and not result.json()["can_review"]
    for path in [
        "/review-batches",
        "/review-queue",
        "/review-comments",
        "/review-issues",
        "/comments",
        "/issues",
        f"/comment-issues/{item['link']['id']}",
        f"/comments/{item['comment']['id']}",
        f"/issues/{item['issue']['id']}",
        "/stats/summary",
    ]:
        assert client.get(path).status_code == 200, path
    for route in business_routes():
        if "POST" in route.methods:
            response = client.post(route_path(route), json={}, headers=headers)
            assert response.status_code == 403, (route.path, response.text)
            assert response.json()["detail"]["code"] == "review_permission_denied"
    with session_factory() as db:
        assert db.query(IssueAction).count() == 0
        assert db.get(CommentIssue, item["link"]["id"]).status == "suggested"


def test_batch_upload_requires_reviewer_and_csrf_and_viewer_can_read_results(
    client, accounts, enable_auth,
):
    enable_auth()
    payload = {'platform': 'demo', 'csv_text': 'shop_id,product_id,body\ns,p,broken zipper'}
    reviewer = auth_headers(login(client))
    assert client.post('/review-batches', json=payload).status_code == 403
    result = client.post('/review-batches', json=payload, headers=reviewer)
    assert result.status_code == 202
    batch_id = result.json()['batch_id']
    viewer = auth_headers(login(client, 'bob'))
    assert client.post('/review-batches', json=payload, headers=viewer).status_code == 403
    for path in ['/review-batches', f'/review-batches/{batch_id}',
                 f'/review-batches/{batch_id}/errors', f'/comments?batch_id={batch_id}']:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-CSRF-Token": "forged"},
        {"Origin": "https://foreign.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "null"},
    ],
)
def test_mutations_require_csrf_and_same_origin(
    client,
    review_candidate,
    review_payload,
    accounts,
    enable_auth,
    headers,
):
    item = review_candidate()
    enable_auth()
    valid = auth_headers(login(client))
    combined = {**valid, **headers} if headers else LOGIN_HEADERS
    response = client.post(
        f"/comment-issues/{item['link']['id']}/decisions",
        json=review_payload(item),
        headers=combined,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"


@pytest.mark.parametrize("headers", [{}, {"X-Review-Request": "1", "Origin": "https://evil.test"}])
def test_login_also_rejects_cross_site_requests(client, accounts, enable_auth, headers):
    enable_auth()
    assert login(client, headers=headers).status_code == 403


def test_invalid_login_does_not_echo_password(client, enable_auth):
    enable_auth()
    secret = "secret-not-for-validation-output"
    result = client.post(
        "/auth/login", json={"username": {}, "password": secret}, headers=LOGIN_HEADERS
    )
    assert result.status_code == 422 and secret not in result.text
    assert client.post("/auth/login", content="a" * 4097, headers=LOGIN_HEADERS).status_code == 422


@pytest.mark.parametrize("username", ["alice", "unknown-user"])
def test_login_throttle_does_not_reveal_if_account_exists(
    client,
    session_factory,
    accounts,
    enable_auth,
    username,
):
    enable_auth()
    for _ in range(5):
        response = login(client, username, "wrong-password")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "invalid_credentials"
    response = login(client, username)
    assert response.status_code == 429 and response.headers["Retry-After"] == "900"
    with session_factory() as db:
        for bucket in db.query(ReviewLoginThrottle):
            bucket.window_start = utcnow() - timedelta(minutes=16)
        db.commit()
    assert login(client, username).status_code == (200 if username == "alice" else 401)


def test_ip_throttle_survives_username_rotation(client, session_factory, enable_auth):
    enable_auth()
    with session_factory() as db:
        db.add(
            ReviewLoginThrottle(
                key="ip:" + hashlib.sha256(b"testclient").hexdigest(),
                window_start=utcnow(),
                attempts=30,
            )
        )
        db.commit()
    assert login(client, "another-user").status_code == 429


def test_logout_revokes_cookie_token_in_database(client, accounts, enable_auth):
    enable_auth()
    headers = auth_headers(login(client))
    old = client.cookies.get(COOKIE)
    assert client.post("/auth/logout", json={}, headers=LOGIN_HEADERS).status_code == 403
    assert client.get("/review-queue").status_code == 200
    assert client.post("/auth/logout", json={}, headers=headers).status_code == 200
    client.cookies.set(COOKIE, old)
    assert client.get("/review-queue").status_code == 401


def test_new_login_rotates_same_browser_session(client, session_factory, accounts, enable_auth):
    enable_auth()
    login(client)
    old = client.cookies.get(COOKIE)
    login(client)
    new = client.cookies.get(COOKIE)
    assert old != new
    with session_factory() as db:
        assert db.get(ReviewSession, token_hash(old)) is None
        assert db.get(ReviewSession, token_hash(new)) is not None


def test_expired_or_forged_cookie_is_rejected(client, session_factory, accounts, enable_auth):
    enable_auth()
    login(client)
    with session_factory() as db:
        db.query(ReviewSession).one().expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/review-queue").status_code == 401
    assert not client.get("/auth/session").json()["authenticated"]
    client.cookies.clear()
    client.cookies.set(COOKIE, "invented-token")
    assert client.get("/review-queue").status_code == 401


@pytest.mark.parametrize(
    "action,kwargs",
    [
        ("role", {"role": "viewer"}),
        ("password", {"password": "A-different-local-password"}),
        ("disable", {}),
    ],
)
def test_account_changes_revoke_all_sessions(
    client,
    session_factory,
    accounts,
    enable_auth,
    action,
    kwargs,
):
    enable_auth()
    login(client)
    with session_factory() as db:
        manage_user(db, action, "alice", **kwargs)
        assert db.query(ReviewSession).count() == 0
    assert client.get("/review-queue").status_code == 401
    response = login(client)
    assert response.status_code == (200 if action == "role" else 401)
    if action == "role":
        assert not response.json()["can_review"]


def test_account_management_preserves_existing_history(session_factory, accounts):
    with session_factory() as db:
        user = db.query(ReviewUser).filter_by(username="alice").one()
        original_id = user.id
        manage_user(db, "disable", "alice")
        enabled = manage_user(db, "enable", "alice")
        assert enabled.id == original_id and enabled.username == "alice"
        with pytest.raises(ValueError):
            manage_user(db, "create", "demo-reviewer", role="reviewer", password=PASSWORD)
        with pytest.raises(ValueError):
            manage_user(db, "create", "alice", role="reviewer", password=PASSWORD)


def test_password_salt_and_length():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and verify_password(PASSWORD, first)
    assert not verify_password("incorrect", first)
    assert not verify_password(PASSWORD, "bad hash")
    for value in ("short", " " * 12, "x" * 257):
        with pytest.raises(ValueError):
            hash_password(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"review_auth_mode": "demo"},
        {"review_cookie_secure": False},
    ],
)
def test_production_cannot_start_with_demo_or_insecure_cookies(changes):
    values = {"app_env": "production", "review_auth_mode": "session", "review_cookie_secure": True}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**values, **changes})
    assert Settings(_env_file=None, **values).review_auth_mode == "session"


def test_explicit_demo_mode_remains_compatible(client):
    info = client.get("/auth/session").json()
    assert info["mode"] == "demo" and info["username"] == "demo-reviewer"
    assert info["can_review"] and info["csrf_token"] is None
    assert login(client).status_code == 409
