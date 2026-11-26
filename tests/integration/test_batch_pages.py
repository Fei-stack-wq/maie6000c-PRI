"""Real upload/list/progress contracts, including updates of existing sources."""
import pytest

from services.common.models import Comment, IngestionBatch, Job, utcnow


def upload(client, body="shop,product,body\n", **kwargs):
    return client.post('/review-batches', json={
        'platform': 'demo', 'filename': 'test.csv',
        'csv_text': 'shop_id,product_id,body\n' + body, **kwargs,
    })


def test_batch_listing_filters_totals_and_stable_paging(client, session_factory):
    ids = [upload(client, filename=name, platform=platform).json()['batch_id']
           for name, platform in [('50%_off.csv', 'demo'), ('50%_off2.csv', 'demo'),
                                  ('500xoff.csv', 'demo'), ('50%_off.csv', 'other')]]
    with session_factory() as db:
        stamp = utcnow()
        for batch in db.query(IngestionBatch):
            batch.created_at = stamp
        db.commit()
    pages = [client.get('/review-batches', params={
        'q': '50%_', 'platform': 'demo', 'offset': offset, 'limit': 1,
    }) for offset in range(3)]
    assert all(r.status_code == 200 and r.headers['x-total-count'] == '2' for r in pages)
    assert [r.json()[0]['id'] for r in pages[:2]] == sorted(ids[:2])
    assert pages[2].json() == []
    assert pages[0].headers['cache-control'] == 'no-store'
    assert client.get('/review-batches', params={'q': 'x' * 201}).status_code == 422


def test_partial_csv_import_and_batch_comment_filter(client):
    response = upload(client, 's,p,"引号内,逗号和\n换行"\ns,p,good,extra\n,p,invalid\n')
    assert response.status_code == 202
    b = response.json()
    assert (b['accepted_rows'], b['invalid_rows'], b['declared_rows']) == (1, 2, 3)
    errors = client.get(f"/review-batches/{b['batch_id']}/errors").json()
    assert [e['code'] for e in errors] == ['extra_columns', 'required']
    upload(client, 's,other,another comment\n')
    comments = client.get('/comments', params={'batch_id': b['batch_id']})
    assert comments.headers['x-total-count'] == '1'
    assert comments.json()[0]['body'] == '引号内,逗号和\n换行'
    detail = client.get(f"/review-batches/{b['batch_id']}").json()
    assert detail['batch']['file_ref'] == 'test.csv' and detail['current_rows'] == 1
    assert detail['waiting_rows'] == 1 and detail['analysis_coverage'] == 0


@pytest.mark.parametrize(('csv', 'code'), [
    ('shop_id,product_id,body,body\ns,p,x,y\n', 'invalid_header'),
    ('shop_id,product_id,body,\x00\ns,p,x,y\n', 'invalid_header'),
    ('shop_id,product_id,body\ns,p,good\ns,p,"unterminated', 'invalid_csv'),
    ('shop_id,product_id,body\n', 'empty_csv'),
    ('product_id,body\np,b\n', 'missing_columns'),
    ('shop_id,product_id,body\n' + 's,p,good\n' * 5001, 'too_many_rows'),
    ('shop_id,product_id,body\n' + 'x' * (10 * 1024 * 1024), 'file_too_large'),
])
def test_malformed_csv_rejects_entire_batch_without_partial_import(client, csv, code):
    result = upload(client, csv_text=csv, idempotency_key='retry-rejected')
    assert result.status_code == 422
    assert code in [e['code'] for e in result.json()['detail']['errors']]
    batch_id = result.json()['detail']['batch_id']
    assert client.get('/comments').json() == []
    assert client.get(f'/review-batches/{batch_id}').json()['status'] == 'rejected'
    replay = upload(client, csv_text=csv, idempotency_key='retry-rejected').json()
    assert replay['batch_id'] == batch_id and replay['status'] == 'rejected'
    assert client.get('/review-batches').headers['x-total-count'] == '1'


def test_long_source_identifier_and_nul_are_row_errors(client):
    result = upload(client, csv_text='shop_id,product_id,body,source_review_id\n'
                    + 's,p,valid,one\ns,p,too long,' + 'x' * 129 + '\ns,p,bad\x00body,two\n')
    assert result.status_code == 202
    assert result.json()['accepted_rows'] == 1 and result.json()['invalid_rows'] == 2


def test_same_key_with_changed_payload_conflicts_instead_of_replaying_wrong_batch(client):
    first = upload(client, idempotency_key='retry-upload')
    replay = upload(client, idempotency_key='retry-upload')
    changed = upload(client, body='s,p,new body', idempotency_key='retry-upload')
    assert first.json()['batch_id'] == replay.json()['batch_id']
    assert changed.status_code == 409
    assert changed.json()['detail']['code'] == 'idempotency_conflict'
    assert client.get('/review-batches').headers['x-total-count'] == '1'



def test_repeated_source_has_independent_batch_coverage(client, session_factory):
    header = 'shop_id,product_id,source_review_id,body\n'
    first = upload(client, csv_text=header + 's,p,r,original').json()['batch_id']
    second = upload(client, csv_text=header + 's,p,r,updated').json()['batch_id']
    changed = client.get(f'/review-batches/{second}').json()
    assert changed['batch']['accepted_rows'] == 1 and changed['batch']['duplicate_rows'] == 0
    assert changed['job_count'] == changed['current_rows'] == changed['waiting_rows'] == 1
    with session_factory() as db:
        db.query(Comment).filter_by(batch_id=second).one().analysis_status = 'analyzed'
        db.query(Job).filter_by(batch_id=second).one().status = 'completed'
        db.commit()
    done = client.get(f'/review-batches/{second}').json()
    assert done['status'] == 'completed' and done['analysis_coverage'] == 1
    assert client.get(f'/review-batches/{first}').json()['analysis_coverage'] == 0
    assert client.get('/comments', params={'batch_id': first}).json()[0]['body'] == 'original'


def test_failed_job_does_not_appear_as_success_when_source_moved(client, session_factory):
    header = 'shop_id,product_id,source_review_id,body\n'
    original = upload(client, csv_text=header + 's,p,r,original').json()['batch_id']
    upload(client, csv_text=header + 's,p,r,updated')
    with session_factory() as db:
        db.query(Job).filter_by(batch_id=original).one().status = 'failed'
        db.query(Comment).filter_by(batch_id=original).one().analysis_status = 'failed'
        db.commit()
    detail = client.get(f'/review-batches/{original}').json()
    assert detail['current_rows'] == 1 and detail['failed_jobs'] == 1
    assert detail['status'] == 'partially_failed'
