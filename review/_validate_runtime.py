"""Runtime validation of the review-management skeleton (SQLite + Pydantic).

Runs with the Anaconda interpreter that has SQLAlchemy / Pydantic installed:

    D:\\Conda\\python.exe review/_validate_runtime.py
"""

from __future__ import annotations

import sys

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from services.common.categories import CATEGORY_VERSION, category_ids, is_valid_category
from services.common.db import Base
from services.common.models import (
    AnalysisRun,
    AnalysisStatus,
    Comment,
    CommentIssue,
    HasIssue,
    IngestionBatch,
    Issue,
    IssueStatus,
    Job,
    JobStatus,
    JobType,
    LinkStatus,
)
from services.common.schemas import (
    AnalysisJobRead,
    BatchProgressRead,
    CommentDetailRead,
    ExtractionResult,
    IssueActionRequest,
    IssueDetailRead,
    LinkDecisionRequest,
    QueryScope,
    StatsSummaryRead,
)

failures: list[str] = []


def check(cond: bool, message: str) -> None:
    print(("  ok    " if cond else "  FAIL  ") + message)
    if not cond:
        failures.append(message)


def expect_integrity_error(fn, message: str) -> None:
    try:
        fn()
    except IntegrityError:
        print("  ok    " + message)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL   {message}: unexpected {type(exc).__name__}: {exc}")
        failures.append(message)
        return
    print("  FAIL   " + message + ": no error raised")
    failures.append(message)


engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

print("== schema creates on SQLite ==")
tables = sorted(Base.metadata.tables)
print("  tables:", ", ".join(tables))
check("comments" in tables and "comment_issues" in tables and "jobs" in tables, "new tables registered")

# ---------------------------------------------------------------- happy path
with SessionFactory() as db:
    batch = IngestionBatch(platform="demo", source_type="csv", declared_rows=1)
    db.add(batch)
    db.flush()

    comment = Comment(
        platform="demo",
        shop_id="shop-1",
        product_id="bag-001",
        source_review_id="r-001",
        batch_id=batch.id,
        body="拉链拉到一半就卡住，拉不上。",
        content_hash="a" * 64,
    )
    db.add(comment)
    db.flush()
    check(comment.analysis_status == AnalysisStatus.RECEIVED.value, "comment defaults to received")
    check(comment.dedupe_mode == "source_id", "comment defaults to source_id dedupe")

    run = AnalysisRun(
        comment_id=comment.id,
        model_version="mock-1",
        prompt_version="v1",
        input_hash="b" * 64,
        status="succeeded",
        output_json={"has_issue": "yes"},
    )
    job = Job(
        comment_id=comment.id,
        batch_id=batch.id,
        job_type=JobType.EXTRACT_ISSUES.value,
        status=JobStatus.PENDING.value,
    )
    db.add_all([run, job])
    db.flush()

    comment.analysis_status = AnalysisStatus.ANALYZED.value
    comment.has_issue = HasIssue.YES.value
    comment.current_analysis_run_id = run.id

    issue = Issue(
        platform="demo",
        shop_id="shop-1",
        product_id="bag-001",
        category_id="quality",
        title="拉链卡住/拉不上",
        status=IssueStatus.PROPOSED.value,
    )
    db.add(issue)
    db.flush()
    link = CommentIssue(
        comment_id=comment.id,
        issue_id=issue.id,
        status=LinkStatus.SUGGESTED.value,
        evidence_text="拉链拉到一半就卡住",
        evidence_start=0,
        evidence_end=9,
        evidence_verified=True,
        analysis_run_id=run.id,
    )
    db.add(link)
    db.commit()
    check(issue.status == "proposed" and link.status == "suggested", "issue + suggested link persist")
    check(link.comment_version == 1 and link.superseded_at is None, "link version defaults to 1")

    # read contracts must see the ORM relations (issue_links -> issues/links alias)
    comment_view = CommentDetailRead.model_validate(db.get(Comment, comment.id))
    check(len(comment_view.issues) == 1, "CommentDetailRead sees issue links (non-empty)")
    issue_view = IssueDetailRead.model_validate(db.get(Issue, issue.id))
    check(len(issue_view.links) == 1, "IssueDetailRead sees issue links (non-empty)")
    check(issue_view.version == 1, "IssueDetailRead carries optimistic version")

# --------------------------------------------------------- constraint checks
with SessionFactory() as db:
    dupe = Comment(
        platform="demo",
        shop_id="shop-1",
        product_id="bag-001",
        source_review_id="r-001",
        body="重复来源",
        content_hash="c" * 64,
    )
    db.add(dupe)
    expect_integrity_error(db.flush, "unique(platform, shop, product, source_review_id) enforced")
    db.rollback()

with SessionFactory() as db:
    comment = db.execute(select(Comment)).scalars().first()
    assert comment is not None
    active = Job(comment_id=comment.id, job_type="extract_issues")
    db.add(active)
    expect_integrity_error(db.flush, "one active job per comment (partial unique index) enforced")
    db.rollback()

with SessionFactory() as db:
    comment = db.execute(select(Comment)).scalars().first()
    assert comment is not None
    done = Job(comment_id=comment.id, job_type="extract_issues", status="completed")
    db.add(done)
    db.flush()  # completed jobs are not covered by the partial index
    print("  ok    completed job does not conflict with the partial index")
    bad = Comment(
        platform="demo",
        shop_id="s",
        product_id="p",
        source_review_id="r-2",
        body="x",
        content_hash="d" * 64,
        analysis_status="invalid-status",
    )
    db.add(bad)
    expect_integrity_error(db.flush, "analysis_status CHECK enforced")
    db.rollback()

with SessionFactory() as db:
    orphan = Job(job_type="extract_issues")
    db.add(orphan)
    expect_integrity_error(db.flush, "job requires comment_id")
    db.rollback()

with SessionFactory() as db:
    comment = db.execute(select(Comment)).scalars().first()
    assert comment is not None
    bad_status = Job(comment_id=comment.id, job_type="extract_issues", status="bogus")
    db.add(bad_status)
    expect_integrity_error(db.flush, "job status CHECK enforced")
    db.rollback()

# ------------------------------------------------------------------- schemas
print("== pydantic contracts ==")
result = ExtractionResult(
    comment_id="c-1",
    has_issue="yes",
    issues=[{"category_id": "quality", "description": "拉链卡住", "evidence_text": "拉链卡住"}],
    model_version="mock-1",
    prompt_version="v1",
)
check(result.has_issue == HasIssue.YES, "ExtractionResult accepts with_issue")

for payload, label in [
    (
        {"comment_id": "c-1", "has_issue": "yes", "issues": [], "model_version": "m", "prompt_version": "v1"},
        "has_issue=yes with empty issues rejected",
    ),
    (
        {
            "comment_id": "c-1",
            "has_issue": "no",
            "issues": [{"category_id": "q", "description": "d", "evidence_text": "e"}],
            "model_version": "m",
            "prompt_version": "v1",
        },
        "has_issue=no with issues rejected",
    ),
]:
    try:
        ExtractionResult(**payload)
        check(False, label)
    except ValidationError:
        print("  ok    " + label)

for payload, label, expect_ok in [
    ({"action": "rename"}, "rename without title", False),
    ({"action": "merge_into"}, "merge_into without target", False),
    ({"action": "split"}, "split without comment_issue_ids", False),
    ({"action": "split", "comment_issue_ids": [1, 2]}, "split with links accepted", True),
    ({"action": "accept"}, "accept without comment_issue_id", False),
    ({"action": "resolve"}, "resolve accepted", True),
]:
    try:
        IssueActionRequest(**payload)
        check(expect_ok, label)
    except ValidationError:
        check(not expect_ok, label)

check(LinkDecisionRequest(decision="accept").decision.value == "accept", "link decision contract")
check(category_ids() == ("quality", "logistics", "mismatch", "usability", "other"), "category ids stable")
check(CATEGORY_VERSION == "v1" and is_valid_category("quality"), "category taxonomy versioned")

scope = QueryScope(product_id="bag-001", as_of="2026-10-27T00:00:00Z")
progress = BatchProgressRead(
    batch_id="b-1", status="imported", job_count=2, analyzed_rows=2, scope=scope
)
check(progress.analyzed_rows == 2 and progress.scope.product_id == "bag-001", "BatchProgressRead works")
stats = StatsSummaryRead(scope=scope, received_rows=10, analyzed_rows=8, failed_rows=1)
check(stats.analysis_coverage is None and stats.received_rows == 10, "StatsSummaryRead works")

# --------------------------------------------------------------- job contract
print("== job contract ==")

with SessionFactory() as db:
    comment_job = db.execute(select(Job).where(Job.comment_id.isnot(None))).scalars().first()
    assert comment_job is not None
    new_view = AnalysisJobRead.model_validate(comment_job)
    check(new_view.comment_id is not None and new_view.max_attempts == 3, "AnalysisJobRead works")

print()
if failures:
    print(f"RESULT: {len(failures)} failure(s)")
    sys.exit(1)
print("RESULT: all runtime checks passed")
