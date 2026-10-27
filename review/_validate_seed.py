"""Validate seed script against an in-memory SQLite database (no server needed)."""

from __future__ import annotations

import os
import runpy

os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from services.common import db as db_module  # noqa: E402
from services.common import models  # noqa: E402,F401  (register all tables)
from services.common.db import Base  # noqa: E402

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(engine)
db_module._SESSION_FACTORY = db_module.make_session_factory(engine)

seed = runpy.run_path(r"scripts/seed_demo_data.py", run_name="seed_validation")
seed["main"]()
seed["main"]()  # idempotent second run

from services.common.db import get_session_factory  # noqa: E402
from services.common.models import Comment, Issue, Job  # noqa: E402

with get_session_factory()() as db:
    comments = db.query(Comment).count()
    issues = db.query(Issue).count()
    jobs = db.query(Job).count()
print(f"VALIDATION: comments={comments} issues={issues} jobs={jobs}")
assert (comments, issues, jobs) == (6, 3, 6), (comments, issues, jobs)
print("SEED VALIDATION OK")
