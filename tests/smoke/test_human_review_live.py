"""Explicit local session-mode acceptance against a running API, Worker and AI.

Set SMOKE_HUMAN_REVIEW=1, SMOKE_BASE_URL and reviewer/viewer credentials to opt in.
Each run imports new UUID-scoped fixtures; it never rewrites pre-existing reviews.
"""
import csv
import io
import os
import time
import uuid
from urllib.parse import urlparse

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_session_upload_review_manual_followup_and_source_recheck():
    if os.getenv('SMOKE_HUMAN_REVIEW') != '1':
        pytest.skip('Set SMOKE_HUMAN_REVIEW=1 to run local authenticated acceptance')
    base = os.environ['SMOKE_BASE_URL']
    assert urlparse(base).hostname in {'127.0.0.1', 'localhost', '::1'}
    product = 'review-e2e-' + uuid.uuid4().hex[:12]
    original = 'The zipper is broken. Delivery was late.'
    updated = 'The zipper is still broken. Delivery was late.'
    other = 'The support team never replied about my warranty.'

    def get(client, path):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code, response.text)
        return response.json()

    def post(client, path, payload, expected=200):
        response = client.post(path, json=payload)
        assert response.status_code == expected, (path, response.status_code, response.text)
        return response.json()

    def login(client, prefix):
        data = post(client, '/auth/login', {
            'username': os.environ[prefix + '_USERNAME'],
            'password': os.environ[prefix + '_PASSWORD'],
        })
        assert data['mode'] == 'session'
        client.headers['X-CSRF-Token'] = data['csrf_token']

    def upload(client, body):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['shop_id', 'product_id', 'source_review_id', 'body'])
        writer.writerows([['smoke-shop', product, 'source-1', body],
                          ['smoke-shop', product, 'source-2', other]])
        payload = {'platform': 'human-review-smoke', 'filename': 'acceptance.csv',
                   'csv_text': stream.getvalue(), 'idempotency_key': str(uuid.uuid4())}
        batch = post(client, '/review-batches', payload, 202)['batch_id']
        assert post(client, '/review-batches', payload, 202)['batch_id'] == batch
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            progress = get(client, '/review-batches/' + batch)
            if progress['status'] == 'completed':
                return batch
            assert progress['status'] != 'partially_failed', progress
            time.sleep(0.2)
        pytest.fail('Worker did not complete the imported comments within 30 seconds')

    headers = {'X-Review-Request': '1', 'Origin': base.rstrip('/')}
    with httpx.Client(base_url=base, headers=headers, timeout=10) as reviewer, \
            httpx.Client(base_url=base, headers=headers, timeout=10) as viewer:
        assert reviewer.get('/comments').status_code == 401
        login(reviewer, 'SMOKE_REVIEW')
        batch_id = upload(reviewer, original)
        comments = get(reviewer, '/comments?batch_id=' + batch_id)
        assert len(comments) == 2 and all(c['analysis_status'] == 'analyzed' for c in comments)
        primary = next(c for c in comments if c['source_review_id'] == 'source-1')
        supplemental = next(c for c in comments if c['source_review_id'] == 'source-2')
        detail = get(reviewer, '/review-comments/' + primary['id'])
        item = next(i for i in detail['links'] if i['issue']['category_id'] == 'quality')
        link_id, issue_id = item['link']['id'], item['issue']['id']
        decision = {'request_id': str(uuid.uuid4()), 'expected_token': item['token'],
                    'decision': 'accept', 'note': 'Authenticated live acceptance fixture'}
        saved = post(reviewer, f'/comment-issues/{link_id}/decisions', decision)
        assert saved == post(reviewer, f'/comment-issues/{link_id}/decisions', decision)
        for action, status in [('confirm', 'confirmed'), ('follow_up', 'confirmed'),
                               ('resolve', 'resolved'), ('reopen', 'proposed')]:
            group = get(reviewer, '/review-issues/' + issue_id)
            result = post(reviewer, f'/issues/{issue_id}/actions', {
                'request_id': str(uuid.uuid4()), 'expected_token': group['token'],
                'action': action, 'note': 'Authenticated acceptance: ' + action,
            })
            assert result['status'] == status
        comment = get(reviewer, '/review-comments/' + supplemental['id'])
        manual = post(reviewer, f"/review-comments/{supplemental['id']}/manual-links", {
            'request_id': str(uuid.uuid4()), 'expected_token': comment['token'],
            'new_issue': {'title': 'Warranty support did not reply', 'category_id': 'other'},
            'evidence_text': other, 'evidence_start': 0, 'evidence_end': len(other),
            'note': 'Human evidence acceptance fixture',
        })
        assert get(reviewer, f"/comment-issues/{manual['link_id']}")['link']['origin'] == 'human'
        upload(reviewer, updated)
        stale = get(reviewer, f'/comment-issues/{link_id}')
        assert stale['needs_recheck'] and stale['link']['status'] == 'accepted'
        assert stale['evidence_body'] == original
        quote = 'The zipper is still broken'
        post(reviewer, f'/comment-issues/{link_id}/recheck', {
            'request_id': str(uuid.uuid4()), 'expected_token': stale['token'],
            'decision': 'accept', 'evidence_text': quote, 'evidence_start': 0,
            'evidence_end': len(quote), 'note': 'Rechecked changed source in live acceptance',
        })
        refreshed = get(reviewer, f'/comment-issues/{link_id}')
        assert not refreshed['needs_recheck'] and len(refreshed['actions']) == 2
        assert refreshed['link']['decided_by'] == os.environ['SMOKE_REVIEW_USERNAME']
        assert len(get(reviewer, '/review-issues/' + issue_id)['actions']) == 5
        login(viewer, 'SMOKE_VIEWER')
        assert get(viewer, f'/comment-issues/{link_id}')['link']['status'] == 'accepted'
        assert viewer.post(f'/comment-issues/{link_id}/decisions', json=decision).status_code == 403
        post(reviewer, '/auth/logout', {})
        assert reviewer.get('/review-queue').status_code == 401
