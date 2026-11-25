(function () {
  'use strict';
  const esc = value => String(value).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  function mountWorkspace(root, options) {
    const returnTo = ProductRoutes.safeReturn(options.returnTo);
    const back = ProductRoutes.parse(returnTo);
    const backLabel = back ? `← 返回${back.route === 'comments' ? '评论' : '问题组'}${back.detailId ? '详情' : '列表'}` : '';
    root.innerHTML = `${back ? `<p><a class="btn" href="${esc(returnTo)}">${backLabel}</a></p>` : ''}
      <div class="human-review-actions" aria-label="复核方式">
        <button class="btn" id="review-decisions-tab">建议复核与历史</button>
        <button class="btn" id="review-manual-tab">人工补充问题</button>
        <button class="btn" id="review-issues-tab">问题确认与跟进</button>
      </div><div id="review-workspace"></div>`;
    const updateAddress = (mode, id) => {
      if (root.isConnected) window.history.replaceState(null, '', ProductRoutes.reviewHref(mode, id, returnTo));
    };
    const openComment = id => { window.location.hash = ProductRoutes.href('comments', id); };
    const show = (mode, id) => {
      const area = root.querySelector('#review-workspace');
      if (area.getAttribute('aria-busy') === 'true') return;
      area.innerHTML = '<div></div>';
      const view = area.firstElementChild;
      for (const name of ['decisions', 'manual', 'issues']) {
        root.querySelector(`#review-${name}-tab`).setAttribute('aria-pressed', String(mode === name));
      }
      updateAddress(mode, id);
      const hooks = {
        openReview: linkId => show('decisions', linkId), openComment,
        selected: selectedId => updateAddress(mode, selectedId),
        busy: value => area.setAttribute('aria-busy', String(value))
      };
      if (mode === 'manual') ManualReview.mount(view, {...hooks, commentId: id});
      else if (mode === 'issues') IssueWorkflow.mount(view, {...hooks, issueId: id});
      else ReviewDecisions.mount(view, {...hooks, linkId: id,
        addForComment: commentId => show('manual', commentId),
        openIssue: issueId => { window.location.hash = ProductRoutes.href('issues', issueId); }
      });
    };
    root.querySelector('#review-decisions-tab').addEventListener('click', () => show('decisions'));
    root.querySelector('#review-manual-tab').addEventListener('click', () => show('manual'));
    root.querySelector('#review-issues-tab').addEventListener('click', () => show('issues'));
    show(options.mode || 'decisions', options.recordId);
  }
  window.HumanReview = {
    mount(root, options = {}) {
      ReviewAuth.mount(root, area => mountWorkspace(area, ProductRoutes.parse(window.location.hash) || options));
    }
  };
})();
