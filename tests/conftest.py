from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from services.api.app.main import app
from services.common.db import Base, get_db, make_session_factory


@pytest.fixture()
def engine():
    """In-memory SQLite shared across threads (no tmp files, CI friendly)."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    try:
        yield test_engine
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return make_session_factory(engine)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

# R2 fixtures exercise the public worker orchestrator with a controlled AI boundary.
@pytest.fixture()
def worker_settings():
    from services.worker.app.settings import WorkerSettings

    return WorkerSettings(retry_base_seconds=1, retry_max_seconds=25)


@pytest.fixture()
def worker_setup(session_factory, worker_settings, monkeypatch):
    from services.worker.app import main as worker

    monkeypatch.setattr(worker, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(worker, "get_worker_settings", lambda: worker_settings)
    return worker


@pytest.fixture()
def new_job(session_factory):
    import hashlib
    import uuid

    from services.common.models import Comment, IngestionBatch, Job

    def create(body="拉链卡住了。", product="bag-1", shop="shop-1", platform="demo"):
        with session_factory() as db:
            batch = IngestionBatch(platform=platform, source_type="csv", status="imported",
                                   accepted_rows=1, declared_rows=1)
            db.add(batch)
            db.flush()
            comment = Comment(
                platform=platform, shop_id=shop, product_id=product,
                source_review_id=str(uuid.uuid4()), batch_id=batch.id, body=body,
                content_hash=hashlib.sha256(body.encode()).hexdigest(), analysis_status="queued",
            )
            db.add(comment)
            db.flush()
            job = Job(comment_id=comment.id, batch_id=batch.id)
            db.add(job)
            db.commit()
            return job.id, comment.id, batch.id
    return create


@pytest.fixture()
def ai_response(monkeypatch):
    import httpx

    from services.ai.app.main import extract_issues
    from services.common.schemas import ExtractionRequest

    calls = []

    class Reply:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def reply(url, json, timeout=None):
        calls.append(json)
        return Reply(extract_issues(ExtractionRequest(**json)).model_dump(mode="json"))

    monkeypatch.setattr(httpx, "post", reply)
    return Reply, reply, calls
