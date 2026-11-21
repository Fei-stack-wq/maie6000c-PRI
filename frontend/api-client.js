(function () {
  'use strict';
  let session = null;
  window.ReviewAPI = {
    setSession(value) { session = value; },
    get canReview() { return session?.can_review === true; },
    identity(operator) {
      return session?.mode === 'demo' ? `真实数据库 · 演示身份：${operator}（非登录认证）` :
        `当前账号：${session?.username || operator} · ${this.canReview ? '复核员' : '只读成员'}`;
    },
    async request(path, body, options = {}) {
      const requestSession = session;
      const headers = body ? { 'Content-Type': 'application/json', 'X-Review-Request': '1' } : {};
      if (body && session?.csrf_token) headers['X-CSRF-Token'] = session.csrf_token;
      const response = await fetch(path, {
        method: body ? 'POST' : 'GET',
        credentials: 'same-origin', cache: 'no-store', headers,
        body: body ? JSON.stringify(body) : undefined
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.detail?.code || 'request_failed');
        error.status = response.status;
        error.detail = data.detail;
        if (session === requestSession && path !== '/auth/login' &&
            (response.status === 401 || response.status === 403)) {
          session = null;
          window.dispatchEvent(new Event('review-session-expired'));
        }
        throw error;
      }
      if (options.page) {
        const header = response.headers.get('X-Total-Count');
        if (header === null || !/^\d+$/.test(header) || !Array.isArray(data)) {
          throw new Error('invalid_page_response');
        }
        return {items: data, total: Number(header)};
      }
      return data;
    }
  };
})();
