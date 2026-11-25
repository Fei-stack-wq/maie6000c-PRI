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

    from services.ai.app.grouping import suggest_group_assignment
    from services.ai.app.main import extract_issues
    from services.common.config import Settings
    from services.common.schemas import ExtractionRequest, GroupSuggestionRequest

    calls = []

    class Reply:
        def __init__(self, payload, status_code: int = 200):
            self.payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                request = httpx.Request("POST", "http://test")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError("error", request=request, response=response)

        def json(self):
            return self.payload

    def reply(url, json, timeout=None):
        calls.append({"url": str(url), "json": json})
        path = str(url)
        if path.rstrip("/").endswith("suggest-groups"):
            # Hashing is noisier than MiniLM; keep a stricter T_overlap so hard
            # negatives in unit/integration tests do not false-merge via bypass.
            suggestion = suggest_group_assignment(
                GroupSuggestionRequest.model_validate(json),
                settings=Settings(
                    grouping_embedding_backend="hashing",
                    grouping_similarity_threshold=0.35,
                    grouping_overlap_threshold=0.75,
                    grouping_top2_margin=0.08,
                    grouping_keyword_gate=True,
                ),
            )
            return Reply(suggestion.model_dump(mode="json"))
        return Reply(extract_issues(ExtractionRequest(**json)).model_dump(mode="json"))

    monkeypatch.setattr(httpx, "post", reply)
    return Reply, reply, calls


@pytest.fixture()
def review_candidate(new_job, worker_setup, session_factory, client, ai_response):
    def create(body="拉链卡住了。", **kwargs):
        _, comment_id, _ = new_job(body=body, **kwargs)
        with session_factory() as db:
            claim = worker_setup.claim_next_pending_job(db)
        assert worker_setup.process_job(claim) == "completed"
        from services.common.models import CommentIssue
        with session_factory() as db:
            link = db.query(CommentIssue).filter_by(comment_id=comment_id).one()
            link_id = link.id
        return client.get(f"/comment-issues/{link_id}").json()
    return create


@pytest.fixture()
def review_payload():
    import uuid

    def create(item, decision="accept", note="核对原文"):
        return {"request_id": str(uuid.uuid4()), "expected_token": item["token"],
                "decision": decision, "note": note}
    return create


@pytest.fixture()
def reassign_target(session_factory):
    from services.common.models import Issue

    def create(item, **changes):
        values = {key: item["comment"][key] for key in ("platform", "shop_id", "product_id")}
        values.update(category_id="usability", title="拉链使用不顺畅", created_by="human")
        values.update(changes)
        with session_factory() as db:
            issue = Issue(**values)
            db.add(issue)
            db.commit()
            return issue.id
    return create


@pytest.fixture()
def reassign_payload(client):
    import uuid

    def create(item, target_id):
        response = client.get(f"/comment-issues/{item['link']['id']}/reassign-targets")
        assert response.status_code == 200, response.text
        target = next(row for row in response.json()["items"] if row["issue"]["id"] == target_id)
        return {"request_id": str(uuid.uuid4()), "expected_token": item["token"],
                "target_issue_id": target_id, "expected_target_token": target["token"],
                "note": "核对原文，调整到更准确的问题组"}
    return create


@pytest.fixture()
def manual_candidate(new_job, session_factory, worker_setup, ai_response, client):
    def create(body="售后一直没有回复。", **kwargs):
        _, comment_id, _ = new_job(body=body, **kwargs)
        with session_factory() as db:
            claim = worker_setup.claim_next_pending_job(db)
        assert worker_setup.process_job(claim) == "completed"
        return client.get(f"/review-comments/{comment_id}").json()
    return create


@pytest.fixture()
def manual_payload():
    import uuid

    def create(item, evidence=None, **changes):
        body = item["comment"]["body"]
        evidence = evidence if evidence is not None else body
        start = body.find(evidence)
        values = {"request_id": str(uuid.uuid4()), "expected_token": item["token"],
                  "evidence_text": evidence, "evidence_start": start,
                  "evidence_end": start + len(evidence), "note": "核对原文，补充漏检问题",
                  "new_issue": {"title": "售后不回复", "category_id": "other"}}
        values.update(changes)
        return values
    return create


@pytest.fixture()
def issue_candidate(client, review_candidate, review_payload):
    def create(accepted=True, **kwargs):
        link = review_candidate(**kwargs)
        if accepted:
            response = client.post(f"/comment-issues/{link['link']['id']}/decisions",
                                   json=review_payload(link))
            assert response.status_code == 200
            link = client.get(f"/comment-issues/{link['link']['id']}").json()
        issue = client.get(f"/review-issues/{link['issue']['id']}").json()
        return link, issue
    return create


@pytest.fixture()
def issue_payload():
    import uuid

    def create(item, action="confirm", note="核对证据后记录问题组判断"):
        return {"request_id": str(uuid.uuid4()), "expected_token": item["token"],
                "action": action, "note": note}
    return create


@pytest.fixture()
def structure_case(client, issue_candidate, review_payload, reassign_target):
    def create():
        first, _ = issue_candidate()
        second, _ = issue_candidate(accepted=False)
        third, _ = issue_candidate(accepted=False)
        assert client.post(f"/comment-issues/{third['link']['id']}/decisions",
                           json=review_payload(third, "reject", "原组中不成立")).status_code == 200
        links = [client.get(f"/comment-issues/{r['link']['id']}").json()
                 for r in (first, second, third)]
        source = client.get(f"/review-issues/{first['issue']['id']}").json()
        target_id = reassign_target(first)
        target = client.get(f"/review-issues/{target_id}").json()
        return links, source, target
    return create


@pytest.fixture()
def structure_payload():
    import uuid

    def create(source, target=None, ids=None, **changes):
        data = {"request_id": str(uuid.uuid4()), "expected_token": source["token"],
                "note": "核对原文，整理重复或混合的问题组"}
        if target:
            data.update(target_issue_id=target["issue"]["id"],
                        expected_target_token=target["token"])
        else:
            data.update(comment_issue_ids=ids,
                        new_issue={"title": "拆出的独立问题", "category_id": "other"})
        data.update(changes)
        return data
    return create


@pytest.fixture()
def update_review_source(client, session_factory, worker_setup, ai_response):
    def update(item, body="😀 拉链又卡住了。再次反馈：拉链又卡住了。", finish=True):
        c = item["comment"]
        response = client.post("/review-batches", json={"platform": c["platform"], "comments": [{
            **{key: c[key] for key in ("platform", "shop_id", "product_id", "source_review_id")},
            "body": body,
        }]})
        assert response.status_code == 202, response.text
        if finish:
            with session_factory() as db:
                claim = worker_setup.claim_next_pending_job(db)
            assert worker_setup.process_job(claim) == "completed"
        return client.get(f"/comment-issues/{item['link']['id']}").json()
    return update


@pytest.fixture()
def recheck_case(client, issue_candidate, issue_payload, update_review_source):
    def create(**kwargs):
        old, group = issue_candidate()
        assert client.post(f"/issues/{group['issue']['id']}/actions",
                           json=issue_payload(group)).status_code == 200
        old = client.get(f"/comment-issues/{old['link']['id']}").json()
        return old, update_review_source(old, **kwargs)
    return create


@pytest.fixture()
def recheck_payload():
    import uuid

    def create(item, decision="accept", evidence=None, **changes):
        quote = evidence if evidence is not None else item["comment"]["body"]
        start = item["comment"]["body"].find(quote)
        data = {"request_id": str(uuid.uuid4()), "expected_token": item["token"],
                "decision": decision, "note": "核对变化后的原文，重新判断当前关联"}
        if decision == "accept" or evidence is not None:
            data.update(evidence_text=quote, evidence_start=start, evidence_end=start + len(quote))
        data.update(changes)
        return data
    return create
