"""HTTP boundary for human review, with server-provided operator identity."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from services.api.app.reviews.commands import decide
from services.api.app.reviews.recheck import recheck
from services.api.app.reviews import issue_workflow, manual, structure
from services.api.app.reviews.reassign import list_targets, reassign
from services.api.app.reviews.queries import as_review, context_query, list_queue
from services.api.app.auth.access import review_operator
from services.common.db import get_db
from services.common.models import CommentIssue
from services.common.schemas import (
    ReviewDecisionRead, ReviewDecisionRequest, ReviewQueueRead, ReviewRead,
    ReassignRead, ReassignRequest, ReassignTargetsRead,
    ManualCommentQueueRead, ManualCommentRead, ManualLinkRead, ManualLinkRequest,
    IssueEvidencePage, IssueWorkflowActionRead, IssueWorkflowQueueRead,
    IssueWorkflowRead, IssueWorkflowRequest,
    IssueMergeRequest, IssueMergeTargetsRead, IssueSplitRequest, IssueStructureRead,
    ReviewRecheckRead, ReviewRecheckRequest,
)

router = APIRouter(tags=["Human review"])


@router.get("/review-queue", response_model=ReviewQueueRead)
def queue(
    status: Literal["pending", "reviewed", "needs_recheck"] = "pending",
    product_id: str | None = None, category_id: str | None = None,
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), operator: str = Depends(review_operator),
):
    items, total = list_queue(db, status, product_id, category_id, limit, offset)
    return ReviewQueueRead(items=items, total=total, limit=limit, offset=offset, operator=operator)


@router.get("/comment-issues/{link_id}", response_model=ReviewRead)
def detail(link_id: int, db: Session = Depends(get_db)):
    row = db.execute(context_query().where(CommentIssue.id == link_id)).one_or_none()
    if row is None:
        raise HTTPException(404, detail={"code": "link_not_found"})
    return as_review(db, row, history=True)


@router.post("/comment-issues/{link_id}/decisions", response_model=ReviewDecisionRead)
def decision(
    link_id: int, payload: ReviewDecisionRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return decide(db, link_id, payload, operator)


@router.post("/comment-issues/{link_id}/recheck", response_model=ReviewRecheckRead)
def recheck_link(
    link_id: int, payload: ReviewRecheckRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return recheck(db, link_id, payload, operator)


@router.get("/comment-issues/{link_id}/reassign-targets", response_model=ReassignTargetsRead)
def reassign_targets(
    link_id: int, q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_targets(db, link_id, q, limit, offset)


@router.post("/comment-issues/{link_id}/reassign", response_model=ReassignRead)
def reassign_link(
    link_id: int, payload: ReassignRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return reassign(db, link_id, payload, operator)


@router.get("/review-comments", response_model=ManualCommentQueueRead)
def manual_comments(
    verdict: Literal["attention", "all", "yes", "no", "unknown", "failed"] = "attention",
    product_id: str | None = None, q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), operator: str = Depends(review_operator),
):
    return manual.list_comments(db, verdict, product_id, q, limit, offset, operator)


@router.get("/review-comments/{comment_id}", response_model=ManualCommentRead)
def manual_detail(comment_id: str, db: Session = Depends(get_db)):
    return manual.detail(db, comment_id)


@router.get("/review-comments/{comment_id}/targets", response_model=ReassignTargetsRead)
def manual_targets(
    comment_id: str, q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return manual.targets(db, comment_id, q, limit, offset)


@router.post("/review-comments/{comment_id}/manual-links", response_model=ManualLinkRead)
def manual_add(
    comment_id: str, payload: ManualLinkRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return manual.add_link(db, comment_id, payload, operator)


@router.get("/review-issues", response_model=IssueWorkflowQueueRead)
def workflow_queue(
    status: Literal["all", "proposed", "confirmed", "resolved", "dismissed", "merged"] = "proposed",
    product_id: str | None = None, category_id: str | None = None,
    q: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0), db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return issue_workflow.list_issues(
        db, status, product_id, category_id, q, limit, offset, operator,
    )


@router.get("/review-issues/{issue_id}", response_model=IssueWorkflowRead)
def workflow_detail(issue_id: str, db: Session = Depends(get_db)):
    return issue_workflow.as_workflow(db, issue_workflow.get_issue(db, issue_id), history=True)


@router.get("/review-issues/{issue_id}/evidence", response_model=IssueEvidencePage)
def workflow_evidence(
    issue_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return issue_workflow.evidence_page(db, issue_id, limit, offset)


@router.post("/issues/{issue_id}/actions", response_model=IssueWorkflowActionRead)
def workflow_action(
    issue_id: str, payload: IssueWorkflowRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return issue_workflow.act(db, issue_id, payload, operator)


@router.get("/review-issues/{issue_id}/merge-targets", response_model=IssueMergeTargetsRead)
def merge_targets(
    issue_id: str, q: str = Query("", max_length=200), limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0), db: Session = Depends(get_db),
):
    return structure.targets(db, issue_id, q, limit, offset)


@router.post("/issues/{issue_id}/merge", response_model=IssueStructureRead)
def merge_issue(
    issue_id: str, payload: IssueMergeRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return structure.restructure(db, issue_id, payload, operator, "merge")


@router.post("/issues/{issue_id}/split", response_model=IssueStructureRead)
def split_issue(
    issue_id: str, payload: IssueSplitRequest, db: Session = Depends(get_db),
    operator: str = Depends(review_operator),
):
    return structure.restructure(db, issue_id, payload, operator, "split")
