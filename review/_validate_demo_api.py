"""End-to-end validation: seed data -> API read endpoints (in-memory SQLite)."""

from __future__ import annotations

import os
import runpy

os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from services.api.app.main import app  # noqa: E402
from services.common import db as db_module  # noqa: E402
from services.common import models  # noqa: E402,F401
from services.common.db import Base, get_db  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(engine)
factory = db_module.make_session_factory(engine)
db_module._SESSION_FACTORY = factory

seed = runpy.run_path(r"scripts/seed_demo_data.py", run_name="seed_e2e")
seed["main"]()


def override_get_db():
    session = factory()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_db] = override_get_db
try:
    with TestClient(app) as client:
        comments = client.get("/comments").json()
        assert len(comments) == 6, len(comments)
        assert {c["analysis_status"] for c in comments} == {"analyzed", "queued"}

        target = next(c for c in comments if c["has_issue"] == "yes")
        detail = client.get(f"/comments/{target['id']}").json()
        assert detail["issues"], "expected at least one seeded issue link"
        assert detail["latest_analysis_run"] is not None

        issues = client.get("/issues").json()
        assert len(issues) == 3, len(issues)
        assert any(i["accepted_count"] == 0 and i["suggested_count"] > 0 for i in issues)

        issue_detail = client.get(f"/issues/{issues[0]['id']}").json()
        assert issue_detail["links"], "issue detail should include links"

        stats = client.get("/stats/summary").json()
        assert stats["received_rows"] == 6
        assert stats["analyzed_rows"] == 5
        assert stats["processing_rows"] == 1
        assert stats["scope"]["as_of"]

        ui = client.get("/ui/")
        assert ui.status_code == 200 and "batches" in ui.text
finally:
    app.dependency_overrides.clear()

print("DEMO + API VALIDATION OK")
