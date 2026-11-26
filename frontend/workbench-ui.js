(function () {
  'use strict';
  const tr = (zh, en) => I18n.language === 'en' ? en : zh;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const categories = {
    quality: tr('质量', 'Quality'), logistics: tr('物流', 'Delivery'),
    mismatch: tr('描述不符', 'Not as described'), usability: tr('使用体验', 'User experience'),
    other: tr('其他', 'Other')
  };
  const badge = key => `<span class="category-badge category--${Object.hasOwn(categories, key) ? key : 'other'}">${esc(categories[key] || key)}</span>`;
  const rating = value => value == null ? tr('无', 'None') : esc(value) + ' / 5';
  const date = value => value ? new Date(value).toLocaleString(I18n.locale) : '—';
  const label = batch => (batch.file_ref || tr('未命名批次', 'Unnamed batch')) + ' · ' + date(batch.created_at);
  function confirm(message, destructive = false) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog');
      dialog.className = 'language-confirm';
      dialog.setAttribute('aria-labelledby', 'workbench-confirm-title');
      dialog.innerHTML = `<p id="workbench-confirm-title">${esc(message)}</p><form method="dialog">
        <button class="btn" value="cancel" autofocus>${tr('取消', 'Cancel')}</button>
        <button class="btn ${destructive ? 'btn-danger' : 'btn-primary'}" value="confirm">${tr('确认', 'Confirm')}</button></form>`;
      const focused = document.activeElement;
      dialog.addEventListener('close', () => {
        const confirmed = dialog.returnValue === 'confirm';
        dialog.remove(); focused?.focus(); resolve(confirmed);
      }, {once: true});
      document.body.appendChild(dialog); dialog.showModal();
    });
  }
  async function allOptions(path, params = {}) {
    const rows = [];
    for (let offset = 0; ; ) {
      const query = new URLSearchParams({...params, limit: '200', offset: String(offset)});
      const page = await ReviewAPI.request(path + '?' + query);
      if (!Array.isArray(page.items) || !Number.isInteger(page.total)) throw Error('invalid_catalog');
      rows.push(...page.items);
      offset += page.items.length;
      if (offset >= page.total) return rows;
      if (!page.items.length) throw Error('incomplete_catalog');
    }
  }
  function parseSelection(values) {
    const batches = values.batch_ids ? values.batch_ids.split(',').filter(Boolean) : values.batch_id ? [values.batch_id] : [];
    let products = [];
    try {
      const parsed = values.product_keys ? JSON.parse(values.product_keys) : [];
      if (!Array.isArray(parsed) || parsed.some(row => !Array.isArray(row) || row.length !== 3 ||
          row.some(value => typeof value !== 'string'))) throw Error('invalid_scope');
      products = parsed.map(row => JSON.stringify(row));
    } catch (_) { throw Error('invalid_scope'); }
    return {batches: [...new Set(batches)], products: [...new Set(products)]};
  }
  window.WorkbenchUI = {tr, esc, categories, badge, rating, date, label, confirm, allOptions, parseSelection};
})();
