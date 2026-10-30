"""Standalone midterm presenter; business processing stays in the real R1/R2/R3 code.

Run one Uvicorn process through compose.midterm.yaml. All visitors share one round.
"""
import asyncio
from contextlib import asynccontextmanager
import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.common.db import get_session_factory
from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, Job, utcnow
from services.common.schemas import ExtractionRequest

processes = {}
handles = {}
current = None
scenarios = {}
calls = {}
control = asyncio.Lock()


async def stop_process(name):
    process = processes.get(name)
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 15)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait)
    handle = handles.pop(name, None)
    if handle:
        handle.close()


def launch(name, command, env=None):
    log = open(Path(tempfile.gettempdir()) / f"midterm-{name}.log", "w")
    handles[name] = log
    processes[name] = subprocess.Popen(
        command, env=env or os.environ.copy(), stdout=log, stderr=subprocess.STDOUT,
    )


@asynccontextmanager
async def lifespan(app):
    try:
        for name, port, module in (
            ("ai", 18100, "services.ai.app.main:app"),
            ("api", 18000, "services.api.app.main:app"),
        ):
            launch(name, [sys.executable, "-m", "uvicorn", module,
                          "--host", "127.0.0.1", "--port", str(port)])
        async with httpx.AsyncClient() as client:
            for port in (18000, 18100):
                for _ in range(100):
                    try:
                        response = await client.get(
                            f"http://127.0.0.1:{port}/health/ready", timeout=0.5,
                        )
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.15)
                else:
                    raise RuntimeError(f"Midterm service on port {port} could not start")
        yield
    finally:
        for name in ("worker", "api", "ai"):
            await stop_process(name)


app = FastAPI(title="MAIE 6000C Midterm Demo", lifespan=lifespan)


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    # Accept the actual localhost port selected by Compose; no saved machine URL is needed.
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "请从当前演示页面提交操作"}, status_code=403)
    return await call_next(request)


class Example(BaseModel):
    body: str = Field(min_length=1, max_length=500)
    scenario: Literal["normal", "once", "fail"] = "normal"


@app.get("/")
@app.get("/zh", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/en", include_in_schema=False)
def english_index():
    return FileResponse(Path(__file__).with_name("index.en.html"))

@app.get("/health/ready")
def ready():
    if any(processes[name].poll() is not None for name in ("api", "ai")):
        raise HTTPException(503, "演示后台服务已停止，请查看容器日志")
    return {"status": "ok"}


def read_state():
    active = current
    if active is None:
        return {"phase": "empty", "worker": False}
    with get_session_factory()() as db:
        job = db.get(Job, active["job_id"])
        comment = db.get(Comment, active["comment_id"])
        if job is None or comment is None:
            raise HTTPException(503, "演示数据暂时无法读取")
        links = db.execute(
            select(CommentIssue, Issue).join(Issue, CommentIssue.issue_id == Issue.id)
            .where(CommentIssue.comment_id == comment.id,
                   CommentIssue.superseded_at.is_(None))
        ).all()
        runs = db.execute(
            select(AnalysisRun).where(AnalysisRun.comment_id == comment.id)
            .order_by(AnalysisRun.id)
        ).scalars().all()
        wait = max(0, (job.next_attempt_at - utcnow()).total_seconds()) if (
            job.next_attempt_at is not None
        ) else 0
        process = processes.get("worker")
        return {
            "phase": job.status, "worker": process is not None and process.poll() is None,
            "batch_id": job.batch_id, "job_id": job.id, "comment_id": comment.id,
            "body": comment.body, "comment_status": comment.analysis_status,
            "has_issue": comment.has_issue, "attempts": job.attempts,
            "max_attempts": job.max_attempts, "wait": round(wait, 1),
            "error_code": job.error_code, "scenario": active["scenario"],
            "links": [{"title": issue.title, "category": issue.category_id,
                       "evidence": link.evidence_text, "verified": link.evidence_verified}
                      for link, issue in links],
            "runs": [{"attempt": run.output_json.get("_worker", {}).get("attempt"),
                      "status": run.status, "error_code": run.error_code,
                      "latency_ms": run.latency_ms} for run in runs],
        }


@app.get("/lesson/state")
def state():
    return read_state()


@app.post("/lesson/import")
async def import_example(example: Example):
    global current
    async with control:
        if current is not None:
            raise HTTPException(409, "请先完成当前演示，再点击重新演示")
        if not example.body.strip():
            raise HTTPException(422, "请先输入一条评论")
        await stop_process("worker")
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["shop_id", "product_id", "source_review_id", "body"])
        writer.writerow(["midterm-shop", "midterm-" + uuid.uuid4().hex,
                         uuid.uuid4().hex, example.body.strip()])
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://127.0.0.1:18000/review-batches",
                json={"platform": "midterm", "csv_text": stream.getvalue()}, timeout=10,
            )
        response.raise_for_status()
        batch_id = response.json()["batch_id"]
        with get_session_factory()() as db:
            job = db.execute(select(Job).where(Job.batch_id == batch_id)).scalar_one()
            current = {"job_id": job.id, "comment_id": job.comment_id,
                       "scenario": example.scenario}
            scenarios[job.comment_id] = example.scenario
        return read_state()


@app.post("/lesson/start")
async def start():
    async with control:
        if current is None:
            raise HTTPException(409, "先把评论存入数据库")
        if read_state()["phase"] in ("completed", "failed"):
            raise HTTPException(409, "这一轮已结束，可以重新演示")
        process = processes.get("worker")
        if process is None or process.poll() is not None:
            await stop_process("worker")
            env = dict(os.environ, AI_SERVICE_URL="http://127.0.0.1:18707",
                       WORKER_POLL_SECONDS="0.3", WORKER_REQUEST_TIMEOUT_SECONDS="10",
                       WORKER_LEASE_SECONDS="60", WORKER_RETRY_BASE_SECONDS="3",
                       WORKER_RETRY_MAX_SECONDS="6", WORKER_METRICS_PORT="8200")
            launch("worker", [sys.executable, "-m", "services.worker.app.main"], env)
        return read_state()


@app.post("/lesson/reset")
async def reset():
    global current
    async with control:
        if current is not None and read_state()["phase"] not in ("completed", "failed"):
            raise HTTPException(409, "先等待这一轮处理结束")
        await stop_process("worker")
        current = None
        scenarios.clear()
        calls.clear()
        return read_state()


@app.post("/extract-issues")
async def demo_ai_proxy(payload: ExtractionRequest):
    comment_id = payload.comment_id
    calls[comment_id] = calls.get(comment_id, 0) + 1
    scenario = scenarios.get(comment_id, "normal")
    # Extra pause and 503s are presentation-only; the actual R2 worker is unmodified.
    await asyncio.sleep(3)
    if scenario == "fail" or (scenario == "once" and calls[comment_id] == 1):
        return JSONResponse({"error": "midterm fault injection"}, status_code=503)
    async with httpx.AsyncClient() as client:
        response = await client.post("http://127.0.0.1:18100/extract-issues",
                                     json=payload.model_dump(mode="json"), timeout=5)
    return JSONResponse(response.json(), status_code=response.status_code)
