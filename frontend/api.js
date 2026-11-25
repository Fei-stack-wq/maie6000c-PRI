/* Same-origin API boundary. Keep backend contracts in this file. */
(function (root) {
  'use strict';
  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(path, {...options, signal: controller.signal,
        headers: {'Content-Type': 'application/json', ...options.headers}});
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload?.detail;
        const error = new Error(typeof detail === 'string' ? detail :
          detail?.code || (Array.isArray(detail) ? '请求字段不符合要求' : `HTTP ${response.status}`));
        error.detail = detail;
        error.status = response.status;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超时，请刷新确认状态；上传可能已被接收。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  function query(path, filters = {}) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== '' && value != null) params.set(key, value);
    });
    return request(`${path}?${params}`);
  }
  root.ReviewAPI = {
    upload: payload => request('/review-batches', {method: 'POST', body: JSON.stringify(payload)}),
    batch: id => request(`/review-batches/${encodeURIComponent(id)}`),
    errors: id => request(`/review-batches/${encodeURIComponent(id)}/errors`),
    comments: filters => query('/comments', filters),
    comment: id => request(`/comments/${encodeURIComponent(id)}`),
    issues: filters => query('/issues', filters),
    issue: id => request(`/issues/${encodeURIComponent(id)}`),
    stats: filters => query('/stats/summary', filters)
  };
})(typeof window !== 'undefined' ? window : globalThis);
