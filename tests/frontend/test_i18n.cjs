const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const frontend = path.join(__dirname, '../../frontend');

function client({saved, search = '', storageBlocked = false, busy = false, confirm = true} = {}) {
  const events = {}, selectorEvents = {}, assigned = [], notices = [], writes = [], dialogs = [];
  const feedback = {set textContent(text) { notices.push(text); }};
  const selector = {value: '', focus() {}, addEventListener: (type, fn) => selectorEvents[type] = fn};
  const document = {
    documentElement: {}, title: '评论', body: {appendChild() {}},
    createTreeWalker: () => ({nextNode: () => null}), querySelectorAll: () => [],
    getElementById: id => id === 'ui-language' ? selector : feedback, querySelector: () => busy ? {} : null,
    createElement() {
      const dialog = {setAttribute() {}, remove() {}, showModal() {},
        addEventListener(type, fn) { this.onClose = fn; },
        close(value) { this.returnValue = value; this.onClose(); }};
      dialogs.push(dialog); return dialog;
    },
    addEventListener: (type, fn) => events[type] = fn
  };
  const window = {
    location: {search, href: 'http://localhost:8000/ui/' + search + '#/comments/c-1?product_id=bag',
      assign: url => assigned.push(url)},
    alert: text => notices.push(text), confirm: text => { notices.push(text); return confirm; }
  };
  const context = {window, document, NodeFilter: {SHOW_TEXT: 4}, URLSearchParams, URL,
    localStorage: {getItem() { if (storageBlocked) throw Error(); return saved; },
      setItem(key, value) { if (storageBlocked) throw Error(); writes.push([key, value]); }}};
  for (const file of ['i18n-en.js', 'i18n.js']) vm.runInNewContext(fs.readFileSync(path.join(frontend, file), 'utf8'), context);
  return {i18n: window.I18n, context, document, selector, assigned, notices, writes, events, dialogs,
    change(value) { selector.value = value; selectorEvents.change(); }};
}

test('language defaults to Chinese; saved preference and valid URL override work without storage', () => {
  assert.equal(client().i18n.language, 'zh');
  assert.equal(client({saved: 'en'}).document.title, 'Reviews');
  assert.equal(client({saved: 'en', search: '?lang=zh'}).i18n.language, 'zh');
  assert.equal(client({saved: 'en', search: '?lang=invalid'}).i18n.language, 'en');
  const english = client({search: '?lang=en', storageBlocked: true});
  assert.equal(english.document.documentElement.lang, 'en');
  assert.equal(english.i18n.locale, 'en-US');
});

test('static copy and accessible attributes translate while values and routes remain unchanged', () => {
  const {i18n} = client({saved: 'en'});
  assert.equal(i18n.t('  待复核  '), '  To review  ');
  assert.equal(i18n.t('<input value="质量" placeholder="输入问题标题" name="q">'),
    '<input value="质量" placeholder="Enter an issue title" name="q">');
  assert.equal(i18n.t('/review-links/accepted'), '/review-links/accepted');
  assert.equal(i18n.t('A backend diagnostic without a translation'), 'A backend diagnostic without a translation');
});

test('dynamic review text, issue titles, evidence and placeholder-like content are never translated', () => {
  const {i18n} = client({saved: 'en'});
  const review = '质量 待复核 __rl_slot_0__ <span title="评论">原始证据</span>';
  assert.equal(i18n.html`<h2>当前评论原文</h2><p>${review}</p>`,
    '<h2>Current review text</h2><p>' + review + '</p>');
  assert.equal(i18n.html`当前：${'质量'}`, 'Current: 质量');
  assert.equal(i18n.html`<input title="${'评论'}" value="${review}">`,
    '<input title="评论" value="' + review + '">');
  const chinese = client().i18n;
  assert.equal(chinese.html`当前：${review}`, '当前：' + review);
});

test('all translated phrases preserve their interpolation slots', () => {
  const {i18n, context} = client({saved: 'en'});
  const slots = s => [...s.matchAll(/__rl_slot_\d+__/g)].map(m => m[0]).sort();
  assert.ok(Object.keys(context.window.ReviewLensEnglish).length > 600);
  for (const [original, translated] of Object.entries(context.window.ReviewLensEnglish)) {
    assert.deepEqual(slots(translated), slots(original), original);
    assert.equal(i18n.t(original), translated, original);
    assert.doesNotMatch(translated, /[\u3400-\u9fff]/, original);
  }
});

test('language switch remembers selection and preserves the current route and filters', () => {
  const page = client();
  page.change('en');
  assert.deepEqual(page.writes, [['reviewlens-language', 'en']]);
  assert.equal(page.assigned[0], 'http://localhost:8000/ui/?lang=en#/comments/c-1?product_id=bag');
  const blocked = client({storageBlocked: true});
  blocked.change('en');
  assert.equal(new URL(blocked.assigned[0]).searchParams.get('lang'), 'en');
});

test('pending operations and unsaved form cancellation prevent a language reload', () => {
  const busy = client({saved: 'en', busy: true});
  busy.change('zh');
  assert.equal(busy.assigned.length, 0);
  assert.match(busy.notices[0], /Wait for the current operation/);
  const dirty = client({saved: 'en', confirm: false});
  const form = {id: 'manual-add', isConnected: true};
  dirty.events.input({target: {closest: () => form}});
  dirty.change('zh');
  dirty.dialogs[0].close('cancel');
  assert.equal(dirty.assigned.length, 0);
  assert.match(dirty.dialogs[0].innerHTML, /Unsaved entries/);
  dirty.change('zh');
  dirty.dialogs[1].close('switch');
  assert.equal(dirty.assigned.length, 1);
  form.isConnected = false;
  dirty.change('zh');
  assert.equal(dirty.assigned.length, 2);
});

test('API identity labels translate without changing operators or request bodies', async () => {
  const page = client({saved: 'en'}), {context} = page;
  context.I18n = page.i18n;
  context.CustomEvent = class { constructor(type) { this.type = type; } };
  context.window.dispatchEvent = () => {};
  const calls = [];
  context.fetch = async (url, options) => { calls.push([url, options]); return {ok: true, json: async () => ({saved: true})}; };
  vm.runInNewContext(fs.readFileSync(path.join(frontend, 'api-client.js'), 'utf8'), context);
  const api = context.window.ReviewAPI;
  api.setSession({mode: 'demo', can_review: true});
  assert.equal(api.identity('质量'), 'Live database · Demo identity: 质量 (not authenticated)');
  const body = {decision: 'accepted', evidence_quote: '质量', note: '待复核'};
  await api.request('/review-links/1/decision', body);
  assert.deepEqual(JSON.parse(calls[0][1].body), body);
});

test('translated templates survive new interpolations before an existing phrase', () => {
  const {i18n} = client({saved: 'en'});
  assert.equal(i18n.t('评分：__rl_slot_31__ · 评论时间：__rl_slot_32__'),
    'Rating: __rl_slot_31__ · Review date: __rl_slot_32__');
});
