(function () {
  'use strict';
  const modes = ['decisions', 'manual', 'issues'];
  const listKeys = {
    batches: ['platform', 'q', 'page', 'trash'],
    comments: ['batch_ids', 'product_keys', 'batch_id', 'product_id', 'analysis_status', 'has_issue', 'q', 'page'],
    issues: ['batch_ids', 'product_keys', 'product_id', 'status', 'category_id', 'q', 'page']
  };
  const defaults = {batches: {platform: ''}, comments: {batch_id: '', analysis_status: '', has_issue: ''}, issues: {status: 'all', category_id: ''}};
  function filters(route, params) {
    if (!listKeys[route]) return {};
    const result = {...defaults[route], product_id: '', q: '', page: '1'};
    for (const key of listKeys[route] || []) {
      if (params.has(key)) result[key] = params.get(key).trim().slice(0, key === 'q' ? 200 : key === 'batch_ids' ? 8000 : key === 'product_keys' ? 80000 : 128);
    }
    if (!/^[1-9]\d{0,5}$/.test(result.page)) result.page = '1';
    const enums = route === 'comments' ? {
      analysis_status: ['', 'received', 'queued', 'analyzing', 'analyzed', 'failed'],
      has_issue: ['', 'yes', 'no', 'unknown']
    } : route === 'issues' ? {status: ['all', 'proposed', 'confirmed', 'resolved', 'dismissed', 'merged'],
      category_id: ['', 'quality', 'logistics', 'mismatch', 'usability', 'other']} : {};
    if (route === 'batches') { result.platform = result.platform.slice(0, 32); if (result.trash !== '1') result.trash = ''; }
    if (route === 'comments') result.batch_id = result.batch_id.slice(0, 36);
    for (const [key, values] of Object.entries(enums)) {
      if (!values.includes(result[key])) result[key] = defaults[route][key];
    }
    return result;
  }
  function href(route, id, values = {}) {
    const params = new URLSearchParams();
    for (const key of listKeys[route] || []) {
      const value = values[key];
      if (value && !(key === 'page' && String(value) === '1') && !(key === 'status' && value === 'all')) {
        params.set(key, value);
      }
    }
    return `#/${route}${id ? '/' + encodeURIComponent(id) : ''}${params.size ? '?' + params : ''}`;
  }
  function parse(hash, allowReturn = true) {
    try {
      const raw = String(hash || '');
      if (!raw.startsWith('#/') || raw.length > 250000) return null;
      const split = raw.indexOf('?'), path = split < 0 ? raw.slice(2) : raw.slice(2, split);
      const parts = path.replace(/\/$/, '').split('/');
      const route = parts[0], id = parts[1] ? decodeURIComponent(parts[1]) : null;
      if (!['batches', 'comments', 'issues', 'reviews', 'about'].includes(route) || parts.length > 2) return null;
      if (id && (!['batches', 'comments', 'issues'].includes(route) || !/^[A-Za-z0-9_-]{1,64}$/.test(id))) return null;
      const params = new URLSearchParams(split < 0 ? '' : raw.slice(split + 1));
      const mode = modes.includes(params.get('mode')) ? params.get('mode') : 'decisions';
      const record = params.get('id');
      const recordId = record && (mode === 'decisions' ? /^[1-9]\d{0,17}$/ : /^[A-Za-z0-9_-]{1,64}$/).test(record) ? record : null;
      return {route, detailId: id, filters: filters(route, params), mode, recordId,
        returnTo: allowReturn ? safeReturn(params.get('return_to')) : ''};
    } catch (_) { return null; }
  }
  function safeReturn(value) {
    const parsed = parse(value, false);
    return parsed && ['comments', 'issues'].includes(parsed.route)
      ? href(parsed.route, parsed.detailId, parsed.filters) : '';
  }
  function reviewHref(mode = 'decisions', id, returnTo = '') {
    const params = new URLSearchParams({mode});
    if (id) params.set('id', id);
    const back = safeReturn(returnTo);
    if (back) params.set('return_to', back);
    return '#/reviews?' + params;
  }
  window.ProductRoutes = {parse, href, reviewHref, safeReturn};
})();
