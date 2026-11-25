(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const statusLabel = s => ({proposed: '待确认', confirmed: '已确认', resolved: '已处理', dismissed: '已驳回'}[s] || s);
  const actionLabel = a => ({confirm: '确认问题', follow_up: '记录跟进', resolve: '标记已处理', dismiss: '驳回问题', reopen: '重新打开', merge_into: '合并问题组', split: '拆分问题组'}[a] || a);
  const groupLabel = issue => issue.merged_into_id ? '已合并' : statusLabel(issue.status);
  const linkLabel = s => ({suggested: '待复核', accepted: '已接受', rejected: '已拒绝'}[s] || s);
  const help = {
    confirm: '确认该问题成立。原有评论关联的决定保持不变，问题将进入“已确认”。',
    follow_up: '记录已采取的措施或当前进展。问题仍保持“已确认”。',
    resolve: '记录处理结果，将问题标记为“已处理”。后续可由人工重新打开。',
    dismiss: '记录驳回原因，将问题标记为“已驳回”。原评论、证据和历史保留。',
    reopen: '重新打开后回到“待确认”，需要重新核对有效证据再确认。'
  };
  const savedMessage = {
    confirm: '问题已确认', follow_up: '跟进记录已保存', resolve: '已记录处理完成',
    dismiss: '问题已驳回', reopen: '问题已重新打开，回到待确认'
  };
  const errors = {
    issue_changed: '问题、证据或原文已变化，请重新加载并核对后再提交。',
    no_valid_accepted_evidence: '至少需要一条当前有效的已接受关联，才能确认问题。',
    invalid_issue_transition: '当前状态不支持此操作，请重新加载。',
    issue_merged: '问题已合并，不能在此继续操作。',
    idempotency_conflict: '提交编号冲突，请重新加载后核对。',
    source_changed: '原文已变化', analysis_not_ready: '正在等待或进行分析',
    analysis_changed: '分析记录已变化', suggestion_superseded: '旧建议已失效',
    invalid_evidence: '证据与原文不一致', scope_mismatch: '所属商品不一致'
  };
  window.IssueWorkflow = {
    mount(root, hooks) {
      let current = null, offset = 0, total = 0, evidenceOffset = 0, evidenceTotal = 0;
      let busy = false, loading = false, pending = null, queueSerial = 0, detailSerial = 0, evidenceSerial = 0;
      root.innerHTML = `<div class="panel human-review-head"><h2>问题组确认与跟进</h2>
        <p>接受评论关联后，再独立确认问题组。确认后可以记录进展、处理完成或驳回；关闭后可人工重开。</p>
        <p id="workflow-identity"></p><form id="workflow-filter" class="human-review-filters">
          <label>问题状态 <select name="status"><option value="proposed">待确认</option>
            <option value="confirmed">已确认</option><option value="resolved">已处理</option>
            <option value="dismissed">已驳回</option><option value="merged">已合并</option><option value="all">全部状态</option></select></label>
          <label>商品编号 <input name="product" placeholder="全部商品"></label>
          <label>类别 <select name="category"><option value="">全部类别</option>
            <option value="quality">质量</option><option value="logistics">物流</option>
            <option value="mismatch">描述不符</option><option value="usability">使用体验</option>
            <option value="other">其他</option></select></label>
          <label>搜索问题 <input name="q" maxlength="200" placeholder="输入问题标题"></label>
          <button class="btn btn-primary">查询问题组</button></form></div>
        <p id="workflow-message" role="status" aria-live="polite"></p>
        <div class="human-review-grid"><section class="panel"><h3 id="workflow-count">问题组列表</h3>
          <div id="workflow-items"></div><div class="human-review-pagination">
            <button class="btn" id="workflow-prev" disabled>上一页问题</button>
            <button class="btn" id="workflow-next" disabled>下一页问题</button></div></section>
          <section class="panel" id="workflow-detail">选择问题组，核对证据与历史。</section></div>`;
      const $ = s => root.querySelector(s);
      if (hooks.detailOnly) {
        root.classList.add('workflow-detail-only');
        $('.human-review-head').hidden = true;
        $('.human-review-grid > section').hidden = true;
      }
      const message = text => { if (root.isConnected) $('#workflow-message').textContent = text; };
      function controls() {
        if (!root.isConnected) return;
        $('#workflow-prev').disabled = offset === 0;
        $('#workflow-next').disabled = offset + 20 >= total;
        if ($('#workflow-save')) $('#workflow-save').disabled = loading || !current.allowed_actions.length;
        if ($('#workflow-evidence-prev')) {
          $('#workflow-evidence-prev').disabled = evidenceOffset === 0;
          $('#workflow-evidence-next').disabled = evidenceOffset + 20 >= evidenceTotal;
        }
      }
      async function loadQueue() {
        if (hooks.detailOnly) return;
        const call = ++queueSerial, form = new FormData($('#workflow-filter'));
        const params = new URLSearchParams({status: form.get('status'), q: form.get('q').trim(),
          limit: '20', offset: String(offset)});
        if (form.get('product').trim()) params.set('product_id', form.get('product').trim());
        if (form.get('category')) params.set('category_id', form.get('category'));
        try {
          const data = await ReviewAPI.request('/review-issues?' + params);
          if (!root.isConnected || call !== queueSerial) return;
          total = data.total;
          if (!data.items.length && offset) { offset = 0; return loadQueue(); }
          $('#workflow-identity').textContent = ReviewAPI.identity(data.operator);
          $('#workflow-count').textContent = `符合条件：${total} 个问题组`;
          $('#workflow-items').innerHTML = data.items.length ? data.items.map(item => `
            <button class="human-review-item" data-workflow-issue="${esc(item.issue.id)}">
              <strong>${esc(item.issue.title)}</strong><span>${groupLabel(item.issue)} · ${esc(item.issue.product_id)}</span>
              <small>当前有效已接受证据 ${item.valid_accepted_count} 条 · 暂不可用 ${item.invalid_accepted_count} 条</small>
            </button>`).join('') : '<p>没有符合条件的问题组。可修改状态或筛选条件。</p>';
          controls();
        } catch (error) { if (call === queueSerial) message('问题组列表加载失败，请重试查询。'); }
      }
      async function loadEvidence() {
        const call = ++evidenceSerial, id = current.issue.id;
        $('#workflow-evidence').textContent = '正在加载证据…';
        $('#workflow-evidence-prev').disabled = $('#workflow-evidence-next').disabled = true;
        try {
          const data = await ReviewAPI.request(`/review-issues/${id}/evidence?limit=20&offset=${evidenceOffset}`);
          if (!root.isConnected || call !== evidenceSerial || current.issue.id !== id) return;
          evidenceTotal = data.total;
          if (!data.items.length && evidenceOffset) { evidenceOffset = 0; return loadEvidence(); }
          $('#workflow-evidence').innerHTML = data.items.length ? data.items.map(item => {
            const r = item.review;
            return `<article class="human-review-history"><p>${linkLabel(r.link.status)} · ${r.link.superseded_at ? '已归档，不计入当前关联' : item.usable ? '当前有效证据' : r.link.status === 'accepted' ? esc(errors[item.blocked_reason] || '暂不可用') : '尚未作为确认依据'}</p>
              <blockquote class="human-review-body">${esc(r.comment.body)}</blockquote>
              <p>关联证据：${esc(r.link.evidence_text || '无')}</p>
              <button class="btn" data-workflow-link="${r.link.id}">查看关联与复核历史</button>
              ${hooks.openComment ? `<button class="btn" data-workflow-comment="${esc(r.comment.id)}">查看评论详情</button>` : ''}</article>`;
          }).join('') : '<p>暂无关联证据，不能确认问题。</p>';
          controls();
        } catch (error) { if (call === evidenceSerial) $('#workflow-evidence').textContent = '证据加载失败，请重新加载问题。'; }
      }
      function describeAction() {
        const action = $('#workflow-action')?.value;
        if (action) $('#workflow-action-help').textContent = help[action];
      }
      function renderDetail(item) {
        item = {...item, allowed_actions: ReviewAPI.canReview ? item.allowed_actions : [],
          can_restructure: item.can_restructure && ReviewAPI.canReview};
        current = item; pending = null; evidenceOffset = 0; evidenceTotal = 0; ++evidenceSerial;
        const issue = item.issue;
        $('#workflow-detail').innerHTML = `<h3>${esc(issue.title)}</h3>
          <p>${esc(issue.platform)} / ${esc(issue.shop_id)} / ${esc(issue.product_id)} · ${esc(issue.category_id)}</p>
          <p>问题状态：<strong>${groupLabel(issue)}</strong> · 重新打开 ${issue.reopen_count} 次</p>
          ${issue.resolved_at ? `<p>处理完成时间：${esc(new Date(issue.resolved_at).toLocaleString())}</p>` : ''}
          <p>当前有效的已接受证据 ${item.valid_accepted_count} 条；暂不可用的已接受关联 ${item.invalid_accepted_count} 条。</p>
          <p>已接受关联 ${issue.accepted_count} 条；待复核建议 ${issue.suggested_count} 条。问题状态不改变这些关联决定。</p>
          ${item.blocked_actions.confirm === 'no_valid_accepted_evidence' ? `<p class="human-review-notice">${errors.no_valid_accepted_evidence}</p>` : ''}
          ${issue.status === 'confirmed' && !item.valid_accepted_count ? '<p class="human-review-notice">当前没有可用的已接受证据，请重新检查关联。历史确认保留，可记录跟进或按实际情况驳回。</p>' : ''}
          ${issue.merged_into_id ? `<p class="human-review-notice">${errors.issue_merged}</p><button class="btn" data-workflow-issue="${esc(issue.merged_into_id)}">查看合并后的问题组</button>` : ''}
          ${issue.split_from_id ? `<button class="btn" data-workflow-issue="${esc(issue.split_from_id)}">查看拆分来源问题组</button>` : ''}
          ${item.can_restructure ? `<div id="workflow-structure-buttons" class="human-review-actions">
            <button class="btn" type="button" data-workflow-structure="merge">合并问题组</button>
            <button class="btn" type="button" data-workflow-structure="split" ${item.active_link_count < 2 ? 'disabled' : ''}>拆分问题组</button></div>` : ''}
          <div id="workflow-structure"></div>
          ${item.allowed_actions.length ? `<form id="workflow-action-form" class="human-review-manual-form">
            <label for="workflow-action">问题组操作</label><select id="workflow-action">${item.allowed_actions.map(a => `<option value="${a}">${actionLabel(a)}</option>`).join('')}</select>
            <p id="workflow-action-help"></p><label for="workflow-note">操作说明 / 跟进记录（必填，最多 500 字）</label>
            <textarea id="workflow-note" maxlength="500" rows="3"></textarea>
            <div class="human-review-actions"><button class="btn btn-primary" id="workflow-save">保存问题组操作</button>
              <button class="btn" type="button" id="workflow-cancel">取消本次填写</button></div>
          </form>` : ''}
          <button class="btn" type="button" id="workflow-reload">重新加载问题</button>
          <h4>关联原文与证据</h4><div id="workflow-evidence"></div>
          <div class="human-review-pagination"><button class="btn" id="workflow-evidence-prev" disabled>上一页证据</button>
            <button class="btn" id="workflow-evidence-next" disabled>下一页证据</button></div>
          <h4>问题组操作历史</h4>${item.actions.length ? item.actions.map(a => `<article class="human-review-history">
            <strong>${a.payload_json?.operation === 'evidence_rechecked' ? '关联原文与证据重新复核' : esc(actionLabel(a.action))}：${statusLabel(a.from_status) || '新建'} → ${a.payload_json?.after?.merged_into_id ? '已合并' : statusLabel(a.to_status)}</strong>
            <p>${esc(a.operator)} · ${esc(new Date(a.created_at).toLocaleString())}</p><p>${esc(a.note)}</p>
            ${a.payload_json?.operation === 'evidence_rechecked' ? `<p>关联 #${a.payload_json.link_id} 已重新核对，问题组需要重新确认。</p>
              <button class="btn" data-workflow-link="${a.payload_json.link_id}">查看重新复核的关联与历史</button>
              <details><summary>查看前后原文与证据</summary><p>旧原文：${esc(a.payload_json.before_evidence?.body ?? '历史原文不可用')}</p>
              <p>旧证据：${esc(a.payload_json.before_evidence?.evidence_text || '无')}</p><p>新原文：${esc(a.payload_json.after_evidence?.body)}</p>
              <p>新证据：${esc(a.payload_json.after_evidence?.evidence_text || '无')}</p></details>`
              : a.payload_json?.transfers ? `<p>“${esc(a.payload_json.source_issue_title)}” → “${esc(a.payload_json.target_issue_title)}” · 转入 ${a.payload_json.copied_count} 条，重复保留 ${a.payload_json.deduplicated_count} 条（其中恢复归档 ${a.payload_json.reactivated_count || 0} 条）</p>
              <button class="btn" data-workflow-issue="${esc(a.issue_id === a.payload_json.source_issue_id ? a.payload_json.target_issue_id : a.payload_json.source_issue_id)}">查看另一侧问题组</button>
              <details><summary>查看整理时的关联与证据</summary>${a.payload_json.transfers.map(t => `<p>${linkLabel(t.before_source.status)} · ${esc(t.before_source.body)}<br>证据：${esc(t.before_source.evidence_text)}</p>
                <button class="btn" data-workflow-link="${t.source_link_id}">查看原关联历史</button><button class="btn" data-workflow-link="${t.target_link_id}">查看目标关联历史</button>`).join('')}</details>`
              : `<details><summary>查看当时的确认依据</summary><p>当时有效已接受证据：${a.payload_json?.valid_accepted_count ?? '未知'} 条</p>
              ${(a.payload_json?.accepted_evidence || []).map(e => `<p>${e.usable ? '有效' : '暂不可用'} · ${esc(e.body)}<br>证据：${esc(e.evidence_text)}</p>`).join('') || '<p>当时没有已接受证据。</p>'}</details>`}</article>`).join('') : '<p>尚无问题组操作。关联的人工历史可通过上方入口查看。</p>'}`;
        describeAction(); loadEvidence();
      }
      async function loadDetail(id) {
        const call = ++detailSerial; ++evidenceSerial;
        loading = true; $('#workflow-detail').inert = true;
        try {
          const data = await ReviewAPI.request('/review-issues/' + id);
          if (root.isConnected && call === detailSerial) { renderDetail(data); hooks.selected?.(data.issue.id); }
        } catch (error) {
          if (root.isConnected && call === detailSerial) {
            message(error.status === 404 ? '未找到该问题组，请返回列表重新选择。' : '问题详情加载失败，请重新加载。');
            if (!current) $('#workflow-detail').innerHTML = '<button class="btn" id="workflow-retry">重试加载问题</button>';
          }
        }
        finally {
          if (root.isConnected && call === detailSerial) {
            loading = false; $('#workflow-detail').inert = false; controls();
          }
        }
      }
      root.addEventListener('change', event => {
        if (event.target.id === 'workflow-action') { pending = null; describeAction(); }
      });
      root.addEventListener('click', event => {
        if (busy) return;
        const comment = event.target.closest('[data-workflow-comment]');
        if (comment) { hooks.openComment(comment.dataset.workflowComment); return; }
        if (event.target.id === 'workflow-retry') { loadDetail(hooks.issueId); return; }
        const structure = event.target.closest('[data-workflow-structure]');
        if (structure && current && !loading) {
          if ($('#workflow-action-form')) $('#workflow-action-form').hidden = true;
          $('#workflow-structure-buttons').hidden = true;
          IssueStructure.mount($('#workflow-structure'), current, structure.dataset.workflowStructure, {
            openReview: id => hooks.openReview(id),
            busy: value => { busy = value; root.inert = value; hooks.busy(value); },
            cancel: () => { renderDetail(current); message('已取消整理，问题组和历史未改变。'); },
            saved: async result => {
              message(`${result.operation === 'merge' ? '合并' : '拆分'}已保存，关联决定及原历史保留。请重新核对待确认的问题组。`);
              await Promise.all([loadDetail(result.target_issue_id), loadQueue()]);
            }
          });
        }
        const issue = event.target.closest('[data-workflow-issue]'), link = event.target.closest('[data-workflow-link]');
        if (issue) { message(''); loadDetail(issue.dataset.workflowIssue); }
        if (link) hooks.openReview(link.dataset.workflowLink);
        if (event.target.id === 'workflow-prev') { offset -= 20; loadQueue(); }
        if (event.target.id === 'workflow-next') { offset += 20; loadQueue(); }
        if (event.target.id === 'workflow-evidence-prev') { evidenceOffset -= 20; loadEvidence(); }
        if (event.target.id === 'workflow-evidence-next') { evidenceOffset += 20; loadEvidence(); }
        if (event.target.id === 'workflow-reload' && current) loadDetail(current.issue.id);
        if (event.target.id === 'workflow-cancel') {
          $('#workflow-note').value = ''; pending = null; message('已取消本次填写，问题状态与历史未改变。');
        }
      });
      root.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy) return;
        if (event.target.id === 'workflow-filter') { offset = 0; loadQueue(); return; }
        if (event.target.id !== 'workflow-action-form' || loading || !current) return;
        const action = $('#workflow-action').value, note = $('#workflow-note').value.trim();
        if (!current.allowed_actions.includes(action)) return;
        if (!note) { message('请填写操作说明或跟进记录。'); $('#workflow-note').focus(); return; }
        const content = {action, note, expected_token: current.token}, key = JSON.stringify(content);
        if (!pending || pending.key !== key) pending = {key, body: {...content, request_id: crypto.randomUUID()}};
        busy = true; root.inert = true; hooks.busy(true);
        try {
          await ReviewAPI.request(`/issues/${current.issue.id}/actions`, pending.body);
          pending = null; message(`${savedMessage[action]}，操作说明和当时依据均已保留。`);
          await Promise.all([loadDetail(current.issue.id), loadQueue()]);
        } catch (error) { message((errors[error.message] || '保存未确认，请重试。') + ' 输入内容已保留。'); }
        finally { busy = false; root.inert = false; hooks.busy(false); controls(); }
      });
      if (hooks.issueId) $('#workflow-filter select[name="status"]').value = 'all';
      loadQueue();
      if (hooks.issueId) loadDetail(hooks.issueId);
    }
  };
})();
