(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const date = value => value ? new Date(value).toLocaleString(I18n.locale) : I18n.t('未提供');
  const analysis = {received: I18n.t('已接收'), queued: I18n.t('等待分析'), analyzing: I18n.t('分析中'), analyzed: I18n.t('分析完成'), failed: I18n.t('分析失败')};
  const verdict = {yes: I18n.t('发现问题'), no: I18n.t('未发现问题'), unknown: I18n.t('无法判断')};
  const status = {proposed: I18n.t('待确认'), confirmed: I18n.t('已确认'), resolved: I18n.t('已处理'), dismissed: I18n.t('已驳回'), merged: I18n.t('已合并')};
  const category = {quality: I18n.t('质量'), logistics: I18n.t('物流'), mismatch: I18n.t('描述不符'), usability: I18n.t('使用体验'), other: I18n.t('其他')};
  const linkStatus = {suggested: I18n.t('待复核'), accepted: I18n.t('已接受'), rejected: I18n.t('已拒绝')};
  const issueStatus = issue => issue.merged_into_id ? I18n.t('已合并') : (status[issue.status] || issue.status);
  const ai = comment => (comment.has_issue && comment.analysis_status !== 'analyzed' ? I18n.t('上次 AI 判断：') : I18n.t('AI 判断：')) +
    (verdict[comment.has_issue] || I18n.t('暂无结果'));
  const opts = (values, selected) => Object.entries(values).map(([value, title]) =>
    `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(title)}</option>`).join('');
  const link = (href, text, className = 'btn') => `<a class="${className}" href="${esc(href)}">${esc(text)}</a>`;
  const scope = item => `${esc(item.platform)} / ${esc(item.shop_id)} / ${esc(item.product_id)}`;
  const commentHref = id => ProductRoutes.href('comments', id);
  const issueHref = id => ProductRoutes.href('issues', id);

  function mountComment(root, route) {
    let generation = 0;
    const returnTo = ProductRoutes.href('comments', route.detailId, route.filters);
    root.innerHTML = I18n.html`<div class="human-review-actions">${link(ProductRoutes.href('comments', null, route.filters), I18n.t('← 返回评论列表'))}
      <button class="btn" id="comment-product-reload">重新加载评论</button></div>
      <div id="comment-product-detail" aria-live="polite"></div>`;
    const area = root.querySelector('#comment-product-detail');
    async function load() {
      const call = ++generation;
      area.innerHTML = I18n.t('<section class="panel"><p>正在读取评论原文…</p></section>');
      try {
        const [data, analysisDetail] = await Promise.all([
          ReviewAPI.request('/review-comments/' + encodeURIComponent(route.detailId)),
          ReviewAPI.request('/comments/' + encodeURIComponent(route.detailId))
        ]);
        if (!root.isConnected || call !== generation) return;
        const c = data.comment;
        const run = analysisDetail.latest_analysis_run;
        area.innerHTML = I18n.html`<section class="panel live-comment-detail"><h2>评论原文</h2>
          <p>${scope(c)}</p><div class="live-product-tags"><span>${esc(analysis[c.analysis_status] || c.analysis_status)}</span><span>${esc(ai(c))}</span></div>
          <blockquote class="human-review-body">${esc(c.body)}</blockquote>
          ${run ? I18n.html`<p>分析来源：${esc(({llm: I18n.t('大模型'), heuristic: I18n.t('关键词规则')})[run.source] || I18n.t('未记录'))} · 模型：${esc(run.model_version)} · 模型尝试：${esc(run.llm_attempts || 0)} 次</p>
            <p>回退原因：${esc(run.fallback_reason || I18n.t('无'))} · 耗时：${esc(run.latency_ms ?? '—')} ms</p>` : ''}
          <p>评分：${WorkbenchUI.rating(c.rating)} · 评论时间：${esc(date(c.review_date))}</p>
          <p class="live-product-meta">来源评论编号：${esc(c.source_review_id)} · 最近更新：${esc(date(c.updated_at))}</p>
          ${c.analysis_status !== 'analyzed' && c.has_issue ? I18n.t('<p class="human-review-notice">当前分析尚未完成，上次 AI 判断不能视为当前原文的分析结论。</p>') : ''}
          ${data.can_add && ReviewAPI.canReview ? link(ProductRoutes.reviewHref('manual', c.id, returnTo), I18n.t('为这条评论补充问题'), 'btn btn-primary') :
            `<p>${ReviewAPI.canReview ? I18n.t('评论分析尚未就绪，稍后可进入人工补充。') : I18n.t('当前账号只读，可查看关联与操作历史。')}</p>`}
          </section><section class="panel live-comment-links"><h2>问题关联与复核记录</h2>
          <p>AI 判断与人工决定分别保留；已接受关联仍需核对原文是否变化。</p>
          ${data.links.length ? data.links.map(item => {
            const l = item.link;
            return I18n.html`<article class="human-review-history"><h3>${link(issueHref(item.issue.id), item.issue.title, 'live-product-title')}</h3>
              <p>${esc(linkStatus[l.status] || l.status)}${l.superseded_at ? I18n.t('（已归档）') : ''} · 问题组：${esc(issueStatus(item.issue))}</p>
              <p>关联来源：${l.origin === 'human' ? I18n.t('人工') : I18n.t('AI 建议')}${l.decided_by ? I18n.t(' · 决定者：') + esc(l.decided_by) : ''}</p>
              <p>关联证据：${esc(l.evidence_text || I18n.t('无'))}</p>
              ${item.needs_recheck ? I18n.t('<p class="human-review-notice">原文已变化，旧证据需要重新核对。</p>') : ''}
              ${!item.needs_recheck && !l.superseded_at && ['source_changed', 'analysis_changed', 'invalid_evidence', 'scope_mismatch'].includes(item.blocked_reason) ? I18n.t('<p class="human-review-notice">这条关联暂不能作为当前依据，请进入复核查看原文或分析版本的变化。</p>') : ''}
              ${l.superseded_at ? I18n.t('<p>这条关联已归档，保留供历史追溯。</p>') : ''}
              ${link(ProductRoutes.reviewHref('decisions', l.id, returnTo), ReviewAPI.canReview ? I18n.t('查看证据并复核') : I18n.t('查看证据与历史'))}
            </article>`;
          }).join('') : I18n.t('<p>暂无问题关联。没有 AI 建议不代表评论一定没有问题。</p>')}</section>`;
      } catch (error) {
        if (!root.isConnected || call !== generation) return;
        area.innerHTML = `<section class="panel"><h2>${error.status === 404 ? I18n.t('未找到这条评论') : I18n.t('评论加载失败')}</h2>
          <p>${error.status === 404 ? I18n.t('请返回列表重新选择。') : I18n.t('请点击“重新加载评论”重试。')}</p></section>`;
      }
    }
    root.querySelector('#comment-product-reload').addEventListener('click', load);
    load();
  }

  function mountIssue(root, route) {
    const returnTo = ProductRoutes.href('issues', route.detailId, route.filters);
    root.innerHTML = `<div class="human-review-actions">${link(ProductRoutes.href('issues', null, route.filters), I18n.t('← 返回问题组列表'))}</div>
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
        if (!route.detailId) ScopedPages.mount(area, route);
        else if (route.route === 'comments') mountComment(area, route);
        else mountIssue(area, route);
      });
    }
  };
})();
