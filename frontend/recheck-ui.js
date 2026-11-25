(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const errors = {
    review_changed: '原文、关联决定或问题组已变化，请取消并重新加载后核对。',
    invalid_evidence: '证据必须与当前原文的所选位置逐字一致。',
    analysis_not_ready: '正在等待或进行分析，请完成后再重新复核。',
    issue_not_active: '问题组已关闭或合并，请先查看问题组状态。',
    suggestion_superseded: '此关联已归档，不能通过重新复核恢复归组。',
    source_unchanged: '原文与现有证据未变化；修改接受／拒绝请使用“修改决定”。',
    recheck_unchanged: '原文、决定和证据均未改变，无需重复保存。',
    idempotency_conflict: '提交编号冲突，请取消并重新核对。',
    scope_mismatch: '评论与问题组所属商品不一致。'
  };
  window.ReviewRecheck = {
    mount(root, item, hooks) {
      let busy = false, pending = null, occurrences = [];
      const body = item.comment.body;
      root.innerHTML = `<section class="human-review-regroup"><h4>重新核对原文与证据</h4>
        <p>本次只依据当前原文重新判断。原决定与旧证据保留；保存后问题组回到“待确认”。</p>
        <form id="recheck-form" class="human-review-manual-form">
          <label for="recheck-decision">本次判断</label><select id="recheck-decision">
            <option value="">请选择判断</option><option value="accept">接受：当前原文支持该问题</option>
            <option value="reject">拒绝：当前原文不支持该问题</option></select>
          <label for="recheck-evidence">当前原文证据（接受时必填，拒绝时可留空）</label>
          <textarea id="recheck-evidence" maxlength="2000" rows="3"></textarea>
          <p id="recheck-evidence-feedback">从当前原文复制证据。拒绝且无合适引文时可以留空，不沿用旧证据。</p>
          <label for="recheck-occurrence">证据出现的位置</label><select id="recheck-occurrence"></select>
          <blockquote class="human-review-body" id="recheck-preview">${esc(body)}</blockquote>
          <label for="recheck-note">重新复核原因（必填，最多 500 字）</label>
          <textarea id="recheck-note" maxlength="500" rows="3"></textarea>
          <p id="recheck-message" role="status" aria-live="polite"></p>
          <button class="btn btn-primary" id="recheck-save" disabled>保存重新复核</button>
          <button class="btn" type="button" id="recheck-cancel">取消重新复核</button>
        </form></section>`;
      const $ = s => root.querySelector(s);
      const message = value => { if (root.isConnected) $('#recheck-message').textContent = value; };
      function controls() {
        const decision = $('#recheck-decision').value, quote = $('#recheck-evidence').value;
        $('#recheck-save').disabled = !decision || (decision === 'accept' || quote.length > 0) && !occurrences.length;
      }
      function preview() {
        const span = occurrences[Number($('#recheck-occurrence').value)], chars = Array.from(body);
        $('#recheck-preview').innerHTML = span ? esc(chars.slice(0, span.start).join('')) + '<mark>' +
          esc(chars.slice(span.start, span.end).join('')) + '</mark>' + esc(chars.slice(span.end).join('')) : esc(body);
      }
      function evidence() {
        const quote = $('#recheck-evidence').value;
        occurrences = [];
        if (quote.trim()) {
          for (let pos = body.indexOf(quote); pos >= 0; pos = body.indexOf(quote, pos + 1)) {
            occurrences.push({start: Array.from(body.slice(0, pos)).length,
              end: Array.from(body.slice(0, pos + quote.length)).length});
          }
        }
        $('#recheck-occurrence').innerHTML = occurrences.map((span, i) =>
          `<option value="${i}">第 ${i + 1} 处：第 ${span.start + 1}–${span.end} 个字符</option>`).join('');
        $('#recheck-evidence-feedback').textContent = occurrences.length
          ? `找到 ${occurrences.length} 处匹配，请核对下方高亮位置。`
          : quote ? '未匹配当前原文，请重新复制；不能使用改写的引文。' : '接受时必须提供当前证据；拒绝时可留空。';
        preview(); controls();
      }
      root.addEventListener('input', event => {
        if (event.target.id === 'recheck-evidence') evidence();
      });
      root.addEventListener('change', event => {
        if (event.target.id === 'recheck-occurrence') preview();
        controls();
      });
      root.addEventListener('click', event => {
        if (!busy && event.target.id === 'recheck-cancel') hooks.cancel();
      });
      root.addEventListener('submit', async event => {
        event.preventDefault(); event.stopPropagation();
        if (busy || event.target.id !== 'recheck-form' || $('#recheck-save').disabled) return;
        const decision = $('#recheck-decision').value, note = $('#recheck-note').value.trim();
        if (!note) { message('请填写重新复核原因。'); $('#recheck-note').focus(); return; }
        const content = {expected_token: item.token, decision, note};
        const span = occurrences[Number($('#recheck-occurrence').value)];
        if (span) Object.assign(content, {evidence_text: $('#recheck-evidence').value,
          evidence_start: span.start, evidence_end: span.end});
        const key = JSON.stringify(content);
        if (!pending || pending.key !== key) pending = {key, body: {...content, request_id: crypto.randomUUID()}};
        busy = true; root.inert = true; hooks.busy(true);
        try {
          const result = await ReviewAPI.request(`/comment-issues/${item.link.id}/recheck`, pending.body);
          pending = null; await hooks.saved(result);
        } catch (error) { message((errors[error.message] || '保存未确认，请重试。') + ' 输入内容已保留。'); }
        finally { busy = false; root.inert = false; hooks.busy(false); }
      });
    }
  };
})();
