(function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const label = s => ({suggested: '待复核', accepted: '已接受', rejected: '已拒绝'}[s] || s);
  const errors = {
    issue_changed: '原问题组、评论或证据已变化，请取消并重新加载问题后核对。',
    target_changed: '目标问题组已变化，请重新查询并选择目标。',
    duplicate_link_conflict: '同一评论的决定、证据或归组历史冲突，请先核对两侧关联。',
    split_requires_subset: '必须选择当前组内的部分未归档关联，并至少留一条在原组。',
    duplicate_issue: '同类别已有同名活动问题组，请换用明确的新标题或考虑合并。',
    issue_not_active: '问题组已关闭或合并，请重新核对。',
    no_active_links: '当前没有可以整理的关联。',
    scope_mismatch: '只能整理同平台、同店铺、同商品的问题组。',
    idempotency_conflict: '请求编号冲突，请取消后重新核对。'
  };
  window.IssueStructure = {
    mount(root, source, mode, hooks) {
      const merging = mode === 'merge';
      let selectedTarget = null, targets = [], offset = 0, total = 0, serial = 0;
      let busy = false, loading = false, pending = null;
      const selected = new Set();
      root.innerHTML = `<section class="human-review-regroup"><h4>${merging ? '合并到已有问题组' : '拆分为新问题组'}</h4>
        <p>${merging ? '原组将标记为已合并，目标组回到待确认。同一评论只有决定和证据一致时才去重；存在冲突时不允许合并。'
          : '选择部分关联移入一个新问题组，至少留一条在原组。原组和新组都回到待确认。一次最多选择 100 条。'}</p>
        <p>接受／拒绝／待复核决定保持原样，旧关联与历史保留；失效证据不会因整理而变成有效。</p>
        ${merging ? '<form id="structure-search"><label>搜索合并目标<input name="q" maxlength="200"></label><button class="btn">查询合并目标</button></form>' : ''}
        <div id="structure-options">正在加载…</div>
        <div class="human-review-pagination"><button class="btn" id="structure-prev" disabled>上一页选项</button>
          <button class="btn" id="structure-next" disabled>下一页选项</button></div>
        <p id="structure-selection" aria-live="polite"></p>
        <form id="structure-form" class="human-review-manual-form">
          ${merging ? '' : `<label>新问题标题<input id="structure-title" maxlength="200" required></label>
            <label>新问题类别<select id="structure-category"><option value="quality">质量</option>
            <option value="logistics">物流</option><option value="mismatch">描述不符</option>
            <option value="usability">使用体验</option><option value="other">其他</option></select></label>`}
          <label>整理原因（必填，最多 500 字）<textarea id="structure-note" maxlength="500" rows="3"></textarea></label>
          <p id="structure-message" role="status"></p>
          <button class="btn btn-primary" id="structure-save" disabled>${merging ? '保存合并' : '保存拆分'}</button>
          <button class="btn" type="button" id="structure-cancel">取消整理</button>
        </form></section>`;
      const $ = s => root.querySelector(s);
      const message = text => { if (root.isConnected) $('#structure-message').textContent = text; };
      function controls() {
        if (!root.isConnected) return;
        $('#structure-prev').disabled = loading || offset === 0;
        $('#structure-next').disabled = loading || offset + 20 >= total;
        $('#structure-save').disabled = loading || (merging ? !selectedTarget :
          !selected.size || selected.size >= source.active_link_count || selected.size > 100);
        $('#structure-selection').textContent = merging
          ? selectedTarget ? `将“${source.issue.title}”合并到“${selectedTarget.target.issue.title}”：转入 ${selectedTarget.copied_count} 条，重复关联保留目标侧 ${selectedTarget.deduplicated_count} 条（其中恢复归档 ${selectedTarget.reactivated_count} 条）。目标组将重新待确认。` : '请选择合并目标。'
          : `已选 ${selected.size} 条；原组当前有 ${source.active_link_count} 条未归档关联。`;
      }
      async function load() {
        const call = ++serial; loading = true; controls();
        const query = merging ? new FormData($('#structure-search')).get('q').trim() : '';
        const url = merging ? `/review-issues/${source.issue.id}/merge-targets?q=${encodeURIComponent(query)}`
          : `/review-issues/${source.issue.id}/evidence?`;
        try {
          const data = await ReviewAPI.request(`${url}&limit=20&offset=${offset}`);
          if (!root.isConnected || call !== serial) return;
          total = data.total; targets = data.items;
          $('#structure-options').innerHTML = targets.length ? targets.map(item => {
            if (merging) {
              const issue = item.target.issue;
              return `<article class="human-review-history"><button class="human-review-item" type="button" data-structure-target="${esc(issue.id)}" ${item.selectable ? '' : 'disabled'}>
                <strong>${esc(issue.title)}</strong><span>${esc(issue.category_id)} · 已接受 ${issue.accepted_count} 条 · 待复核 ${issue.suggested_count} 条</span>
                <small>转入 ${item.copied_count} 条 · 相同重复 ${item.deduplicated_count} 条 · 恢复归档 ${item.reactivated_count} 条${item.conflicts.length ? ` · 冲突 ${item.conflicts.length} 条` : ''}</small></button>
                ${item.conflicts.map(c => `<p>同一评论在目标中${c.reason === 'target_link_archived' ? '已有归档关联' : '有不同决定或证据'}，不能直接合并。</p>
                  <button class="btn" type="button" data-structure-link="${c.source_link_id}">查看原组冲突关联</button>
                  <button class="btn" type="button" data-structure-link="${c.target_link_id}">查看目标冲突关联</button>`).join('')}</article>`;
            }
            const r = item.review, archived = !!r.link.superseded_at;
            return `<article class="human-review-history"><label><input class="structure-checkbox" type="checkbox" data-structure-link-id="${r.link.id}" ${selected.has(r.link.id) ? 'checked' : ''} ${archived ? 'disabled' : ''}>
              ${archived ? '已归档，不可选择' : '选择关联'} #${r.link.id} · ${label(r.link.status)}</label>
              <blockquote class="human-review-body">${esc(r.comment.body)}</blockquote><p>证据：${esc(r.link.evidence_text || '无')}</p></article>`;
          }).join('') : '<p>没有可选记录。</p>';
        } catch (e) { if (call === serial) message(errors[e.message] || '加载失败，请重试。'); }
        finally { if (call === serial) { loading = false; controls(); } }
      }
      root.addEventListener('click', event => {
        if (busy) return;
        const target = event.target.closest('[data-structure-target]');
        if (target && !loading) {
          selectedTarget = targets.find(t => t.target.issue.id === target.dataset.structureTarget);
          pending = null; controls();
        }
        const link = event.target.closest('[data-structure-link]');
        if (link) hooks.openReview(link.dataset.structureLink);
        if (event.target.id === 'structure-cancel') hooks.cancel();
        if (event.target.id === 'structure-prev') { offset -= 20; load(); }
        if (event.target.id === 'structure-next') { offset += 20; load(); }
      });
      root.addEventListener('change', event => {
        const id = event.target.dataset.structureLinkId;
        if (id) { event.target.checked ? selected.add(Number(id)) : selected.delete(Number(id)); pending = null; controls(); }
      });
      root.addEventListener('submit', async event => {
        event.preventDefault(); event.stopPropagation();
        if (busy) return;
        if (event.target.id === 'structure-search') {
          offset = 0; selectedTarget = null; pending = null; load(); return;
        }
        if (event.target.id !== 'structure-form' || loading || $('#structure-save').disabled) return;
        const note = $('#structure-note').value.trim();
        if (!note) { message('请填写整理原因。'); $('#structure-note').focus(); return; }
        const content = {expected_token: source.token, note};
        if (merging) Object.assign(content, {target_issue_id: selectedTarget.target.issue.id,
          expected_target_token: selectedTarget.target.token});
        else Object.assign(content, {comment_issue_ids: [...selected].sort((a, b) => a - b),
          new_issue: {title: $('#structure-title').value.trim(), category_id: $('#structure-category').value}});
        const key = JSON.stringify(content);
        if (!pending || pending.key !== key) pending = {key, body: {...content, request_id: crypto.randomUUID()}};
        busy = true; root.inert = true; hooks.busy(true);
        try {
          const result = await ReviewAPI.request(`/issues/${source.issue.id}/${mode}`, pending.body);
          pending = null; await hooks.saved(result);
        } catch (e) { message((errors[e.message] || '保存未确认，请重试。') + ' 填写内容已保留。'); }
        finally { busy = false; root.inert = false; hooks.busy(false); }
      });
      if (!merging) $('#structure-category').value = source.issue.category_id;
      load();
    }
  };
})();
