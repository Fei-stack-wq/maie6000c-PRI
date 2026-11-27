"""Model retries are separate from Worker job retries; never use a real API key."""

import httpx
import pytest

from services.ai.app import main as ai
from services.common.config import Settings
from services.common.schemas import ExtractionRequest


@pytest.mark.parametrize(
    "failures,expected_source", [(0, "llm"), (1, "llm"), (2, "llm"), (3, "heuristic")]
)
@pytest.mark.parametrize("failure", ["timeout", "http_429", "bad_json"])
def test_model_retries_before_rule_fallback(monkeypatch, failures, expected_source, failure):
    settings = Settings(
        llm_provider="openai_compatible",
        llm_api_key="unit-test-only",
        llm_base_url="https://test.invalid/v1",
        llm_model="test-model",
    )
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: None)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        request = httpx.Request("POST", url)
        if len(calls) <= failures:
            if failure == "timeout":
                raise httpx.ReadTimeout("test", request=request)
            if failure == "http_429":
                return httpx.Response(429, request=request, json={})
            return httpx.Response(
                200, request=request, json={"choices": [{"message": {"content": "invalid"}}]}
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [{"message": {"content": '{"has_issue":"no","issues":[]}'}}],
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    result = ai.run_extraction(
        ExtractionRequest(comment_id="retry", product_id="p", body="拉链坏了")
    )
    assert len(calls) == min(failures + 1, 3)
    assert result.llm_attempts == len(calls)
    assert result.source == expected_source
    assert (result.fallback_reason is not None) == (failures == 3)


def test_missing_key_does_not_send_or_retry_provider(monkeypatch):
    monkeypatch.setattr(
        ai, "get_settings", lambda: Settings(llm_provider="openai_compatible", llm_api_key="")
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("must not send"))
    result = ai.run_extraction(
        ExtractionRequest(comment_id="missing", product_id="p", body="拉链坏了")
    )
    assert result.source == "heuristic"
    assert result.fallback_reason == "no_api_key"
    assert result.llm_attempts == 0


def test_worker_timeout_contains_all_model_attempts():
    settings = Settings(llm_timeout_seconds=15, worker_request_timeout_seconds=20)
    assert settings.extraction_request_timeout_seconds >= 3 * 15 + 5


@pytest.mark.parametrize("failures,source", [(2, "llm"), (3, "heuristic")])
def test_pipeline_persists_model_attempts_separately_from_job_attempts(
    monkeypatch,
    session_factory,
    new_job,
    worker_setup,
    failures,
    source,
):
    from services.common.models import AnalysisRun, Job

    settings = Settings(
        llm_provider="openai_compatible",
        llm_api_key="unit-test-only",
        llm_base_url="https://test.invalid/v1",
        llm_model="test-model",
    )
    monkeypatch.setattr(ai, "get_settings", lambda: settings)
    monkeypatch.setattr(ai.time, "sleep", lambda _: None)
    provider_calls = []

    def post(url, **kwargs):
        request = httpx.Request("POST", url)
        if "test.invalid" in url:
            provider_calls.append(url)
            if len(provider_calls) <= failures:
                raise httpx.ReadTimeout("test", request=request)
            content = (
                '{"has_issue":"yes","issues":[{"category_id":"quality",'
                '"description":"拉链损坏","evidence_text":"拉链坏了"}]}'
            )
            payload = {"choices": [{"message": {"content": content}}]}
        elif url.endswith("/extract-issues"):
            result = ai.run_extraction(ExtractionRequest(**kwargs["json"]))
            payload = result.model_dump(mode="json")
        else:
            pytest.fail("No grouping candidate should need another HTTP call")
        return httpx.Response(200, request=request, json=payload)

    monkeypatch.setattr(httpx, "post", post)
    job_id, _, _ = new_job(body="拉链坏了")
    assert worker_setup.run_once() == "completed"
    with session_factory() as db:
        job = db.get(Job, job_id)
        run = db.query(AnalysisRun).filter_by(job_id=job_id).one()
        assert job.attempts == 1
        assert run.output_json["llm_attempts"] == 3
        assert run.output_json["source"] == source
        assert len(provider_calls) == 3
