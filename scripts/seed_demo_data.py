"""Seed a small demo dataset for the review-management system.

Run:  python scripts/seed_demo_data.py
Idempotent: skips seeding when the demo batch already exists.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from services.common.db import get_session_factory
from services.common.models import (
    AnalysisRun,
    AnalysisStatus,
    BatchStatus,
    Comment,
    CommentIssue,
    HasIssue,
    IngestionBatch,
    Issue,
    IssueAction,
    IssueActionType,
    IssueStatus,
    Job,
    JobStatus,
    JobType,
    LinkOrigin,
    LinkStatus,
    utcnow,
)

DEMO_FILE = "demo_backpack_reviews.csv"
DEMO_SHOP = "demo-shop"
DEMO_PRODUCT = "backpack-001"

DEMO_COMMENTS = [
    {
        "source": "demo-0001",
        "body": "拉链拉到一半就卡住，拉不上，只能退货。",
        "rating": 2,
        "days_ago": 3,
        "status": AnalysisStatus.ANALYZED,
        "has_issue": HasIssue.YES,
        "issue": "quality",
    },
    {
        "source": "demo-0002",
        "body": "肩带太窄，背久了肩膀疼，通勤不太舒服。",
        "rating": 3,
        "days_ago": 4,
        "status": AnalysisStatus.ANALYZED,
        "has_issue": HasIssue.YES,
        "issue": "usability",
    },
    {
        "source": "demo-0003",
        "body": "实物颜色和商品图片色差很大，偏灰。",
        "rating": 3,
        "days_ago": 5,
        "status": AnalysisStatus.ANALYZED,
        "has_issue": HasIssue.YES,
        "issue": "mismatch",
    },
    {
        "source": "demo-0004",
        "body": "物流很快，包装完整，容量也够用，好评。",
        "rating": 5,
        "days_ago": 6,
        "status": AnalysisStatus.ANALYZED,
        "has_issue": HasIssue.NO,
        "issue": None,
    },
    {
        "source": "demo-0005",
        "body": "容量比想象的小，装不下 14 寸电脑；拉链头用了两周就坏了。",
        "rating": 2,
        "days_ago": 7,
        "status": AnalysisStatus.ANALYZED,
        "has_issue": HasIssue.YES,
        "issue": "quality",
    },
    {
        "source": "demo-0006",
        "body": "刚收到，还在使用中。",
        "rating": 4,
        "days_ago": 1,
        "status": AnalysisStatus.QUEUED,
        "has_issue": None,
        "issue": None,
    },
]

ISSUE_LABELS = {
    "quality": ("拉链卡住 / 拉不上", "同一商品内拉链相关的使用问题"),
    "usability": ("肩带宽窄与背负体验", "肩带、容量等使用体验问题"),
    "mismatch": ("颜色与描述不符", "实物颜色、尺寸与页面描述不符"),
}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    session_factory = get_session_factory()
    now = utcnow()

    with session_factory() as db:
        exists = db.query(IngestionBatch).filter(IngestionBatch.file_ref == DEMO_FILE).first()
        if exists is not None:
            print(f"Demo data already seeded (batch {exists.id}); nothing to do.")
            return

        batch = IngestionBatch(
            platform="demo",
            source_type="csv",
            file_ref=DEMO_FILE,
            declared_rows=len(DEMO_COMMENTS),
            accepted_rows=len(DEMO_COMMENTS),
            status=BatchStatus.IMPORTED.value,
            finished_at=now,
        )
        db.add(batch)
        db.flush()

        issues: dict[str, Issue] = {}
        for category_id, (title, description) in ISSUE_LABELS.items():
            issue = Issue(
                platform="demo",
                shop_id=DEMO_SHOP,
                product_id=DEMO_PRODUCT,
                category_id=category_id,
                title=title,
                description=description,
                status=IssueStatus.PROPOSED.value,
                created_by="ai",
            )
            db.add(issue)
            issues[category_id] = issue
        db.flush()

        for item in DEMO_COMMENTS:
            body = item["body"]
            review_date = (now - timedelta(days=item["days_ago"])).replace(
                hour=12, minute=0, second=0, microsecond=0
            )
            comment = Comment(
                platform="demo",
                shop_id=DEMO_SHOP,
                product_id=DEMO_PRODUCT,
                source_review_id=item["source"],
                batch_id=batch.id,
                rating=item["rating"],
                review_date=review_date,
                body=body,
                content_hash=_hash(body),
                analysis_status=item["status"].value,
                has_issue=item["has_issue"].value if item["has_issue"] else None,
            )
            db.add(comment)
            db.flush()

            if item["status"] == AnalysisStatus.QUEUED:
                db.add(
                    Job(
                        comment_id=comment.id,
                        batch_id=batch.id,
                        job_type=JobType.EXTRACT_ISSUES.value,
                        status=JobStatus.PENDING.value,
                    )
                )
                continue

            run = AnalysisRun(
                comment_id=comment.id,
                model_version="rule-baseline-1",
                prompt_version="v1",
                category_version="v1",
                input_hash=comment.content_hash,
                output_json={
                    "has_issue": comment.has_issue,
                    "issues": [],
                    "model_version": "rule-baseline-1",
                    "prompt_version": "v1",
                },
                status="succeeded",
            )
            db.add(run)
            db.flush()
            comment.current_analysis_run_id = run.id

            if item["issue"]:
                issue = issues[item["issue"]]
                evidence = body[: min(18, len(body))]
                start = body.find(evidence)
                db.add(
                    CommentIssue(
                        comment_id=comment.id,
                        issue_id=issue.id,
                        status=LinkStatus.SUGGESTED.value,
                        origin=LinkOrigin.AI.value,
                        evidence_text=evidence,
                        evidence_start=start,
                        evidence_end=start + len(evidence),
                        evidence_verified=True,
                        analysis_run_id=run.id,
                    )
                )

            db.add(
                Job(
                    comment_id=comment.id,
                    batch_id=batch.id,
                    job_type=JobType.EXTRACT_ISSUES.value,
                    status=JobStatus.COMPLETED.value,
                    attempts=1,
                    claimed_at=now,
                    completed_at=now,
                )
            )

        # A confirmed + resolved issue so the review board has history.
        usability = issues["usability"]
        usability.status = IssueStatus.CONFIRMED.value
        mismatch = issues["mismatch"]
        mismatch.status = IssueStatus.RESOLVED.value
        mismatch.resolved_at = now
        db.add(
            IssueAction(
                issue_id=usability.id,
                action=IssueActionType.CONFIRM.value,
                from_status=IssueStatus.PROPOSED.value,
                to_status=IssueStatus.CONFIRMED.value,
                operator="demo-operator",
                note="确认肩带 / 容量问题",
            )
        )
        db.add(
            IssueAction(
                issue_id=mismatch.id,
                action=IssueActionType.RESOLVE.value,
                from_status=IssueStatus.CONFIRMED.value,
                to_status=IssueStatus.RESOLVED.value,
                operator="demo-operator",
                note="已记录：与供应商核对色卡",
            )
        )

        db.commit()
        print(
            f"Seeded batch {batch.id}: {len(DEMO_COMMENTS)} comments, "
            f"{len(ISSUE_LABELS)} issues, 1 pending job."
        )


if __name__ == "__main__":
    main()
