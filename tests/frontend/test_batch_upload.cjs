const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const {File} = require('node:buffer');
const source = fs.readFileSync(path.join(__dirname, '../../frontend/batch-upload.js'), 'utf8');
function client(storage = new Map()) {
  const context = {window: {}, crypto: webcrypto, TextDecoder, TextEncoder,
    sessionStorage: {getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v)}};
  vm.runInNewContext(source, context);
  return context.window.BatchUpload;
}

test('CSV UTF-8/BOM and quoted newlines reach API unchanged; request key survives refresh', async () => {
  const storage = new Map(), api = client(storage);
  const text = 'shop_id,product_id,body\r\ns,p,"中文,\n换行"\r\n';
  const file = new File(['\uFEFF' + text], 'reviews.csv');
  const first = await api.prepare(file, ' demo ');
  assert.equal(first.csv_text, text);
  assert.equal(first.platform, 'demo');
  assert.equal(first.idempotency_key, (await api.prepare(file, 'demo')).idempotency_key);
  assert.equal(first.idempotency_key, (await client(storage).prepare(file, 'demo')).idempotency_key);
  assert.notEqual(first.idempotency_key, (await api.prepare(file, 'other')).idempotency_key);
  assert.notEqual(first.idempotency_key, (await api.prepare(new File([text + 'changed'], 'reviews.csv'), 'demo')).idempotency_key);
});

test('unsupported files and encoding fail before an upload request can be built', async () => {
  const api = client();
  for (const [file, platform, code] of [
    [null, 'demo', 'csv_required'], [new File(['x'], 'x.xlsx'), 'demo', 'csv_required'],
    [new File([], 'x.csv'), 'demo', 'empty_file'], [new File([' '], 'x.csv'), 'demo', 'empty_file'],
    [new File([new Uint8Array([0xff, 0xfe, 0x00])], 'x.csv'), 'demo', 'invalid_utf8'],
    [{name: 'x.csv', size: 10 * 1024 * 1024 + 1}, 'demo', 'file_too_large'],
    [new File(['x'], 'x.csv'), ' ', 'invalid_platform'],
  ]) await assert.rejects(api.prepare(file, platform), {message: code});
});

test('restricted session storage still allows stable retries within the page', async () => {
  const api = client({get() { throw Error(); }, set() { throw Error(); }});
  const file = new File(['body'], 'x.csv');
  assert.equal((await api.prepare(file, 'demo')).idempotency_key, (await api.prepare(file, 'demo')).idempotency_key);
});
