import httpx
from sqlalchemy import select

from services.common.models import AnalysisRun, Comment, CommentIssue, IngestionBatch, Job


def upload(client, body="拉链坏了。", key=None):
    result = client.post(
        "/review-batches",
        json={
            "platform": "demo",
            "filename": "reviews.csv",
            "idempotency_key": key,
            "csv_text": "shop_id,product_id,source_review_id,body\ns,p,r," + body,
        },
    )
    assert result.status_code == 202, result.text
    return result.json()["batch_id"]


def test_stop_keeps_completed_results_and_cancels_remaining(
    client, session_factory, worker_setup, ai_response
):
    first = client.post(
        "/review-batches",
        json={
            "platform": "demo",
            "csv_text": "shop_id,product_id,body\ns,p,拉链坏了\ns,p,快递慢\ns,p,掉色严重",
        },
    ).json()["batch_id"]
    assert worker_setup.run_once() == "completed"
    stopped = client.post(f"/review-batches/{first}/stop")
    assert stopped.status_code == 200 and stopped.json()["cancelled_now"] == 2
    progress = client.get(f"/review-batches/{first}").json()
    assert progress["status"] == "stopped"
    assert progress["analyzed_rows"] == 1 and progress["cancelled_rows"] == 2
    assert progress["waiting_rows"] == progress["processing_rows"] == 0
    assert len(client.get("/comments", params={"batch_id": first}).json()) == 1
    records = client.get(f"/review-batches/{first}/records").json()
    assert records["total"] == 3
    assert [r["analysis_status"] for r in records["items"]].count("cancelled") == 2
    assert worker_setup.run_once() == "idle"
    assert client.post(f"/review-batches/{first}/stop").json()["cancelled_now"] == 0


def test_stop_during_ai_call_rejects_late_result_and_failure(
    client, session_factory, worker_setup, ai_response, monkeypatch
):
    batch = upload(client)
    _, reply, _ = ai_response

    def stop_before_reply(url, json, timeout=None):
        assert client.post(f"/review-batches/{batch}/stop").status_code == 200
        return reply(url, json, timeout)

    monkeypatch.setattr(httpx, "post", stop_before_reply)
    assert worker_setup.run_once() == "stale"
    with session_factory() as db:
        assert db.scalar(select(Job)).status == "cancelled"
        assert db.scalar(select(Comment)).analysis_status == "cancelled"
        assert db.scalar(select(AnalysisRun)) is None
        assert db.scalar(select(CommentIssue)) is None
    assert worker_setup.run_once() == "idle"


def test_trash_restore_and_purge_only_affect_selected_batch(
    client, session_factory, worker_setup, ai_response
):
    first, second = upload(client), upload(client)
    worker_setup.run_once()
    worker_setup.run_once()
    with session_factory() as db:
        old = db.scalar(select(Comment).where(Comment.batch_id == first))
        old_id = old.id
        other = db.scalar(select(Comment).where(Comment.batch_id == second))
        other_id, other_text = other.id, other.body
        old_link = db.scalar(select(CommentIssue).where(CommentIssue.comment_id == old_id)).id
    assert client.post(f"/review-batches/{first}/trash").status_code == 200
    assert client.get(f"/comments/{old_id}").status_code == 404
    assert client.get(f"/comment-issues/{old_link}").status_code == 404
    assert client.get("/stats/summary").json()["received_rows"] == 1
    assert len(client.get("/comments").json()) == 1
    assert client.get("/review-queue").json()["total"] == 1
    assert client.get("/review-issues", params={"status": "all"}).json()["total"] == 1
    assert [b["id"] for b in client.get("/review-batches", params={"trash": True}).json()] == [
        first
    ]
    assert client.post(f"/review-batches/{first}/restore").status_code == 200
    assert client.get(f"/comments/{old_id}").status_code == 200
    assert client.delete(f"/review-batches/{first}").status_code == 422
    assert client.delete(f"/review-batches/{first}", params={"permanent": True}).status_code == 204
    with session_factory() as db:
        assert db.get(IngestionBatch, first) is None
        assert db.get(Comment, old_id) is None
        assert db.get(Comment, other_id).body == other_text
    assert client.get(f"/comments/{other_id}").status_code == 200


def test_restore_does_not_resume_cancelled_work(client, worker_setup, ai_response):
    first = upload(client)
    assert client.post(f"/review-batches/{first}/trash").status_code == 200
    assert client.post(f"/review-batches/{first}/restore").status_code == 200
    assert worker_setup.run_once() == "idle"
    assert client.get(f"/review-batches/{first}").json()["cancelled_rows"] == 1
