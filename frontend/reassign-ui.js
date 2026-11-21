/* Existing-group reassignment, separate from changing an accept/reject decision. */
(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const errors = {
    target_changed: '目标问题或目标关联已变化，请重新搜索并核对。',
    target_already_reviewed: '目标已有人工决定，不能覆盖；请先查看目标关联。',
    source_not_assignable: '原关联已拒绝，不能继续移组。',
    review_changed: '原评论或关联已变化，请取消后重新加载。',
    source_changed: '原文已变化，请取消后重新加载。',
    analysis_not_ready: '评论正在分析，请稍后重新加载。',
    invalid_evidence: '原文证据失效，不能调整归组。',
    same_issue: '目标不能是当前问题组。',
    scope_mismatch: '只能选择同平台、店铺和商品的问题组。',
    issue_not_active: '问题组已关闭或合并，请重新选择。',
    idempotency_conflict: '提交编号冲突，请取消后重新加载。'
  };
  window.ReviewRegroup = {
    mount(root, source, hooks) {
      let offset = 0, items = [], total = 0, serial = 0, saving = false, loading = false;
      let pending = null;
      root.innerHTML = `
        <section class="human-review-regroup">
          <h4>调整到另一个问题组</h4>
          <p>当前：${esc(source.issue.title)}</p>
          <p>仅显示同平台、店铺、商品下的有效问题组。原关联将被拒绝，目标关联将被接受，操作历史保留。</p>
          <p>沿用原文证据：“${esc(source.link.evidence_text)}”</p>
          <form id="regroup-search"><label for="regroup-query">搜索目标问题组</label>
            <input id="regroup-query" maxlength="200" placeholder="输入问题标题，留空显示全部">
            <button class="btn" type="submit">搜索问题组</button></form>
          <p id="regroup-total"></p>
          <form id="regroup-submit">
            <label for="regroup-target">目标问题组</label>
            <select id="regroup-target"><option value="">正在加载…</option></select>
            <div class="human-review-pagination">
              <button class="btn" type="button" id="regroup-prev" disabled>上一页目标</button>
              <button class="btn" type="button" id="regroup-next" disabled>下一页目标</button>
            </div>
            <p id="regroup-summary">请选择目标问题组。</p>
            <label for="regroup-note">调整原因（必填，最多 500 字）</label>
            <textarea id="regroup-note" maxlength="500" rows="3"></textarea>
            <div class="human-review-actions">
              <button class="btn btn-primary" type="submit" id="regroup-confirm" disabled>确认调整归组</button>
              <button class="btn" type="button" id="regroup-cancel">取消归组调整</button>
            </div>
          </form><p id="regroup-message" role="status" aria-live="polite"></p>
        </section>`;
      const $ = selector => root.querySelector(selector);
      const message = text => { if (root.isConnected) $('#regroup-message').textContent = text; };
      const selected = () => items.find(item => item.issue.id === $('#regroup-target').value);
      function controls() {
        root.querySelectorAll('button, input, select, textarea').forEach(el => { el.disabled = saving; });
        $('#regroup-confirm').disabled = saving || loading || !selected()?.selectable;
        $('#regroup-prev').disabled = saving || loading || offset === 0;
        $('#regroup-next').disabled = saving || loading || offset + items.length >= total;
        $('#regroup-target').disabled = saving || loading;
      }
      function summary() {
        const item = selected();
        $('#regroup-summary').textContent = item
          ? `从“${source.issue.title}”调整到“${item.issue.title}”。目标问题状态保持不变。`
          : '请选择目标问题组。';
        controls();
      }
      async function search() {
        const call = ++serial;
        loading = true; items = []; pending = null;
        $('#regroup-target').innerHTML = '<option value="">正在加载…</option>';
        summary();
        try {
          const query = new URLSearchParams({q: $('#regroup-query').value.trim(), limit: '20', offset: String(offset)});
          const data = await ReviewAPI.request(`/comment-issues/${source.link.id}/reassign-targets?${query}`);
          if (!root.isConnected || call !== serial) return;
          items = data.items; total = data.total;
          if (!items.length && offset > 0) { offset = 0; return search(); }
          $('#regroup-total').textContent = `找到 ${total} 个同商品问题组。`;
          $('#regroup-target').innerHTML = '<option value="">请选择目标问题组</option>' + items.map(item => `
            <option value="${esc(item.issue.id)}" ${item.selectable ? '' : 'disabled'}>${esc(item.issue.title)} · ${esc(item.issue.category_id)}${item.selectable ? '' : '（已有人工决定，不可覆盖）'}</option>`).join('');
          message(items.length ? '选择目标后，请核对调整方向并填写原因。' : '没有符合条件的问题组。可修改搜索条件；新建问题组将在人工补充功能中提供。');
        } catch (error) {
          if (call === serial) message(errors[error.message] || '目标列表加载失败，请重试。');
        } finally {
          if (root.isConnected && call === serial) { loading = false; summary(); }
        }
      }
      root.addEventListener('change', event => {
        event.stopPropagation();
        if (event.target.id === 'regroup-target') { pending = null; summary(); }
      });
      root.addEventListener('click', event => {
        event.stopPropagation();
        if (saving) return;
        if (event.target.id === 'regroup-cancel') hooks.cancel();
        if (event.target.id === 'regroup-prev') { offset -= 20; search(); }
        if (event.target.id === 'regroup-next') { offset += 20; search(); }
      });
      root.addEventListener('submit', async event => {
        event.preventDefault(); event.stopPropagation();
        if (saving) return;
        if (event.target.id === 'regroup-search') { offset = 0; search(); return; }
        const target = selected(), note = $('#regroup-note').value.trim();
        if (loading || !target?.selectable) { message('请选择可用的目标问题组。'); return; }
        if (!note) { message('请填写调整原因。'); $('#regroup-note').focus(); return; }
        const content = {expected_token: source.token, target_issue_id: target.issue.id,
          expected_target_token: target.token, note};
        const key = JSON.stringify(content);
        if (!pending || pending.key !== key) pending = {key, body: {...content, request_id: crypto.randomUUID()}};
        saving = true; hooks.busy(true); controls();
        try {
          const result = await ReviewAPI.request(`/comment-issues/${source.link.id}/reassign`, pending.body);
          pending = null;
          await hooks.saved(result);
        } catch (error) {
          message((errors[error.message] || '保存未确认，请重试。') + ' 调整原因已保留。');
        } finally {
          saving = false; hooks.busy(false);
          if (root.isConnected) controls();
        }
      });
      search();
    }
  };
})();
