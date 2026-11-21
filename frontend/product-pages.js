(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const date = value => value ? new Date(value).toLocaleString() : '未提供';
  const analysis = {received: '已接收', queued: '等待分析', analyzing: '分析中', analyzed: '分析完成', failed: '分析失败'};
  const verdict = {yes: '发现问题', no: '未发现问题', unknown: '无法判断'};
  const status = {proposed: '待确认', confirmed: '已确认', resolved: '已处理', dismissed: '已驳回', merged: '已合并'};
  const category = {quality: '质量', logistics: '物流', mismatch: '描述不符', usability: '使用体验', other: '其他'};
  const linkStatus = {suggested: '待复核', accepted: '已接受', rejected: '已拒绝'};
  const issueStatus = issue => issue.merged_into_id ? '已合并' : (status[issue.status] || issue.status);
  const ai = comment => (comment.has_issue && comment.analysis_status !== 'analyzed' ? '上次 AI 判断：' : 'AI 判断：') +
    (verdict[comment.has_issue] || '暂无结果');
  const opts = (values, selected) => Object.entries(values).map(([value, title]) =>
    `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(title)}</option>`).join('');
  const link = (href, text, className = 'btn') => `<a class="${className}" href="${esc(href)}">${esc(text)}</a>`;
  const scope = item => `${esc(item.platform)} / ${esc(item.shop_id)} / ${esc(item.product_id)}`;
  const commentHref = id => ProductRoutes.href('comments', id);
  const issueHref = id => ProductRoutes.href('issues', id);

  function mountList(root, route) {
    const comments = route.route === 'comments', values = route.filters, page = Number(values.page);
    const name = comments ? '评论' : '问题组';
    let generation = 0, loading = false, total = 0;
    root.innerHTML = `<section class="panel live-product-head">
      <h2>${name}列表</h2><p>${comments ? '查看真实原文和分析状态，从详情进入证据复核或补充问题。' :
        '查看真实问题状态与当前证据。接受关联后，仍需独立确认问题组。'}</p>
      <form class="human-review-filters" id="product-filter">
        ${comments ? `<label>批次编号<input name="batch_id" value="${esc(values.batch_id)}" maxlength="36" placeholder="全部批次"></label>` : ''}
        <label>商品编号<input name="product_id" value="${esc(values.product_id)}" maxlength="128" placeholder="全部商品"></label>
        ${comments ? `<label>分析状态<select name="analysis_status">${opts({'': '全部状态', ...analysis}, values.analysis_status)}</select></label>
          <label>AI 判断<select name="has_issue">${opts({'': '全部判断', ...verdict}, values.has_issue)}</select></label>` :
        `<label>问题状态<select name="status">${opts({all: '全部状态', ...status}, values.status)}</select></label>
          <label>类别<select name="category_id">${opts({'': '全部类别', ...category}, values.category_id)}</select></label>`}
        <label>${comments ? '搜索原文' : '搜索标题'}<input name="q" value="${esc(values.q)}" maxlength="200" placeholder="输入关键词"></label>
        <button class="btn btn-primary">查询${name}</button><button class="btn" type="button" id="product-clear">清除筛选</button>
      </form></section>
      <div class="live-product-summary"><p id="product-count" role="status" aria-live="polite"></p>
        <button class="btn" id="product-reload">刷新列表</button></div>
      <div id="product-results" class="live-product-cards"></div>
      <div class="human-review-pagination"><button class="btn" id="product-prev" disabled>上一页</button>
        <span id="product-page"></span><button class="btn" id="product-next" disabled>下一页</button></div>`;
    const $ = selector => root.querySelector(selector);
    function navigate(next) {
      const hash = ProductRoutes.href(route.route, null, next);
      if (window.location.hash === hash) load();
      else window.location.hash = hash;
    }
    function controls() {
      $('#product-prev').disabled = loading || page <= 1;
      $('#product-next').disabled = loading || page * 20 >= total;
    }
    function commentCard(c) {
      return `<article class="panel live-product-card">
        <p class="live-product-scope">${scope(c)}</p>
        <div class="live-product-tags"><span>${esc(analysis[c.analysis_status] || c.analysis_status)}</span><span>${esc(ai(c))}</span></div>
        <blockquote class="human-review-body">${esc(c.body)}</blockquote>
        <p class="live-product-meta">评分：${c.rating == null ? '未提供' : esc(c.rating) + ' / 5'} · 评论时间：${esc(date(c.review_date))}</p>
        ${link(ProductRoutes.href('comments', c.id, values), '查看原文与关联')}
      </article>`;
    }
    function issueCard(item) {
      const issue = item.issue;
      return `<article class="panel live-product-card">
        <div class="live-product-tags"><span>${esc(issueStatus(issue))}</span><span>${esc(category[issue.category_id] || issue.category_id)}</span></div>
        <h3>${link(ProductRoutes.href('issues', issue.id, values), issue.title, 'live-product-title')}</h3>
        <p class="live-product-scope">${scope(issue)}</p>
        <p>当前有效已接受证据 <strong>${item.valid_accepted_count}</strong> 条</p>
        <p>未归档关联：已接受 ${issue.accepted_count} 条 · 待复核 ${issue.suggested_count} 条</p>
        ${item.invalid_accepted_count ? `<p class="human-review-notice">另有 ${item.invalid_accepted_count} 条历史或暂不可用的已接受关联，不能用于当前确认。</p>` : ''}
        <p class="live-product-meta">最近更新：${esc(date(issue.updated_at))}</p>
        ${link(ProductRoutes.href('issues', issue.id, values), '查看证据与跟进')}
      </article>`;
    }
    async function load() {
      const call = ++generation;
      loading = true; controls();
      $('#product-results').innerHTML = '';
      $('#product-count').textContent = `正在读取${name}…`;
      $('#product-page').textContent = '';
      const params = new URLSearchParams({limit: '20', offset: String((page - 1) * 20)});
      for (const [key, value] of Object.entries(values)) if (key !== 'page' && value) params.set(key, value);
      try {
        const data = comments ? await ReviewAPI.request('/comments?' + params, undefined, {page: true}) :
          await ReviewAPI.request('/review-issues?' + params);
        if (!root.isConnected || call !== generation) return;
        total = data.total;
        if (!data.items.length && page > 1) {
          navigate({...values, page: String(Math.max(1, Math.ceil(total / 20)))}); return;
        }
        $('#product-count').textContent = `符合条件：${total} ${comments ? '条评论' : '个问题组'}`;
        $('#product-results').innerHTML = data.items.length ? data.items.map(comments ? commentCard : issueCard).join('') :
          `<section class="panel live-product-empty"><h3>没有符合条件的${name}</h3><p>可以清除筛选或稍后刷新。这里显示的是数据库结果。</p></section>`;
        $('#product-page').textContent = `第 ${page} / ${Math.max(1, Math.ceil(total / 20))} 页`;
      } catch (_) {
        if (!root.isConnected || call !== generation) return;
        total = 0;
        $('#product-count').textContent = `${name}加载失败，请点击“刷新列表”重试。`;
      } finally {
        if (root.isConnected && call === generation) { loading = false; controls(); }
      }
    }
    $('#product-filter').addEventListener('submit', event => {
      event.preventDefault(); navigate({...Object.fromEntries(new FormData(event.currentTarget)), page: '1'});
    });
    $('#product-clear').addEventListener('click', () => navigate({}));
    $('#product-reload').addEventListener('click', load);
    $('#product-prev').addEventListener('click', () => { if (!loading) navigate({...values, page: String(page - 1)}); });
    $('#product-next').addEventListener('click', () => { if (!loading) navigate({...values, page: String(page + 1)}); });
    load();
  }

  function mountComment(root, route) {
    let generation = 0;
    const returnTo = ProductRoutes.href('comments', route.detailId, route.filters);
    root.innerHTML = `<div class="human-review-actions">${link(ProductRoutes.href('comments', null, route.filters), '← 返回评论列表')}
      <button class="btn" id="comment-product-reload">重新加载评论</button></div>
      <div id="comment-product-detail" aria-live="polite"></div>`;
    const area = root.querySelector('#comment-product-detail');
    async function load() {
      const call = ++generation;
      area.innerHTML = '<section class="panel"><p>正在读取评论原文…</p></section>';
      try {
        const data = await ReviewAPI.request('/review-comments/' + encodeURIComponent(route.detailId));
        if (!root.isConnected || call !== generation) return;
        const c = data.comment;
        area.innerHTML = `<section class="panel live-comment-detail"><h2>评论原文</h2>
          <p>${scope(c)}</p><div class="live-product-tags"><span>${esc(analysis[c.analysis_status] || c.analysis_status)}</span><span>${esc(ai(c))}</span></div>
          <blockquote class="human-review-body">${esc(c.body)}</blockquote>
          <p>评分：${c.rating == null ? '未提供' : esc(c.rating) + ' / 5'} · 评论时间：${esc(date(c.review_date))}</p>
          <p class="live-product-meta">来源评论编号：${esc(c.source_review_id)} · 最近更新：${esc(date(c.updated_at))}</p>
          ${c.analysis_status !== 'analyzed' && c.has_issue ? '<p class="human-review-notice">当前分析尚未完成，上次 AI 判断不能视为当前原文的分析结论。</p>' : ''}
          ${data.can_add && ReviewAPI.canReview ? link(ProductRoutes.reviewHref('manual', c.id, returnTo), '为这条评论补充问题', 'btn btn-primary') :
            `<p>${ReviewAPI.canReview ? '评论分析尚未就绪，稍后可进入人工补充。' : '当前账号只读，可查看关联与操作历史。'}</p>`}
          </section><section class="panel live-comment-links"><h2>问题关联与复核记录</h2>
          <p>AI 判断与人工决定分别保留；已接受关联仍需核对原文是否变化。</p>
          ${data.links.length ? data.links.map(item => {
            const l = item.link;
            return `<article class="human-review-history"><h3>${link(issueHref(item.issue.id), item.issue.title, 'live-product-title')}</h3>
              <p>${esc(linkStatus[l.status] || l.status)}${l.superseded_at ? '（已归档）' : ''} · 问题组：${esc(issueStatus(item.issue))}</p>
              <p>关联来源：${l.origin === 'human' ? '人工' : 'AI 建议'}${l.decided_by ? ' · 决定者：' + esc(l.decided_by) : ''}</p>
              <p>关联证据：${esc(l.evidence_text || '无')}</p>
              ${item.needs_recheck ? '<p class="human-review-notice">原文已变化，旧证据需要重新核对。</p>' : ''}
              ${!item.needs_recheck && !l.superseded_at && ['source_changed', 'analysis_changed', 'invalid_evidence', 'scope_mismatch'].includes(item.blocked_reason) ? '<p class="human-review-notice">这条关联暂不能作为当前依据，请进入复核查看原文或分析版本的变化。</p>' : ''}
              ${l.superseded_at ? '<p>这条关联已归档，保留供历史追溯。</p>' : ''}
              ${link(ProductRoutes.reviewHref('decisions', l.id, returnTo), ReviewAPI.canReview ? '查看证据并复核' : '查看证据与历史')}
            </article>`;
          }).join('') : '<p>暂无问题关联。没有 AI 建议不代表评论一定没有问题。</p>'}</section>`;
      } catch (error) {
        if (!root.isConnected || call !== generation) return;
        area.innerHTML = `<section class="panel"><h2>${error.status === 404 ? '未找到这条评论' : '评论加载失败'}</h2>
          <p>${error.status === 404 ? '请返回列表重新选择。' : '请点击“重新加载评论”重试。'}</p></section>`;
      }
    }
    root.querySelector('#comment-product-reload').addEventListener('click', load);
    load();
  }

  function mountIssue(root, route) {
    const returnTo = ProductRoutes.href('issues', route.detailId, route.filters);
    root.innerHTML = `<div class="human-review-actions">${link(ProductRoutes.href('issues', null, route.filters), '← 返回问题组列表')}</div>
      <div id="review-workspace"><div></div></div>`;
    const area = root.querySelector('#review-workspace');
    IssueWorkflow.mount(area.firstElementChild, {
      issueId: route.detailId, detailOnly: true,
      busy: value => area.setAttribute('aria-busy', String(value)),
      openReview: id => { window.location.hash = ProductRoutes.reviewHref('decisions', id, returnTo); },
      openComment: id => { window.location.hash = commentHref(id); },
      selected: id => { if (id !== route.detailId) window.location.hash = ProductRoutes.href('issues', id, route.filters); }
    });
  }
  window.ProductPages = {
    mount(root, route) {
      ReviewAuth.mount(root, area => {
        if (!route.detailId) mountList(area, route);
        else if (route.route === 'comments') mountComment(area, route);
        else mountIssue(area, route);
      });
    }
  };
})();
