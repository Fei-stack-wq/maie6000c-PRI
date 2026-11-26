from sqlalchemy import select

from services.common.models import Comment, CommentIssue, Issue


def upload(client, body):
    response = client.post('/review-batches', json={
        'platform': 'test', 'source_type': 'csv',
        'comments': [{'platform': 'test', 'source_review_id': 'same-source', 'shop_id': 'shop',
                      'product_id': 'shoe', 'body': body}],
    })
    assert response.status_code == 202, response.text
    return response.json()['batch_id']


def test_uploads_keep_separate_text_jobs_groups_and_decisions(client, session_factory,
                                                             worker_setup, ai_response):
    first = upload(client, '拉链坏了。')
    second = upload(client, '拉链坏了，而且快递慢。')
    third = upload(client, '拉链坏了。')
    with session_factory() as db:
        rows = db.scalars(select(Comment).order_by(Comment.created_at)).all()
        assert len(rows) == 3
        assert [row.batch_id for row in rows] == [first, second, third]
        assert rows[0].body == rows[2].body == '拉链坏了。'
        assert rows[1].body == '拉链坏了，而且快递慢。'
    for _ in range(3):
        assert worker_setup.run_once() == 'completed'
    with session_factory() as db:
        for group in db.scalars(select(Issue)):
            comment_batches = set(db.scalars(select(Comment.batch_id).join(
                CommentIssue, CommentIssue.comment_id == Comment.id).where(
                CommentIssue.issue_id == group.id)))
            assert comment_batches == {group.batch_id}


def test_reassignment_never_offers_another_batch(client, session_factory, worker_setup,
                                                ai_response):
    first = upload(client, '拉链坏了。')
    upload(client, '拉链坏了。')
    worker_setup.run_once()
    worker_setup.run_once()
    with session_factory() as db:
        link = db.scalar(select(CommentIssue).join(Comment).where(Comment.batch_id == first))
        identity = link.id
    response = client.get(f'/comment-issues/{identity}/reassign-targets')
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 0
