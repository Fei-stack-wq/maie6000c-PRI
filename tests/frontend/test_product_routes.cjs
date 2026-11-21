const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = {window: {}, URLSearchParams};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../frontend/product-routes.js'), 'utf8'), context);
const routes = context.window.ProductRoutes;

test('comment filters survive list → detail → review → return URLs', () => {
  const filter = {product_id: 'bag & 1', q: '拉链 50%_', page: '2', analysis_status: 'analyzed', has_issue: 'yes'};
  const detail = routes.href('comments', 'comment-1', filter);
  const review = routes.parse(routes.reviewHref('decisions', 123, detail));
  assert.equal(review.mode, 'decisions');
  assert.equal(review.recordId, '123');
  assert.equal(review.returnTo, detail);
  assert.equal(routes.parse(review.returnTo).filters.q, filter.q);
  assert.equal(routes.parse(review.returnTo).filters.page, '2');
  assert.equal(routes.parse(detail).detailId, 'comment-1');
});

test('refreshable manual and group deep links keep their identifiers', () => {
  for (const mode of ['manual', 'issues']) {
    const parsed = routes.parse(routes.reviewHref(mode, 'a-b-c'));
    assert.equal(parsed.recordId, 'a-b-c');
    assert.equal(parsed.mode, mode);
  }
  assert.equal(routes.parse('#/issues/issue-1?status=merged').filters.status, 'merged');
  assert.equal(routes.parse('#/reviews').mode, 'decisions');
  assert.equal(routes.parse('#/batches').route, 'batches');
  assert.equal(routes.parse('#/about').route, 'about');
});

test('malformed paths and unsafe return targets cannot become links', () => {
  for (const hash of ['#/comments/%', '#/issues/a/b', '#/comments/%3Cscript%3E', '#/reviews/123', 'https://evil.test']) {
    assert.equal(routes.parse(hash), null);
  }
  for (const target of ['javascript:alert(1)', 'https://evil.test', '//evil.test', '#/about', '#/reviews']) {
    assert.equal(routes.safeReturn(target), '');
  }
  const parsed = routes.parse('#/reviews?mode=issues&id=x&return_to=https%3A%2F%2Fevil.test');
  assert.equal(parsed.returnTo, '');
});

test('invalid filters and page numbers normalize without crashing or exposing arbitrary parameters', () => {
  const parsed = routes.parse('#/comments?q=x&page=-3&analysis_status=bogus&has_issue=bogus');
  assert.equal(parsed.filters.page, '1');
  assert.equal(parsed.filters.analysis_status, '');
  assert.equal(parsed.filters.has_issue, '');
  assert.equal(routes.parse('#/comments?q=' + 'x'.repeat(201)).filters.q.length, 200);
  assert.equal(routes.safeReturn('#/issues/i?status=merged&return_to=javascript%3Abad&extra=ignored'), '#/issues/i?status=merged');
  assert.equal(routes.href('comments', null, {q: 'all', product_id: 'all'}), '#/comments?product_id=all&q=all');
});

test('batch details and batch-filtered comment/review URLs survive navigation', () => {
  const batch = routes.href('batches', 'batch-123', {platform: 'demo', q: '50%_', page: '3'});
  assert.equal(routes.parse(batch).detailId, 'batch-123');
  assert.equal(routes.parse(batch).filters.page, '3');
  const comment = routes.href('comments', 'comment-123', {batch_id: 'batch-123', page: '2'});
  const review = routes.parse(routes.reviewHref('manual', 'comment-123', comment));
  assert.equal(routes.parse(review.returnTo).filters.batch_id, 'batch-123');
  assert.equal(routes.parse(review.returnTo).filters.page, '2');
});
