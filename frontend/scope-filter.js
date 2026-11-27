(function () {
  'use strict';
  const {tr, esc, allOptions, parseSelection, label} = WorkbenchUI;
  function html(values, issues) {
    return `<form id="scope-filter" class="scope-filter panel">
      <div class="scope-picker-grid">
        <details class="scope-picker" id="scope-batches"><summary>${tr('选择批次', 'Select batches')}</summary>
          <input type="search" aria-label="${tr('搜索批次选项', 'Search batch options')}" placeholder="${tr('搜索文件名或批次编号', 'Search filename or batch ID')}">
          <div class="scope-options" role="group" aria-label="${tr('批次选项', 'Batch options')}"></div></details>
        <details class="scope-picker" id="scope-products"><summary>${tr('选择商品', 'Select products')}</summary>
          <input type="search" aria-label="${tr('搜索商品选项', 'Search product options')}" placeholder="${tr('搜索平台、店铺或商品编号', 'Search platform, store or product ID')}">
          <div class="scope-options" role="group" aria-label="${tr('商品选项', 'Product options')}"></div></details>
      </div>
      <p class="scope-filter-hint">${tr('不指定选项时查看全部。商品选项随所选批次更新；可以勾选多个。', 'Leave selections empty for all. Product options follow the selected batches; multiple selections are supported.')}</p>
      <div class="scope-secondary">
        ${issues ? `<label>${tr('类别', 'Category')}<select name="category_id">
          <option value="">${tr('全部类别', 'All categories')}</option>${Object.entries(WorkbenchUI.categories).map(([key, text]) =>
            `<option value="${key}" ${values.category_id === key ? 'selected' : ''}>${esc(text)}</option>`).join('')}</select></label>` :
        `<label>${tr('分析状态', 'Analysis status')}<select name="analysis_status">${options({
          '': tr('全部状态', 'All statuses'), received: tr('已接收', 'Received'), queued: tr('等待分析', 'Queued'),
          analyzing: tr('分析中', 'Analyzing'), analyzed: tr('分析完成', 'Analyzed'), failed: tr('分析失败', 'Failed')
        }, values.analysis_status)}</select></label>
        <label>${tr('AI 判断', 'AI decision')}<select name="has_issue">${options({
          '': tr('全部判断', 'All decisions'), yes: tr('发现问题', 'Issue found'),
          no: tr('未发现问题', 'No issue found'), unknown: tr('无法判断', 'Unknown')
        }, values.has_issue)}</select></label>`}
        <label>${issues ? tr('搜索问题或评论', 'Search issues or reviews') : tr('搜索原文', 'Search review text')}
          <input name="q" maxlength="200" value="${esc(values.q)}"></label>
        <button class="btn btn-primary" type="submit" disabled>${tr('应用筛选', 'Apply filters')}</button>
        <button class="btn" type="button" id="scope-clear">${tr('清除筛选', 'Clear filters')}</button>
      </div><p id="scope-filter-notice" role="status"></p></form>`;
  }
  function options(values, selected) {
    return Object.entries(values).map(([key, text]) => `<option value="${esc(key)}" ${key === selected ? 'selected' : ''}>${esc(text)}</option>`).join('');
  }
  async function mount(form, values, submit) {
    const selection = parseSelection(values);
    let batches = [], products = [], serial = 0;
    const notice = form.querySelector('#scope-filter-notice');
    const apply = form.querySelector('[type="submit"]');
    const batchBox = form.querySelector('#scope-batches');
    const productBox = form.querySelector('#scope-products');
    const connected = () => form.isConnected;
    function draw(box, items, selected, allText, itemLabel) {
      const query = box.querySelector('input[type=search]').value.toLocaleLowerCase();
      box.querySelector('summary').textContent = allText + (selected.length ? ` (${selected.length})` : tr('（全部）', ' (all)'));
      box.querySelector('.scope-options').innerHTML = `<label><input type="checkbox" data-all ${selected.length ? '' : 'checked'}>${tr('全部', 'All')}</label>` +
        items.filter(item => (itemLabel(item) + ' ' + (item.id || item.key)).toLocaleLowerCase().includes(query)).map(item => {
          const key = item.id || item.key;
          return `<label><input type="checkbox" value="${esc(key)}" ${selected.includes(key) ? 'checked' : ''}>${esc(itemLabel(item))}</label>`;
        }).join('');
    }
    const drawBatches = () => draw(batchBox, batches, selection.batches, tr('批次', 'Batches'), label);
    const productLabel = item => `${item.platform} / ${item.shop_id} / ${item.product_id}`;
    const drawProducts = () => draw(productBox, products, selection.products, tr('商品', 'Products'), productLabel);
    async function loadProducts(clearInvalid) {
      const call = ++serial;
      apply.disabled = true;
      notice.textContent = tr('正在读取完整商品选项…', 'Loading all product options…');
      try {
        const result = await allOptions('/catalog/products', {batch_ids: selection.batches.join(',')});
        if (!connected() || call !== serial) return;
        products = result;
        if (clearInvalid) selection.products = selection.products.filter(key => products.some(item => item.key === key));
        if (!selection.products.length && values.product_id && !clearInvalid) {
          selection.products = products.filter(item => item.product_id === values.product_id).map(item => item.key);
        }
        drawProducts();
        const missing = selection.products.some(key => !products.some(item => item.key === key));
        notice.textContent = missing ? tr('部分商品已不在当前范围，请清除或重新选择。', 'Some selected products are outside this scope. Clear or reselect them.') : '';
        apply.disabled = missing;
      } catch (_) {
        if (connected() && call === serial) notice.textContent = tr('选项加载失败，请刷新页面后重试。', 'Could not load options. Refresh the page and try again.');
      }
    }
    function changed(event, kind) {
      const input = event.target;
      if (input.type !== 'checkbox') return;
      const key = kind === 'batches' ? 'batches' : 'products';
      if (input.hasAttribute('data-all')) selection[key] = [];
      else selection[key] = input.checked ? [...new Set([...selection[key], input.value])] : selection[key].filter(value => value !== input.value);
      if (kind === 'batches') { drawBatches(); loadProducts(true); } else drawProducts();
    }
    batchBox.addEventListener('change', event => changed(event, 'batches'));
    productBox.addEventListener('change', event => changed(event, 'products'));
    batchBox.querySelector('input[type=search]').addEventListener('input', drawBatches);
    productBox.querySelector('input[type=search]').addEventListener('input', drawProducts);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (apply.disabled) return;
      const next = Object.fromEntries(new FormData(form));
      next.batch_ids = selection.batches.join(',');
      next.product_keys = selection.products.length ? JSON.stringify(selection.products.map(key => JSON.parse(key))) : '';
      next.page = '1'; submit(next);
    });
    form.querySelector('#scope-clear').addEventListener('click', () => submit({}));
    batches = await allOptions('/catalog/batches');
    if (!connected()) return;
    drawBatches();
    if (selection.batches.some(id => !batches.some(batch => batch.id === id))) {
      notice.textContent = tr('所选批次已不可用，请清除筛选或重新选择。', 'A selected batch is unavailable. Clear filters or choose another batch.');
      return;
    }
    await loadProducts(false);
  }
  window.ScopeFilter = {html, mount};
})();
