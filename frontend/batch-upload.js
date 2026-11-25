(function () {
  'use strict';
  const keys = new Map();
  async function prepare(file, platform) {
    platform = String(platform || '').trim();
    if (!platform || platform.length > 32 || platform.includes('\0')) throw new Error('invalid_platform');
    if (!file || !/\.csv$/i.test(file.name)) throw new Error('csv_required');
    if (!file.size) throw new Error('empty_file');
    if (file.size > 10 * 1024 * 1024) throw new Error('file_too_large');
    if (file.name.length > 255) throw new Error('filename_too_long');
    let text;
    try { text = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer()); }
    catch (_) { throw new Error('invalid_utf8'); }
    if (!text.trim()) throw new Error('empty_file');
    const body = {platform, source_type: 'csv', filename: file.name, csv_text: text};
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(body)));
    const fingerprint = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    const storageKey = 'review-batch-request:' + fingerprint;
    let key = keys.get(storageKey);
    try { key = key || sessionStorage.getItem(storageKey); } catch (_) { /* memory fallback */ }
    if (!key) key = crypto.randomUUID();
    keys.set(storageKey, key);
    try { sessionStorage.setItem(storageKey, key); } catch (_) { /* memory fallback */ }
    return {...body, idempotency_key: key};
  }
  window.BatchUpload = {prepare};
})();
