(function () {
  'use strict';
  const errors = {
    invalid_credentials: I18n.t('账号或密码不正确，或账号已停用。'),
    invalid_login: I18n.t('请填写有效账号和密码。'),
    login_rate_limited: I18n.t('尝试次数过多，请在 15 分钟后重试。'),
    csrf_failed: I18n.t('会话校验失败，请重新登录。')
  };
  let cleanup = () => {};
  window.ReviewAuth = {
    unmount() { cleanup(); cleanup = () => {}; },
    mount(root, mountWorkspace) {
      cleanup();
      root.innerHTML = '<div id="review-auth-root"></div>';
      const host = root.firstElementChild;
      let identity = null, serial = 0, timer = null, loading = false;
      const connected = () => host.isConnected;
      const message = text => { const p = host.querySelector('#auth-message'); if (p) p.textContent = text; };
      function notifyTabs() {
        try { localStorage.setItem('review-session-event', String(Date.now())); } catch (_) { /* optional */ }
      }
      function showLogin(note = '') {
        ++serial;
        identity = null;
        ReviewAPI.setSession(null);
        host.innerHTML = I18n.html`<section class="panel review-login-panel">
          <h2>登录复核工作台</h2><p>使用分配给你的账号查看评论、证据与操作历史。</p>
          <form id="review-login" class="human-review-manual-form">
            <label for="login-username">账号</label>
            <input id="login-username" name="username" autocomplete="username" maxlength="64" required autocapitalize="none" spellcheck="false">
            <label for="login-password">密码</label>
            <input id="login-password" name="password" type="password" autocomplete="current-password" maxlength="256" required>
            <button class="btn btn-primary" type="submit">登录</button>
          </form><p id="auth-message" role="status" aria-live="polite"></p>
          <p>账号由项目维护者分配；需要开通或重置密码时，请联系维护者。</p></section>`;
        message(note);
        host.querySelector('#review-login').addEventListener('submit', async event => {
          event.preventDefault();
          if (loading) return;
          ++serial;
          loading = true;
          const form = event.currentTarget, data = new FormData(form);
          form.inert = true; message(I18n.t('正在登录…'));
          try {
            const next = await ReviewAPI.request('/auth/login', {
              username: data.get('username'), password: data.get('password')
            });
            if (connected()) { showWorkspace(next); notifyTabs(); }
          } catch (error) {
            if (connected()) message(errors[error.message] || I18n.t('连接失败，请检查服务后重试。'));
          } finally {
            form.querySelector('#login-password').value = '';
            form.inert = false; loading = false;
          }
        });
      }
      function showWorkspace(next, note = '') {
        ++serial;
        identity = next; ReviewAPI.setSession(next);
        clearTimeout(timer);
        host.innerHTML = `<section class="panel review-session-panel">
          <div><strong id="auth-identity"></strong><p id="auth-scope"></p>
            <p id="auth-message" role="status" aria-live="polite"></p></div>
          ${next.mode === 'session' ? I18n.t('<button class="btn" id="review-logout">退出登录</button>') : ''}
          </section><div id="authenticated-review"></div>`;
        host.querySelector('#auth-identity').textContent = ReviewAPI.identity(next.username);
        host.querySelector('#auth-scope').textContent = next.can_review
          ? I18n.t('可上传评论、核对证据、提交决定并跟进问题。复核操作会保存身份与历史。')
          : I18n.t('只读权限：可查看批次、评论、证据和历史，不能上传或修改数据。');
        message(note);
        mountWorkspace(host.querySelector('#authenticated-review'));
        if (next.expires_at) {
          timer = setTimeout(() => expire(I18n.t('登录已过期，请重新登录后继续。')),
            Math.max(0, new Date(next.expires_at).getTime() - Date.now()));
        }
        host.querySelector('#review-logout')?.addEventListener('click', async event => {
          if (host.querySelector('#review-workspace')?.getAttribute('aria-busy') === 'true') {
            message(I18n.t('正在保存，请等本次操作结束后退出。')); return;
          }
          event.currentTarget.disabled = true;
          try {
            await ReviewAPI.request('/auth/logout', {});
            clearTimeout(timer); ++serial;
            if (connected()) showLogin(I18n.t('已退出登录。'));
            notifyTabs();
          } catch (_) {
            if (connected()) {
              message(I18n.t('退出未完成，请重试。'));
              const button = host.querySelector('#review-logout');
              if (button) button.disabled = false;
            }
          }
        });
      }
      async function refresh(note = '') {
        const call = ++serial;
        try {
          const next = await ReviewAPI.request('/auth/session');
          if (!connected() || call !== serial) return;
          if (!next.authenticated) {
            if (identity || !host.querySelector('#review-login')) showLogin(note);
          } else if (!identity || next.username !== identity.username ||
                     next.role !== identity.role || next.csrf_token !== identity.csrf_token ||
                     next.mode !== identity.mode) showWorkspace(next, note);
        } catch (_) {
          if (!connected() || call !== serial) return;
          if (identity || host.querySelector('#review-login')) return;
          host.innerHTML = I18n.t('<section class="panel"><p>无法连接登录服务。</p><button class="btn" id="auth-retry">重试连接</button></section>');
          host.querySelector('#auth-retry').addEventListener('click', () => refresh());
        }
      }
      function expire(note = I18n.t('会话或权限已变化，请重新核对后继续。未自动重试提交。')) {
        if (!connected()) return;
        clearTimeout(timer);
        showLogin(note);
        refresh(note);
      }
      const expired = () => expire();
      const focused = () => { if (connected() && !loading) refresh(); };
      const storage = event => { if (event.key === 'review-session-event') expire(); };
      window.addEventListener('review-session-expired', expired);
      window.addEventListener('focus', focused);
      window.addEventListener('storage', storage);
      cleanup = () => {
        ++serial; clearTimeout(timer);
        window.removeEventListener('review-session-expired', expired);
        window.removeEventListener('focus', focused);
        window.removeEventListener('storage', storage);
      };
      host.innerHTML = I18n.t('<section class="panel"><p>正在检查登录状态…</p></section>');
      refresh();
    }
  };
})();
