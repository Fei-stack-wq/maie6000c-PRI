(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const verdict = s => ({yes: '发现问题', no: '未发现问题', unknown: '无法判断'}[s] || '未完成');
  const labels = {suggested: '待复核', accepted: '已接受', rejected: '已拒绝'};
  const errors = {
    comment_changed: '原文、分析或关联已变化，请重新加载并核对。',
    analysis_not_ready: '评论正在等待或进行分析，请完成后再补充。',
    invalid_evidence: '证据必须逐字对应原文中的所选位置。',
    target_changed: '目标问题组已变化，请重新搜索并核对。',
    target_already_reviewed: '这条评论在目标中已有人工决定，请查看原关联。',
    duplicate_issue: '同类别已有同名有效问题组，请切换到“关联已有问题组”并搜索。',
    scope_mismatch: '目标必须属于同平台、店铺和商品。',
    issue_not_active: '目标问题组已关闭或合并，请重新选择。',
    idempotency_conflict: '提交编号冲突，请重新加载后核对。'
  };
  window.ManualReview = {
    mount(root, hooks) {
      let current = null, busy = false, detailLoading = false, pending = null;
      let offset = 0, total = 0, queueSerial = 0, detailSerial = 0;
      let targets = [], targetOffset = 0, targetTotal = 0, targetSerial = 0, targetLoading = false;
      let occurrences = [];
      root.innerHTML = `<div class="panel human-review-head">
        <h2>人工补充问题</h2><p>核对评论原文，补充 AI 漏检的问题。人工证据单独留痕，AI 原判断保留。</p>
        <p id="manual-identity"></p>
        <form id="manual-filter" class="human-review-filters">
          <label>评论范围 <select name="verdict"><option value="attention">未发现 / 无法判断 / 分析失败</option>
            <option value="all">全部评论</option><option value="yes">AI 发现问题</option>
            <option value="no">AI 未发现问题</option><option value="unknown">AI 无法判断</option>
            <option value="failed">分析失败</option></select></label>
          <label>商品编号 <input name="product" placeholder="全部商品"></label>
          <label>搜索原文 <input name="q" maxlength="200" placeholder="输入原文关键词"></label>
          <button class="btn btn-primary">查询评论</button>
        </form></div><p id="manual-message" role="status" aria-live="polite"></p>
        <div class="human-review-grid"><section class="panel"><h3 id="manual-count">评论列表</h3>
          <div id="manual-items"></div><div class="human-review-pagination">
          <button class="btn" id="manual-prev" disabled>上一页评论</button>
          <button class="btn" id="manual-next" disabled>下一页评论</button></div></section>
          <section class="panel" id="manual-detail">选择评论，查看原文并补充问题。</section></div>`;
      const $ = selector => root.querySelector(selector);
      const message = text => { if (root.isConnected) $('#manual-message').textContent = text; };
      const isNew = () => $('#manual-mode')?.value === 'new';
      const target = () => targets.find(t => t.issue.id === $('#manual-target')?.value);
      function controls() {
        if (!root.isConnected) return;
        $('#manual-prev').disabled = offset === 0;
        $('#manual-next').disabled = offset + 20 >= total;
        const form = $('#manual-add');
        if (!form) return;
        $('#manual-new-fields').hidden = !isNew();
        $('#manual-existing-fields').hidden = isNew();
        $('#manual-target').disabled = targetLoading;
        $('#manual-target-prev').disabled = targetLoading || targetOffset === 0;
        $('#manual-target-next').disabled = targetLoading || targetOffset + targets.length >= targetTotal;
        $('#manual-save').disabled = !current?.can_add || detailLoading || !occurrences.length ||
          (!isNew() && (targetLoading || !target()?.selectable));
      }
      async function loadQueue() {
        const call = ++queueSerial, form = new FormData($('#manual-filter'));
        const params = new URLSearchParams({verdict: form.get('verdict'), q: form.get('q').trim(),
          limit: '20', offset: String(offset)});
        if (form.get('product').trim()) params.set('product_id', form.get('product').trim());
        try {
          const data = await ReviewAPI.request('/review-comments?' + params);
          if (!root.isConnected || call !== queueSerial) return;
          total = data.total;
          if (!data.items.length && offset) { offset = 0; return loadQueue(); }
          $('#manual-identity').textContent = ReviewAPI.identity(data.operator);
          $('#manual-count').textContent = `符合条件：${total} 条评论`;
          $('#manual-items').innerHTML = data.items.length ? data.items.map(c => `
            <button class="human-review-item" data-comment="${esc(c.id)}">
              <strong>${esc(c.product_id)} · ${c.analysis_status === 'failed' ? '分析失败' : 'AI ' + verdict(c.has_issue)}</strong>
              <span>${esc(c.body)}</span><small>${esc(c.platform)} / ${esc(c.shop_id)}</small></button>`).join('')
            : '<p>没有符合条件的评论。可切换到“全部评论”或修改筛选条件。</p>';
          controls();
        } catch (error) { if (call === queueSerial) message('评论列表加载失败，请重试查询。'); }
      }
      function updateEvidence() {
        const quote = $('#manual-evidence').value, body = current.comment.body;
        const previous = $('#manual-occurrence').value;
        occurrences = [];
        if (quote.trim()) {
          for (let pos = body.indexOf(quote); pos >= 0; pos = body.indexOf(quote, pos + 1)) {
            occurrences.push({start: Array.from(body.slice(0, pos)).length,
              end: Array.from(body.slice(0, pos + quote.length)).length});
          }
        }
        $('#manual-occurrence').innerHTML = occurrences.map((s, i) =>
          `<option value="${i}">第 ${i + 1} 处：第 ${s.start + 1}–${s.end} 个字符</option>`).join('');
        if (occurrences.length) $('#manual-occurrence').value =
          previous !== '' && occurrences[Number(previous)] ? previous : '0';
        $('#manual-evidence-feedback').textContent = occurrences.length
          ? `原文中找到 ${occurrences.length} 处匹配，请核对下方高亮位置。`
          : '请从原文复制一段非空证据；必须逐字一致。';
        previewEvidence(); controls();
      }
      function previewEvidence() {
        const span = occurrences[Number($('#manual-occurrence').value)];
        const chars = Array.from(current.comment.body);
        $('#manual-body').innerHTML = span
          ? esc(chars.slice(0, span.start).join('')) + '<mark>' + esc(chars.slice(span.start, span.end).join('')) + '</mark>' + esc(chars.slice(span.end).join(''))
          : esc(current.comment.body);
      }
      async function loadTargets() {
        const call = ++targetSerial, commentId = current.comment.id;
        targets = []; targetLoading = true; pending = null;
        $('#manual-target').innerHTML = '<option value="">正在加载…</option>'; controls();
        const params = new URLSearchParams({q: $('#manual-target-query').value.trim(),
          limit: '20', offset: String(targetOffset)});
        try {
          const data = await ReviewAPI.request(`/review-comments/${commentId}/targets?${params}`);
          if (!root.isConnected || call !== targetSerial || current.comment.id !== commentId) return;
          targets = data.items; targetTotal = data.total;
          if (!targets.length && targetOffset) { targetOffset = 0; return loadTargets(); }
          $('#manual-target').innerHTML = '<option value="">请选择已有问题组</option>' + targets.map(t =>
            `<option value="${esc(t.issue.id)}" ${t.selectable ? '' : 'disabled'}>${esc(t.issue.title)}${t.selectable ? '' : '（已有人工决定，不可覆盖）'}</option>`).join('');
          $('#manual-target-count').textContent = `找到 ${targetTotal} 个同商品有效问题组。没有合适的可选择新建。`;
        } catch (error) { if (call === targetSerial) message(errors[error.message] || '目标加载失败，请重试搜索。'); }
        finally { if (root.isConnected && call === targetSerial) { targetLoading = false; controls(); } }
      }
      function renderDetail(data) {
        data = {...data, can_add: data.can_add && ReviewAPI.canReview};
        current = data; pending = null; occurrences = []; targets = []; targetOffset = 0; ++targetSerial;
        const c = data.comment;
        $('#manual-detail').innerHTML = `<h3>评论原文与人工补充</h3>
          <p>${esc(c.platform)} / ${esc(c.shop_id)} / ${esc(c.product_id)}</p>
          <p>AI 判断：${verdict(c.has_issue)}${c.analysis_status === 'failed' ? ' · 分析失败，可直接人工核对原文' : ''}</p>
          <blockquote class="human-review-body" id="manual-body">${esc(c.body)}</blockquote>
          <h4>已有问题关联</h4>${data.links.length ? data.links.map(r => `<p>
            <button class="btn" data-open-link="${r.link.id}">${esc(r.issue.title)} · ${labels[r.link.status]}${r.link.superseded_at ? '（旧建议）' : ''}</button></p>`).join('') : '<p>暂无关联，可以补充 AI 漏检的问题。</p>'}
          ${data.can_add ? `<form id="manual-add" class="human-review-manual-form">
            <label for="manual-evidence">原文证据（请复制原文片段）</label>
            <textarea id="manual-evidence" maxlength="2000" rows="3"></textarea>
            <p id="manual-evidence-feedback">请从原文复制一段非空证据；必须逐字一致。</p>
            <label for="manual-occurrence">证据在原文中的位置</label><select id="manual-occurrence"></select>
            <label for="manual-mode">补充方式</label><select id="manual-mode">
              <option value="existing">关联已有问题组</option><option value="new">新建问题组</option></select>
            <div id="manual-existing-fields">
              <label for="manual-target-query">搜索已有问题组</label><input id="manual-target-query" maxlength="200" placeholder="输入问题标题">
              <button type="button" class="btn" id="manual-target-search">搜索问题组</button>
              <p id="manual-target-count"></p><label for="manual-target">目标问题组</label><select id="manual-target"></select>
              <div class="human-review-pagination"><button type="button" class="btn" id="manual-target-prev">上一页目标</button>
                <button type="button" class="btn" id="manual-target-next">下一页目标</button></div>
            </div><div id="manual-new-fields" hidden>
              <label for="manual-title">新问题标题（最多 200 字）</label><input id="manual-title" maxlength="200">
              <label for="manual-category">问题类别</label><select id="manual-category">
                <option value="quality">质量</option><option value="logistics">物流</option>
                <option value="mismatch">描述不符</option><option value="usability">使用体验</option><option value="other">其他</option></select>
              <p>新问题组将保存为“待确认”，本条人工关联保存为“已接受”。</p>
            </div><label for="manual-note">补充原因（必填，最多 500 字）</label>
            <textarea id="manual-note" maxlength="500" rows="3"></textarea>
            <div class="human-review-actions"><button class="btn btn-primary" id="manual-save" disabled>保存人工补充</button>
              <button class="btn" type="button" id="manual-reset">取消补充</button>
              <button class="btn" type="button" id="manual-reload">重新加载评论</button></div>
          </form>` : `<p>${esc(ReviewAPI.canReview ? (errors[data.blocked_reason] || '当前不可补充。') : '只读成员可查看原文和历史，不能补充问题。')}</p><button class="btn" id="manual-reload">重新加载评论</button>`}`;
        if (data.can_add) loadTargets();
      }
      async function loadDetail(id) {
        const call = ++detailSerial; ++targetSerial;
        detailLoading = true; $('#manual-detail').inert = true;
        try {
          const data = await ReviewAPI.request('/review-comments/' + id);
          if (root.isConnected && call === detailSerial) { renderDetail(data); hooks.selected?.(data.comment.id); }
        } catch (error) { if (call === detailSerial) message('评论加载失败，输入已保留，请重试。'); }
        finally {
          if (root.isConnected && call === detailSerial) {
            detailLoading = false; $('#manual-detail').inert = false; controls();
          }
        }
      }
      root.addEventListener('input', event => {
        if (event.target.id === 'manual-evidence' && current) updateEvidence();
      });
      root.addEventListener('keydown', event => {
        if (event.target.id === 'manual-target-query' && event.key === 'Enter') {
          event.preventDefault();
          if (!busy) { targetOffset = 0; loadTargets(); }
        }
      });
      root.addEventListener('change', event => {
        if (event.target.id === 'manual-occurrence') previewEvidence();
        if (event.target.id === 'manual-mode' || event.target.id === 'manual-target') { pending = null; controls(); }
      });
      root.addEventListener('click', event => {
        if (busy) return;
        const comment = event.target.closest('[data-comment]'), link = event.target.closest('[data-open-link]');
        if (comment) { message(''); loadDetail(comment.dataset.comment); }
        if (link) hooks.openReview(link.dataset.openLink);
        if (event.target.id === 'manual-prev') { offset -= 20; loadQueue(); }
        if (event.target.id === 'manual-next') { offset += 20; loadQueue(); }
        if (event.target.id === 'manual-target-prev') { targetOffset -= 20; loadTargets(); }
        if (event.target.id === 'manual-target-next') { targetOffset += 20; loadTargets(); }
        if (event.target.id === 'manual-target-search') { targetOffset = 0; loadTargets(); }
        if (event.target.id === 'manual-reload' && current) loadDetail(current.comment.id);
        if (event.target.id === 'manual-reset' && current) { renderDetail(current); message('已取消补充，未保存任何改变。'); }
      });
      root.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy) return;
        if (event.target.id === 'manual-filter') { offset = 0; loadQueue(); return; }
        if (event.target.id !== 'manual-add' || detailLoading || !current?.can_add) return;
        const span = occurrences[Number($('#manual-occurrence').value)], note = $('#manual-note').value.trim();
        if (!span) { message('请填写与原文一致的证据，并选择位置。'); return; }
        if (!note) { message('请填写补充原因。'); $('#manual-note').focus(); return; }
        const content = {expected_token: current.token, evidence_text: $('#manual-evidence').value,
          evidence_start: span.start, evidence_end: span.end, note};
        if (isNew()) {
          const title = $('#manual-title').value.trim();
          if (!title) { message('请填写新问题标题。'); $('#manual-title').focus(); return; }
          content.new_issue = {title, category_id: $('#manual-category').value};
        } else {
          if (targetLoading || !target()?.selectable) { message('请选择可用的已有问题组。'); return; }
          content.target_issue_id = target().issue.id; content.expected_target_token = target().token;
        }
        const key = JSON.stringify(content);
        if (!pending || pending.key !== key) pending = {key, body: {...content, request_id: crypto.randomUUID()}};
        busy = true; hooks.busy(true); root.inert = true;
        try {
          const result = await ReviewAPI.request(`/review-comments/${current.comment.id}/manual-links`, pending.body);
          pending = null;
          message('人工补充已保存，关联已接受；原文证据、原因和操作历史均已保留。');
          await loadDetail(current.comment.id);
          if (root.isConnected) {
            const button = document.createElement('button');
            button.className = 'btn'; button.dataset.openLink = result.link_id;
            button.textContent = '查看刚保存的关联与历史'; $('#manual-message').append(' ', button);
          }
        } catch (error) { message((errors[error.message] || '保存未确认，请重试。') + ' 输入内容已保留。'); }
        finally { busy = false; hooks.busy(false); root.inert = false; controls(); }
      });
      loadQueue();
      if (hooks.commentId) loadDetail(hooks.commentId);
    }
  };
})();
