(function () {
  'use strict';
  const {tr, esc, badge, rating, date, label} = WorkbenchUI;
  const anchor = (href, text, style = 'btn') => `<a class="${style}" href="${esc(href)}">${esc(text)}</a>`;
  const analysis = {received: tr('已接收', 'Received'), queued: tr('等待分析', 'Queued'),
    analyzing: tr('分析中', 'Analyzing'), analyzed: tr('分析完成', 'Analyzed'),
    failed: tr('分析失败', 'Failed'), cancelled: tr('已取消', 'Cancelled')};
  const verdict = {yes: tr('发现问题', 'Issue found'), no: tr('未发现问题', 'No issue found'), unknown: tr('无法判断', 'Unknown')};
  function mount(root, route) {
    root.innerHTML = '<div id="review-workspace" aria-busy="false"></div>';
    root = root.firstElementChild;
    const issues = route.route === 'issues', values = route.filters;
    const page = Number(values.page || 1), pageSize = issues ? 5 : 20;
    let generation = 0, total = 0, loading = false, acting = false, lanes = [];
    const returnTo = ProductRoutes.href(route.route, null, values);
    root.innerHTML = `<section class="panel"><h2>${issues ? tr('按批次查看问题', 'Issues by batch') : tr('评论', 'Reviews')}</h2>
      <p>${issues ? tr('先按批次和商品查看，再在每个类别中核对已归组及待确认内容。', 'Browse by batch and product, then check grouped and pending entries within each category.') :
      tr('选择批次和商品，查看评论原文及分析结果。', 'Select batches and products to view review text and analysis results.')}</p></section>
      ${ScopeFilter.html(values, issues)}
      <div class="live-product-summary"><p id="scope-count" role="status"></p><button class="btn" id="scope-refresh">${tr('刷新结果', 'Refresh results')}</button></div>
      <div id="scope-results" class="${issues ? 'issue-board' : 'live-product-cards'}"></div>
      <div class="human-review-pagination"><button class="btn" id="scope-prev">${tr('上一页', 'Previous')}</button>
        <span id="scope-page"></span><button class="btn" id="scope-next">${tr('下一页', 'Next')}</button></div>`;
    const $ = selector => root.querySelector(selector);
    function navigate(next) {
      const hash = ProductRoutes.href(route.route, null, next);
      if (window.location.hash === hash) load(); else window.location.hash = hash;
    }
    function controls() {
      $('#scope-prev').disabled = loading || acting || page <= 1;
      $('#scope-next').disabled = loading || acting || page * pageSize >= total;
      $('#scope-refresh').disabled = loading || acting;
    }
    function commentCard(comment) {
      return `<article class="panel live-product-card">
        <p class="live-product-scope">${esc(comment.platform)} / ${esc(comment.shop_id)} / ${esc(comment.product_id)}</p>
        <p class="live-product-meta">${tr('批次编号', 'Batch ID')}: ${esc(comment.batch_id)}</p>
        <div class="live-product-tags"><span>${esc(analysis[comment.analysis_status] || comment.analysis_status)}</span>
          <span>${esc(verdict[comment.has_issue] || tr('暂无结果', 'No result yet'))}</span></div>
        <div class="category-tags">${(comment.issue_categories || []).map(badge).join('')}</div>
        <blockquote class="human-review-body">${esc(comment.body)}</blockquote>
        <p class="live-product-meta">${tr('评分', 'Rating')}: ${rating(comment.rating)}${comment.review_date ? ' · ' + esc(date(comment.review_date)) : ''}</p>
        ${anchor(ProductRoutes.href('comments', comment.id, values), tr('查看原文与关联', 'View text and links'))}</article>`;
    }
    function entry(item, pending) {
      const l = item.link, c = item.comment;
      const source = pending ? tr('待人工确认', 'Needs human confirmation') : l.auto_confirmed ? tr('AI 自动确认', 'AI auto-confirmed') :
        l.origin === 'human' ? tr('人工已调整', 'Human assigned') : tr('人工已确认', 'Human confirmed');
      return `<article class="board-entry ${pending ? 'board-entry--pending' : ''}" data-link-id="${l.id}">
        <div class="board-entry-head">${[item.issue.category_id, ...(c.issue_categories || []).filter(category => category !== item.issue.category_id)].map(badge).join('')}<span class="decision-badge">${source}</span></div>
        <h5>${esc(item.issue.title)}</h5>
        <blockquote class="human-review-body">${esc(c.body)}</blockquote>
        <p class="board-evidence"><strong>${tr('原文证据', 'Evidence')}:</strong> ${esc(l.evidence_text || '—')}</p>
        ${item.needs_recheck ? `<p class="human-review-notice">${tr('原文或证据需要重新核对。', 'The text or evidence needs rechecking.')}</p>` : ''}
        <div class="human-review-actions">
          ${pending && item.can_decide && ReviewAPI.canReview ? `<button class="btn btn-primary" data-accept="${l.id}">${tr('确认归组', 'Confirm assignment')}</button>` : ''}
          ${anchor(ProductRoutes.reviewHref('decisions', l.id, returnTo), ReviewAPI.canReview ? tr('核对 / 调整归组', 'Review / reassign') : tr('查看证据与历史', 'View evidence and history'))}
          ${anchor(ProductRoutes.href('comments', c.id, values), tr('查看原文', 'View review'))}
          ${anchor(ProductRoutes.href('issues', item.issue.id, values), tr('问题跟进', 'Issue follow-up'))}
        </div></article>`;
    }
    function lane(batch, product, category, side) {
      const data = category[side], index = lanes.length;
      lanes.push({batch, product, category: category.category_id, side, offset: data.items.length,
        total: data.total, items: new Map(data.items.map(item => [String(item.link.id), item]))});
      const pending = side === 'pending';
      return `<section class="board-lane" data-lane="${index}">${laneContent(data, pending, index)}</section>`;
    }
    function laneContent(data, pending, index) {
      return `<h4>${pending ? tr('待人工确认', 'Needs human confirmation') : tr('已归组', 'Grouped')} <span>${data.total}</span></h4>
        <div class="board-entries">${data.items.map(item => entry(item, pending)).join('') ||
          `<p class="board-empty">${pending ? tr('暂无待确认内容。', 'No pending entries.') : tr('暂无已归组内容。', 'No grouped entries yet.')}</p>`}</div>
        ${data.items.length < data.total ? `<button class="btn" data-more="${index}">${tr('加载更多', 'Load more')}</button>` : ''}
        <p class="board-lane-notice" role="status"></p>`;
    }
    async function refreshCategory(state, section, button) {
      const related = lanes.map((lane, index) => ({lane, index})).filter(({lane}) =>
        lane.batch.id === state.batch.id && lane.product.platform === state.product.platform &&
        lane.product.shop_id === state.product.shop_id && lane.product.product_id === state.product.product_id &&
        lane.category === state.category);
      const pages = await Promise.all(related.map(async ({lane, index}) => {
        const wanted = Math.max(5, lane.offset), items = [];
        let total = 0;
        do {
          const params = new URLSearchParams({batch_id: lane.batch.id, platform: lane.product.platform,
            shop_id: lane.product.shop_id, product_id: lane.product.product_id, category_id: lane.category,
            decision: lane.side, limit: String(Math.min(100, wanted - items.length)), offset: String(items.length),
            status: values.status || 'all', q: values.q || ''});
          const data = await ReviewAPI.request('/issue-board/entries?' + params);
          total = data.total;
          items.push(...data.items);
          if (!data.items.length && items.length < Math.min(wanted, total)) throw Error('incomplete_lane');
        } while (items.length < Math.min(wanted, total));
        return {lane, index, data: {items, total}};
      }));
      if (!root.isConnected || !section.isConnected) return;
      // Keep the next review in place when the confirmed card moves to Grouped.
      // Capture after the requests so scrolling while waiting is also respected.
      const card = button.closest('.board-entry');
      const neighbor = card.nextElementSibling || card.previousElementSibling;
      const category = section.closest('.board-category');
      const anchorId = neighbor?.dataset.linkId;
      const previousAnchoring = root.style.overflowAnchor;
      root.style.overflowAnchor = 'none';
      const top = (neighbor || category).getBoundingClientRect().top;
      for (const {lane, index, data} of pages) {
        lane.offset = data.items.length;
        lane.total = data.total;
        lane.items = new Map(data.items.map(item => [String(item.link.id), item]));
        root.querySelector(`[data-lane="${index}"]`).innerHTML = laneContent(data, lane.side === 'pending', index);
      }
      const anchor = anchorId ? section.querySelector(`[data-link-id="${anchorId}"]`) : category;
      if (anchor) window.scrollBy({top: anchor.getBoundingClientRect().top - top, left: 0, behavior: 'instant'});
      // Avoid a second adjustment from native scroll anchoring after this patch.
      requestAnimationFrame(() => { root.style.overflowAnchor = previousAnchoring; });
    }
    function board(data) {
      lanes = [];
      return data.batches.map(group => `<section class="board-batch">
        <header class="board-batch-header"><span class="eyebrow">${tr('批次', 'BATCH')}</span>
          <h2>${esc(label(group.batch))}</h2><p>${esc(group.batch.id)}</p>
          ${group.batch.legacy_incomplete ? `<p class="human-review-notice">${tr('旧版导入未完整保留所有批次记录，历史结果可能不完整。', 'Older imports did not retain every batch occurrence. Historical results may be incomplete.')}</p>` : ''}</header>
        ${group.products.map(product => `<section class="board-product">
          <header class="board-product-header"><span>${tr('商品', 'PRODUCT')}</span><h3>${esc(product.product_id)}</h3>
            <p>${esc(product.platform)} / ${esc(product.shop_id)}</p></header>
          ${product.categories.map(category => `<section class="board-category category-border--${category.category_id}">
            <header class="board-category-header">${badge(category.category_id)}<span>${category.issue_count} ${tr('个具体问题组', 'specific issue groups')}</span></header>
            ${lane(group.batch, product, category, 'accepted')}${lane(group.batch, product, category, 'pending')}
          </section>`).join('') || `<p class="panel board-empty">${tr('该商品当前没有符合条件的问题关联。', 'This product has no matching issue links.')}</p>`}
        </section>`).join('')}</section>`).join('');
    }
    async function load() {
      const call = ++generation;
      loading = true; controls(); root.setAttribute('aria-busy', 'true');
      $('#scope-count').textContent = tr('正在读取结果…', 'Loading results…');
      $('#scope-results').innerHTML = '';
      const params = new URLSearchParams({limit: String(pageSize), offset: String((page - 1) * pageSize)});
      for (const [key, value] of Object.entries(values)) if (key !== 'page' && value) params.set(key, value);
      try {
        const data = await ReviewAPI.request((issues ? '/issue-board?' : '/comments?') + params,
          undefined, issues ? {} : {page: true});
        if (!root.isConnected || call !== generation) return;
        total = issues ? data.total_products : data.total;
        if (page > 1 && (page - 1) * pageSize >= total) {
          navigate({...values, page: String(Math.max(1, Math.ceil(total / pageSize)))}); return;
        }
        $('#scope-count').textContent = tr('符合条件：', 'Matches: ') + total + (issues ? tr(' 个批次内商品', ' products within batches') : tr(' 条评论', ' reviews'));
        $('#scope-results').innerHTML = total ? (issues ? board(data) : data.items.map(commentCard).join('')) :
          `<section class="panel"><p>${tr('没有符合条件的结果。可以清除筛选或稍后刷新。', 'No matching results. Clear filters or refresh later.')}</p></section>`;
        $('#scope-page').textContent = `${tr('第', 'Page')} ${page} / ${Math.max(1, Math.ceil(total / pageSize))}` +
          (issues ? tr(' 页 · 按完整商品分页', ' · Whole-product pages') : '');
      } catch (_) {
        if (root.isConnected && call === generation) $('#scope-count').textContent = tr('结果加载失败，请刷新重试。', 'Could not load results. Refresh to try again.');
      } finally {
        if (root.isConnected && call === generation) { loading = false; controls(); root.setAttribute('aria-busy', 'false'); }
      }
    }
    root.addEventListener('click', async event => {
      const button = event.target.closest('button[data-more], button[data-accept]');
      if (!button || loading || acting) return;
      acting = true; controls();
      let confirmed = false;
      const section = button.closest('.board-lane'), index = Number(section.dataset.lane), state = lanes[index];
      button.disabled = true;
      const notice = section.querySelector('.board-lane-notice');
      try {
        if (button.hasAttribute('data-more')) {
          const params = new URLSearchParams({batch_id: state.batch.id, platform: state.product.platform, shop_id: state.product.shop_id,
            product_id: state.product.product_id,
            category_id: state.category, decision: state.side, limit: '20', offset: String(state.offset),
            status: values.status || 'all', q: values.q || ''});
          const data = await ReviewAPI.request('/issue-board/entries?' + params);
          if (!root.isConnected || !section.isConnected) return;
          const fresh = data.items.filter(item => !state.items.has(String(item.link.id)));
          for (const item of fresh) state.items.set(String(item.link.id), item);
          section.querySelector('.board-entries').insertAdjacentHTML('beforeend', fresh.map(item => entry(item, state.side === 'pending')).join(''));
          state.offset += data.items.length;
          if (state.offset >= data.total) button.remove();
        } else {
          const item = state.items.get(button.dataset.accept);
          root.setAttribute('aria-busy', 'true');
          await ReviewAPI.request(`/comment-issues/${item.link.id}/decisions`, {
            request_id: crypto.randomUUID(), expected_token: item.token, decision: 'accept',
            note: tr('核对原文证据后确认归组', 'Confirmed assignment after checking the original evidence')
          });
          confirmed = true;
          if (root.isConnected) await refreshCategory(state, section, button);
        }
      } catch (_) {
        if (notice.isConnected) notice.textContent = confirmed ?
          tr('归组已确认，但结果刷新失败，请刷新结果核对。', 'Assignment confirmed, but the results could not refresh. Refresh to check them.') :
          tr('操作未确认完成。请刷新并核对最新结果后重试。', 'The operation was not confirmed. Refresh and check the latest result before retrying.');
      } finally {
        acting = false; controls();
        if (button.isConnected) button.disabled = false;
        if (root.isConnected && !loading) root.setAttribute('aria-busy', 'false');
      }
    });
    $('#scope-prev').addEventListener('click', () => navigate({...values, page: String(page - 1)}));
    $('#scope-next').addEventListener('click', () => navigate({...values, page: String(page + 1)}));
    $('#scope-refresh').addEventListener('click', load);
    ScopeFilter.mount($('#scope-filter'), values, navigate).then(() => { if (root.isConnected) load(); }).catch(() => {
      if (root.isConnected) $('#scope-count').textContent = tr('筛选选项加载失败，请刷新或清除筛选。', 'Could not load filter options. Refresh or clear filters.');
    });
  }
  window.ScopedPages = {mount};
})();
