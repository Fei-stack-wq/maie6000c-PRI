(function () {
  'use strict';
  const reasons = {
    link_not_found: I18n.t('未找到这条关联，请返回列表重新选择。'),
    source_changed: I18n.t('原文已变化，请核对当前内容。'),
    suggestion_superseded: I18n.t('该关联已被新分析或归组操作替换，原记录与历史保留。'),
    analysis_changed: I18n.t('分析结果已更新，请重新加载。'),
    analysis_not_ready: I18n.t('评论正在等待或进行分析。'),
    issue_not_active: I18n.t('问题组已关闭或合并。'),
    already_reviewed: I18n.t('本条建议已处理，可通过“修改决定”纠正原判断。'),
    not_reviewed: I18n.t('这条建议尚未复核，请先作出首次决定。'),
    decision_unchanged: I18n.t('新决定与原决定相同，无需重复保存。'),
    scope_mismatch: I18n.t('评论与问题所属商品不一致，不能提交。'),
    review_changed: I18n.t('内容或决定已变化，请重新加载并核对。'),
    invalid_evidence: I18n.t('证据未通过原文校验，不能接受。'),
    idempotency_conflict: I18n.t('请求编号冲突，请重新加载。')
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const label = s => ({suggested: I18n.t('待复核'), accepted: I18n.t('已接受'), rejected: I18n.t('已拒绝')}[s] || s);
  const issueLabel = s => ({proposed: I18n.t('待确认'), confirmed: I18n.t('已确认'), resolved: I18n.t('已处理'), dismissed: I18n.t('已驳回')}[s] || s);
  const verdict = s => ({yes: I18n.t('发现问题'), no: I18n.t('未发现问题'), unknown: I18n.t('无法判断')}[s] || I18n.t('未完成'));
  const date = s => s ? new Date(s).toLocaleString(I18n.locale) : '—';
  const actionLabel = a => {
    const data = a.payload_json || {};
    if (data.operation === 'recheck_evidence') return I18n.html`重新复核原文与证据：${label(a.from_status)} → ${label(a.to_status)}`;
    if (data.operation === 'manual_add') return data.created_issue ? I18n.t('人工补充：新建问题组并接受关联') : I18n.t('人工补充：接受关联');
    if (data.operation === 'reassign_out') return I18n.html`调整归组：移至“${data.target_issue_title}”`;
    if (data.operation === 'reassign_in') return I18n.html`调整归组：来自“${data.source_issue_title}”`;
    if (['merge_out', 'split_out'].includes(data.operation)) return I18n.html`问题组${data.operation === 'merge_out' ? I18n.t('合并') : I18n.t('拆分')}：原关联归档，转至“${data.target_issue_title}”，原决定保留`;
    if (['merge_in', 'split_in'].includes(data.operation)) return I18n.html`问题组${data.operation === 'merge_in' ? I18n.t('合并') : I18n.t('拆分')}：来自“${data.source_issue_title}”，${data.deduplicated ? I18n.t('保留目标的相同决定与证据') : I18n.t('沿用原决定与证据')}`;
    return a.action === 'change'
      ? I18n.html`修改决定：${label(a.from_status)} → ${label(a.to_status)}`
      : ({accept: I18n.t('接受关联'), reject: I18n.t('拒绝关联')}[a.action] || a.action);
  };
  const reason = code => reasons[code] || I18n.t('请求失败，请检查服务后重试。');

  window.ReviewDecisions = {
    mount(root, options = {}) {
      let status = 'pending', initialDetail = Boolean(options.linkId);
      let offset = 0, current = null, pending = null, editing = false;
      let generation = 0, queueGeneration = 0, busy = false, loadingDetail = false, regrouping = false;
      let rechecking = false;
      root.innerHTML = I18n.html`
        <div class="panel human-review-head">
          <h2>人工复核</h2><p>核对原文后接受或拒绝关联。接受关联不会自动确认问题组。</p>
          <p id="review-identity">正在连接真实后台…</p>
          <form id="review-filter" class="human-review-filters">
            <label>记录 <select name="status"><option value="pending" ${status === 'pending' ? 'selected' : ''}>待复核</option>
              <option value="reviewed" ${status === 'reviewed' ? 'selected' : ''}>${I18n.language === 'en' ? 'Reviewed' : '已处理'}</option>
              <option value="needs_recheck">原文变化待重核</option></select></label>
            <label>商品编号 <input name="product" placeholder="全部商品"></label>
            <label>类别 <select name="category"><option value="">全部类别</option>
              <option value="quality">质量</option><option value="logistics">物流</option>
              <option value="mismatch">描述不符</option><option value="usability">使用体验</option>
              <option value="other">其他</option></select></label>
            <button class="btn btn-primary">查询</button>
          </form>
        </div>
        <p id="review-message" role="status" aria-live="polite"></p>
        <div class="human-review-grid">
          <section class="panel"><h3 id="review-count">建议列表</h3>
            <div id="review-items"></div>
            <div class="human-review-pagination"><button class="btn" id="review-prev">上一页</button>
            <button class="btn" id="review-next">下一页</button></div></section>
          <section class="panel" id="review-detail"><p>选择一条记录查看原文和历史。</p></section>
        </div>`;
      const $ = s => root.querySelector(s);
      const canSubmit = () => !regrouping && !rechecking && (current?.can_decide || (editing && current?.can_revise));
      const message = text => { if (root.isConnected) $('#review-message').textContent = text; };

      async function loadQueue() {
        const serial = ++queueGeneration;
        const form = new FormData($('#review-filter'));
        const params = new URLSearchParams({status, limit: '20', offset: String(offset)});
        if (form.get('product').trim()) params.set('product_id', form.get('product').trim());
        if (form.get('category')) params.set('category_id', form.get('category'));
        try {
          const data = await ReviewAPI.request('/review-queue?' + params);
          if (!root.isConnected || serial !== queueGeneration) return;
          if (!data.items.length && offset > 0) { offset = Math.max(0, offset - 20); return loadQueue(); }
          $('#review-identity').textContent = ReviewAPI.identity(data.operator);
          $('#review-count').textContent = I18n.html`${{pending:I18n.t('待复核'), reviewed:I18n.t('已处理'), needs_recheck:I18n.t('原文变化待重核')}[status]}：${data.total} 条关联`;
          $('#review-items').innerHTML = data.items.length ? data.items.map(item => `
            <button class="human-review-item" data-link="${item.link.id}">
              <strong>${esc(item.issue.title)}</strong><span>${esc(item.comment.body)}</span>
              <small>${esc(item.comment.product_id)} · ${label(item.link.status)}${item.needs_recheck ? I18n.t(' · 原文变化，待重核') : ''}</small>
            </button>`).join('') : I18n.t('<p>没有符合条件的关联。</p>');
          $('#review-prev').disabled = offset === 0;
          $('#review-next').disabled = offset + data.items.length >= data.total;
        } catch (e) { if (serial === queueGeneration) message(reason(e.message)); }
      }

      function renderDetail(item, note = '', revise = false, regroup = false, recheck = false) {
        item = {...item};
        for (const key of ['can_decide', 'can_revise', 'can_reassign', 'can_recheck']) {
          item[key] = item[key] && ReviewAPI.canReview;
        }
        current = item;
        editing = revise && item.can_revise;
        regrouping = regroup && item.can_reassign;
        rechecking = recheck && item.can_recheck;
        const editable = item.can_decide || editing;
        const blocked = item.link.status === 'suggested' ? item.blocked_reason : item.revision_blocked_reason;
        const c = item.comment, link = item.link;
        // Use literal text/escaped HTML; offsets from Python are not JS UTF-16 offsets.
        let body = esc(c.body);
        const chars = Array.from(c.body), start = link.evidence_start, end = link.evidence_end;
        if (start != null && end != null && chars.slice(start, end).join('') === link.evidence_text && item.blocked_reason !== 'source_changed') {
          body = esc(chars.slice(0, start).join('')) + '<mark>' + esc(link.evidence_text) + '</mark>' +
            esc(chars.slice(end).join(''));
        }
        $('#review-detail').innerHTML = I18n.html`
          <h3>${esc(item.issue.title)}</h3>
          <p>${esc(c.platform)} / ${esc(c.shop_id)} / ${esc(c.product_id)}</p>
          ${options.openComment ? I18n.t('<button class="btn" type="button" id="review-open-comment">查看评论详情</button>') : ''}
          <p>关联：${label(link.status)}${link.superseded_at ? I18n.t('（已归档）') : ''} · 问题状态：${item.issue.merged_into_id ? I18n.t('已合并') : esc(issueLabel(item.issue.status))}</p>
          <p>该问题已接受 ${item.issue.accepted_count} 条关联，待复核建议 ${item.issue.suggested_count} 条。</p>
          ${options.openIssue ? I18n.t('<button class="btn" type="button" id="review-open-issue">查看问题组与跟进</button>') : ''}
          <h4>当前评论原文</h4><blockquote class="human-review-body">${body}</blockquote>
          <p>关联证据：${esc(link.evidence_text || I18n.t('无'))}</p>
          ${item.needs_recheck ? I18n.html`<h4>旧证据对应的原文</h4>
            ${item.evidence_body != null ? `<blockquote class="human-review-body">${esc(item.evidence_body)}</blockquote>` : I18n.t('<p>未找到可核验的历史原文；旧证据和决定仍保留，不将当前原文当作旧原文。</p>')}
            <p class="human-review-notice">当前原文与原证据版本不同。${item.can_recheck ? I18n.t('请重新判断并选取当前证据。') : esc(reason(item.recheck_blocked_reason))}</p>` : ''}
          <p>AI 判断：${esc(verdict(c.has_issue))} · 关联来源：${link.origin === 'ai' ? I18n.t('AI 建议') : I18n.t('人工关联')}</p>
          ${blocked ? `<p class="human-review-notice">${esc(reason(blocked))}</p>` : ''}
          ${item.can_recheck && !rechecking ? I18n.t('<button class="btn" type="button" id="review-recheck">重新核对原文与证据</button>') : ''}
          ${item.can_revise && !item.can_recheck && !editing && !regrouping ? I18n.t('<button class="btn" type="button" id="review-revise">修改决定</button>') : ''}
          ${item.can_reassign && !editing && !regrouping ? I18n.t('<button class="btn" type="button" id="review-regroup">调整问题归组</button>') : ''}
          ${ReviewAPI.canReview && options.addForComment && !editing && !regrouping && !rechecking ? I18n.t('<button class="btn" type="button" id="review-add-comment">为这条评论补充问题</button>') : ''}
          ${editing ? I18n.html`<p class="human-review-notice">当前决定：${label(link.status)}。本次将改为${link.status === 'accepted' ? I18n.t('拒绝') : I18n.t('接受')}，原决定保留在历史中。</p>` : ''}
          <div id="review-regroup-root"></div>
          <div id="review-recheck-root"></div>
          <form id="review-decision" ${regrouping || rechecking ? 'hidden' : ''}><label for="review-note">${editing ? I18n.t('修改原因（必填，最多 500 字）') : I18n.t('判断说明（拒绝时必填，最多 500 字）')}</label>
            <textarea id="review-note" maxlength="500" rows="3" ${editable ? '' : 'disabled'}>${esc(note)}</textarea>
            <div class="human-review-actions">
              ${editing ? I18n.html`<button class="btn btn-primary" type="submit" value="${link.status === 'accepted' ? 'reject' : 'accept'}">${link.status === 'accepted' ? I18n.t('改为拒绝') : I18n.t('改为接受')}</button>
                <button class="btn" type="button" id="review-cancel">取消修改</button>` : I18n.html`
              <button class="btn btn-primary" type="submit" value="accept" ${item.can_decide ? '' : 'disabled'}>接受关联</button>
              <button class="btn" type="submit" value="reject" ${item.can_decide ? '' : 'disabled'}>拒绝关联</button>`}
              <button class="btn" type="button" id="review-reload">重新加载</button>
            </div></form>
          <h4>本条关联的操作历史</h4>
          ${item.actions.length ? item.actions.map(a => I18n.html`
            <article class="human-review-history"><strong>${esc(actionLabel(a))}</strong>
            <p>${esc(a.operator)} · ${esc(date(a.created_at))}</p>
            <p>${esc(a.note || I18n.t('未填写说明'))}</p>
            ${['reassign_out', 'merge_out', 'split_out'].includes(a.payload_json?.operation) ? I18n.html`<button class="btn" type="button" data-review-related="${a.payload_json.target_link_id}">查看调整后的关联</button>` : ''}
            ${['reassign_in', 'merge_in', 'split_in'].includes(a.payload_json?.operation) ? I18n.html`<button class="btn" type="button" data-review-related="${a.payload_json.source_link_id}">查看原关联</button>` : ''}
            <details><summary>查看当时原文与证据</summary>
              ${a.payload_json?.operation === 'recheck_evidence' ? I18n.html`<h5>重新复核前</h5><p>${esc(a.payload_json.before?.body ?? I18n.t('历史原文不可用'))}</p><p>旧证据：${esc(a.payload_json.before?.evidence_text || I18n.t('无'))}</p><h5>重新复核后</h5>` : ''}
              <p>${esc(a.payload_json?.snapshot?.body || I18n.t('历史原文不可用'))}</p>
              <p>证据：${esc(a.payload_json?.snapshot?.evidence_text || I18n.t('无'))}</p>
            </details></article>`).join('') : I18n.t('<p>尚无人工操作记录。</p>')}`;
        if (regrouping) ReviewRegroup.mount($('#review-regroup-root'), item, {
          busy: value => { busy = value; options.busy?.(value); },
          cancel: () => { renderDetail(item); message(I18n.t('已取消归组调整，原关联未改变。')); },
          saved: async result => {
            message(I18n.t('归组已调整：原关联已拒绝，目标关联已接受，两边历史均已保存。'));
            await Promise.all([loadDetail(result.target_link_id), loadQueue()]);
          }
        });
        if (rechecking) ReviewRecheck.mount($('#review-recheck-root'), item, {
          busy: value => { busy = value; root.inert = value; options.busy?.(value); },
          cancel: () => { renderDetail(item); message(I18n.t('已取消重新复核，原决定与证据未改变。')); },
          saved: async result => {
            message(I18n.t('重新复核已保存，旧原文、证据及决定保留，问题组已回到待确认。'));
            await Promise.all([loadDetail(result.link_id), loadQueue()]);
          }
        });
      }

      async function loadDetail(id, keepNote = '') {
        const serial = ++generation;
        loadingDetail = true;
        $('#review-decision')?.querySelectorAll('[type=submit]').forEach(b => { b.disabled = true; });
        try {
          const item = await ReviewAPI.request('/comment-issues/' + id);
          if (!root.isConnected || serial !== generation) return;
          if (initialDetail) {
            initialDetail = false;
            status = item.needs_recheck ? 'needs_recheck' : (item.link.status === 'suggested' ? 'pending' : 'reviewed');
            $('#review-filter select[name="status"]').value = status;
            loadQueue();
          }
          pending = null;
          renderDetail(item, keepNote);
          options.selected?.(item.link.id);
        } catch (e) {
          if (serial === generation) {
            message(reason(e.message));
            if (initialDetail && root.isConnected) { initialDetail = false; loadQueue(); }
          }
        }
        finally {
          if (serial === generation) {
            loadingDetail = false;
            if (root.isConnected && !busy && canSubmit()) {
              $('#review-decision')?.querySelectorAll('[type=submit]').forEach(b => { b.disabled = false; });
            }
          }
        }
      }

      root.addEventListener('click', event => {
        if (busy) return;
        if (event.target.id === 'review-open-comment' && current && !loadingDetail) {
          options.openComment(current.comment.id); return;
        }
        if (event.target.id === 'review-open-issue' && current && !loadingDetail) {
          options.openIssue(current.issue.id); return;
        }
        if (event.target.id === 'review-add-comment' && current && !loadingDetail) {
          options.addForComment(current.comment.id); return;
        }
        const related = event.target.closest('[data-review-related]');
        if (related) { message(''); loadDetail(related.dataset.reviewRelated); return; }
        const button = event.target.closest('[data-link]');
        if (button) { message(''); loadDetail(button.dataset.link); }
        if (event.target.id === 'review-prev') { offset -= 20; loadQueue(); }
        if (event.target.id === 'review-next') { offset += 20; loadQueue(); }
        if (event.target.id === 'review-revise' && current?.can_revise && !loadingDetail) {
          pending = null; renderDetail(current, '', true); message(I18n.t('请核对原文并填写修改原因。'));
        }
        if (event.target.id === 'review-regroup' && current?.can_reassign && !loadingDetail) {
          pending = null; renderDetail(current, '', false, true); message(I18n.t('请核对目标问题组与原文证据。'));
        }
        if (event.target.id === 'review-recheck' && current?.can_recheck && !loadingDetail) {
          pending = null; renderDetail(current, '', false, false, true); message(I18n.t('请根据当前原文重新判断。'));
        }
        if (event.target.id === 'review-cancel' && current) {
          pending = null; renderDetail(current); message(I18n.t('已取消修改，原决定未改变。'));
        }
        if (event.target.id === 'review-reload' && current) {
          loadDetail(current.link.id, $('#review-note').value);
          message(I18n.t('请核对重新加载后的内容，再提交决定。'));
        }
      });
      root.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy) return;
        if (event.target.id === 'review-filter') {
          status = new FormData(event.target).get('status'); offset = 0; loadQueue(); return;
        }
        if (event.target.id !== 'review-decision' || loadingDetail || !canSubmit()) return;
        const decision = event.submitter.value, note = $('#review-note').value.trim();
        if (editing && !note) { message(I18n.t('请填写修改原因。')); $('#review-note').focus(); return; }
        if (decision === 'reject' && !note) { message(I18n.t('请填写拒绝原因。')); $('#review-note').focus(); return; }
        const id = current.link.id;
        const content = {decision, note, expected_token: current.token, mode: editing ? 'revise' : 'initial'};
        // Retain the same key after a lost response; changed user intent gets a new key.
        if (!pending || pending.linkId !== id || pending.content !== JSON.stringify(content)) {
          pending = {linkId: id, content: JSON.stringify(content),
            body: {...content, request_id: crypto.randomUUID()}};
        }
        busy = true;
        options.busy?.(true);
        root.querySelectorAll('button').forEach(b => { b.disabled = true; });
        try {
          await ReviewAPI.request('/comment-issues/' + id + '/decisions', pending.body);
          pending = null;
          message(editing ? I18n.t('决定已修改，原决定与修改原因均已保留。') : I18n.t('决定已保存，可在操作历史中查看。'));
          await Promise.all([loadDetail(id), loadQueue()]);
        } catch (e) {
          message(e.status === 409 ? reason(e.message) + I18n.t(' 已保留说明。') : I18n.t('保存未确认，请重试；说明已保留。'));
          // On conflicts do not silently replace the user's snapshot or auto-submit again.
        } finally {
          busy = false;
          options.busy?.(false);
          if (root.isConnected) {
            root.querySelectorAll('button').forEach(b => { b.disabled = false; });
            if (!canSubmit()) $('#review-decision')?.querySelectorAll('[type=submit]').forEach(b => { b.disabled = true; });
            await loadQueue();
          }
        }
      });
      if (options.linkId) loadDetail(options.linkId);
      else loadQueue();
    }
  };
})();
