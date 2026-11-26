const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../../frontend');

function ui(language = 'zh', request = async () => ({})) {
  const context = {window: {}, I18n: {language, locale: language === 'en' ? 'en-US' : 'zh-CN'},
    ReviewAPI: {request}, URLSearchParams};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'workbench-ui.js'), 'utf8'), context);
  return context.window.WorkbenchUI;
}

test('catalog loader covers every page rather than the first 200 options', async () => {
  const seen = [];
  const tool = ui('en', async path => {
    const url = new URL(path, 'http://local');
    const offset = Number(url.searchParams.get('offset'));
    seen.push(offset);
    return {total: 405, items: Array.from({length: Math.min(200, 405 - offset)}, (_, n) => ({id: String(offset + n)}))};
  });
  const rows = await tool.allOptions('/catalog/batches');
  assert.equal(rows.length, 405);
  assert.deepEqual(seen, [0, 200, 400]);
  assert.equal(new Set(rows.map(row => row.id)).size, 405);
});

test('an incomplete catalog fails visibly rather than silently losing options', async () => {
  const tool = ui('en', async () => ({total: 10, items: []}));
  await assert.rejects(tool.allOptions('/catalog/products'), /incomplete_catalog/);
});

test('scope keys distinguish platform/store and reject malformed selections', () => {
  const tool = ui();
  const products = [['amazon', 'store-a', 'same'], ['amazon', 'store-b', 'same']];
  const selected = tool.parseSelection({batch_ids: 'one,two,one', product_keys: JSON.stringify(products)});
  assert.deepEqual(Array.from(selected.batches), ['one', 'two']);
  assert.equal(selected.products.length, 2);
  assert.throws(() => tool.parseSelection({product_keys: '[["partial"]]'}), /invalid_scope/);
  assert.deepEqual(Array.from(tool.parseSelection({batch_id: 'legacy'}).batches), ['legacy']);
});

test('multi-batch/product filters survive details, review return links and refresh parsing', () => {
  const context = {window: {}, URLSearchParams};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'product-routes.js'), 'utf8'), context);
  const routes = context.window.ProductRoutes;
  const values = {batch_ids: Array.from({length: 12}, (_, n) => 'batch-' + n).join(','),
    product_keys: JSON.stringify([['平台 &', '店铺/一', '同编号'], ['another', 'store', 'same']]), page: '2'};
  const link = routes.href('issues', null, values);
  const review = routes.parse(routes.reviewHref('decisions', 123, link));
  assert.equal(routes.parse(review.returnTo).filters.batch_ids, values.batch_ids);
  assert.equal(routes.parse(review.returnTo).filters.product_keys, values.product_keys);
  assert.equal(routes.parse('#/batches?trash=1').filters.trash, '1');
});

test('category labels are bilingual and user content remains escaped without translation', () => {
  const chinese = ui(), english = ui('en');
  assert.match(chinese.badge('quality'), /质量/);
  assert.match(english.badge('quality'), /Quality/);
  assert.equal(english.esc('质量 <script>'), '质量 &lt;script&gt;');
});

test('permanent deletion uses DELETE with CSRF and handles the empty 204 response', async () => {
  const calls = [];
  const context = {window: {}, I18n: {t: s => s, html: () => ''},
    fetch: async (path, options) => {
      calls.push({path, options});
      return {ok: true, status: 204, json() { throw Error('204 has no JSON body'); }};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(root, 'api-client.js'), 'utf8'), context);
  const api = context.window.ReviewAPI;
  api.setSession({csrf_token: 'csrf-token', can_review: true});
  assert.equal(await api.request('/review-batches/test?permanent=true', undefined, {method: 'DELETE'}), null);
  assert.equal(calls[0].options.method, 'DELETE');
  assert.equal(calls[0].options.headers['X-CSRF-Token'], 'csrf-token');
  assert.equal(calls[0].options.headers['X-Review-Request'], '1');
});
