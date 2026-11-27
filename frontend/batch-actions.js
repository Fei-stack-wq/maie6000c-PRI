(function () {
  'use strict';
  const {tr, esc, confirm} = WorkbenchUI;
  function html(batch) {
    if (!ReviewAPI.canReview) return '';
    return `<div class="batch-actions" data-batch-id="${esc(batch.id)}">
      ${batch.deleted_at ? `<button class="btn" data-batch-action="restore">${tr('恢复批次', 'Restore batch')}</button>` :
        `${!batch.stopped_at && batch.unfinished_rows > 0 ? `<button class="btn" data-batch-action="stop">${tr('停止剩余分析', 'Stop remaining analysis')}</button>` : ''}
        <button class="btn" data-batch-action="trash">${tr('移到回收站', 'Move to trash')}</button>`}
      <button class="btn btn-danger" data-batch-action="purge">${tr('永久删除', 'Delete permanently')}</button>
      <p class="batch-action-feedback" role="status"></p></div>`;
  }
  function mount(root, changed) {
    root.addEventListener('click', async event => {
      const button = event.target.closest('button[data-batch-action]');
      if (!button || !root.contains(button) || button.disabled) return;
      const host = button.closest('[data-batch-id]'), action = button.dataset.batchAction, id = host.dataset.batchId;
      const message = {
        stop: tr('停止此批次剩余分析？已保存结果保留，未完成记录将被取消，不能自动继续。', 'Stop remaining analysis for this batch? Saved results remain; unfinished records will be cancelled and will not resume automatically.'),
        trash: tr('将此批次移到回收站？剩余分析会停止，其他批次不受影响。', 'Move this batch to trash? Remaining analysis will stop. Other batches are unaffected.'),
        restore: tr('恢复此批次？已取消的任务仍保持取消。', 'Restore this batch? Cancelled jobs will stay cancelled.'),
        purge: tr('永久删除此批次的导入、分析、归组与复核记录？此操作不能撤销，其他批次不受影响。', 'Permanently delete this batch and its import, analysis, grouping and review records? This cannot be undone. Other batches are unaffected.')
      }[action];
      if (!await confirm(message, action === 'purge')) return;
      const feedback = host.querySelector('.batch-action-feedback');
      host.querySelectorAll('button').forEach(item => item.disabled = true);
      root.setAttribute('aria-busy', 'true');
      feedback.textContent = tr('正在保存操作…', 'Saving operation…');
      try {
        await ReviewAPI.request('/review-batches/' + encodeURIComponent(id) +
          (action === 'purge' ? '?permanent=true' : '/' + action),
          action === 'purge' ? undefined : {}, action === 'purge' ? {method: 'DELETE'} : {});
        if (root.isConnected) await changed(action, id);
      } catch (_) {
        if (feedback.isConnected) feedback.textContent = tr('操作未确认完成，请刷新批次记录后核对。', 'Operation was not confirmed. Refresh batch records and check the result.');
      } finally {
        if (host.isConnected) host.querySelectorAll('button').forEach(item => item.disabled = false);
        if (root.isConnected) root.setAttribute('aria-busy', 'false');
      }
    });
  }
  function records(root, batchId) {
    const opener = document.createElement('button');
    opener.className = 'btn'; opener.type = 'button';
    opener.textContent = tr('查看原始导入记录（含已取消）', 'View imported records (including cancelled)');
    const area = document.createElement('div');
    area.className = 'batch-records';
    root.append(opener, area);
    let offset = 0;
    opener.addEventListener('click', async () => {
      opener.disabled = true;
      try {
        const data = await ReviewAPI.request(`/review-batches/${encodeURIComponent(batchId)}/records?limit=50&offset=${offset}`);
        if (!root.isConnected) return;
        area.insertAdjacentHTML('beforeend', data.items.map(item => `<article class="board-entry">
          <p>${esc(item.product_id)} · ${item.analysis_status === 'cancelled' ? tr('已取消', 'Cancelled') : esc(item.analysis_status)}</p>
          <blockquote>${esc(item.body)}</blockquote></article>`).join(''));
        offset += data.items.length;
        opener.textContent = offset < data.total ? tr('继续加载原始记录', 'Load more imported records') : tr('已显示全部原始记录', 'All imported records shown');
        if (offset >= data.total) opener.remove();
      } catch (_) { opener.textContent = tr('加载失败，点击重试', 'Could not load. Click to retry'); }
      finally { opener.disabled = false; }
    });
  }
  window.BatchActions = {html, mount, records};
})();
