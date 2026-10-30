"""Real HTTP + PostgreSQL acceptance for an idle, isolated midterm demo.

docker compose -f compose.midterm.yaml exec midterm-demo python demo/midterm/check_demo.py
No test data is deleted. Do not run while another visitor is using the demo.
"""
import time

import httpx

from services.common.db import get_session_factory
from services.common.models import AnalysisRun, Comment, CommentIssue, Job


def main():
    with httpx.Client(base_url="http://127.0.0.1:18707", timeout=10) as client:
        def post(path, data=None):
            response = client.post(path, json=data or {})
            response.raise_for_status()
            return response.json()

        assert client.get("/lesson/state").json()["phase"] == "empty", "Demo must be idle"
        assert client.post("/lesson/start").status_code == 409
        assert client.post("/lesson/import", json={"body": "   "}).status_code == 422
        assert client.post("/lesson/import", json={"body": "test"}, headers={
            "Origin": "https://other.example",
        }).status_code == 403
        cases = [
            ("拉链卡住了。", "normal", "completed", 1, "yes"),
            ("总体不错，很喜欢。", "normal", "completed", 1, "no"),
            ("怪", "normal", "completed", 1, "unknown"),
            ("拉链卡住了。", "once", "completed", 2, "yes"),
            ("拉链卡住了。", "fail", "failed", 3, None),
            ("The zipper gets stuck halfway.", "normal", "completed", 1, "yes"),
            ("Great backpack, the zipper works well.", "normal", "completed", 1, "no"),
            ("I am not sure about this bag.", "normal", "completed", 1, "unknown"),
            ("The zipper gets stuck halfway.", "once", "completed", 2, "yes"),
            ("The zipper gets stuck halfway.", "fail", "failed", 3, None),
        ]
        for body, scenario, terminal, attempts, has_issue in cases:
            initial = post("/lesson/import", {"body": body, "scenario": scenario})
            assert initial["phase"] == "pending" and initial["attempts"] == 0
            with get_session_factory()() as db:
                assert db.get(Comment, initial["comment_id"]).analysis_status == "queued"
                assert db.get(Job, initial["job_id"]).status == "pending"
            assert client.post("/lesson/reset").status_code == 409
            post("/lesson/start")
            deadline = time.monotonic() + 45
            seen = set()
            while time.monotonic() < deadline:
                response = client.get("/lesson/state")
                response.raise_for_status()
                state = response.json()
                seen.add(state["phase"])
                if state["phase"] in ("completed", "failed"):
                    break
                time.sleep(0.2)
            else:
                raise AssertionError(f"Scenario {scenario} timed out")
            assert state["phase"] == terminal and state["attempts"] == attempts
            assert state["has_issue"] == has_issue
            assert "claimed" in seen
            assert len(state["runs"]) == attempts
            with get_session_factory()() as db:
                assert db.get(Job, state["job_id"]).status == terminal
                assert db.query(AnalysisRun).filter_by(job_id=state["job_id"]).count() == attempts
                links = db.query(CommentIssue).filter_by(comment_id=state["comment_id"]).all()
                if terminal == "completed":
                    latest = db.query(AnalysisRun).filter_by(job_id=state["job_id"]).order_by(
                        AnalysisRun.id.desc(),
                    ).first()
                    assert latest.model_version == "rule-baseline-2"
                assert bool(links) == (has_issue == "yes")
                assert all(link.evidence_verified and link.evidence_text in body for link in links)
            metrics = httpx.get("http://127.0.0.1:8200/metrics", timeout=5)
            assert metrics.status_code == 200 and "worker_job_events_total" in metrics.text
            assert client.post("/lesson/start").status_code == 409
            assert post("/lesson/reset")["phase"] == "empty"
            # Starting a new round clears only presentation controls, never the stored result.
            with get_session_factory()() as db:
                assert db.get(Job, state["job_id"]).status == terminal
            print(f"PASS: {scenario}, {has_issue}, {attempts} attempt(s)", flush=True)
    print(f"Midterm acceptance: {len(cases)} cases passed; "
          "DB results, evidence and metrics verified.")


if __name__ == "__main__":
    main()
