/*
 * ReviewLens · 商品评论问题雷达
 * 纯静态 hash 路由 + 前端 mock 交互。
 *
 * 说明：
 * - 所有业务数据来自 mock-data.js，不发送任何网络请求。
 * - 人工复核的接受 / 拒绝 / 改判只修改内存状态，并追加本地审计记录。
 * - 路由使用 #/xxx，直接双击 index.html 或挂载在 /ui/ 子路径均可使用。
 */
(function () {
  'use strict';

  var DATA = window.REVIEW_MOCK || {};
  var MOCK = {
    products: Array.isArray(DATA.products) ? DATA.products : [],
    stats: Array.isArray(DATA.stats) ? DATA.stats : [],
    batches: Array.isArray(DATA.batches) ? DATA.batches : [],
    comments: Array.isArray(DATA.comments) ? DATA.comments : [],
    issues: Array.isArray(DATA.issues) ? DATA.issues : [],
    reviews: Array.isArray(DATA.reviews) ? DATA.reviews : [],
    auditLog: Array.isArray(DATA.auditLog) ? DATA.auditLog : []
  };

  var ROUTE_META = {
    batches: {
      hash: '#/batches',
      title: '批次上传',
      kicker: 'INGESTION',
      subtitle: '从 CSV 接入评论，校验后入库并建立分析任务。'
    },
    comments: {
      hash: '#/comments',
      title: '评论',
      kicker: 'COMMENTS',
      subtitle: '浏览已接收评论，并按商品、分析状态和 has_issue 快速筛选。'
    },
    issues: {
      hash: '#/issues',
      title: '问题组',
      kicker: 'ISSUE GROUPS',
      subtitle: '把语义相近的评论归到同一问题组，由人工确认后持续跟进。'
    },
    reviews: {
      hash: '#/reviews',
      title: '人工复核',
      kicker: 'HUMAN REVIEW',
      subtitle: '复核 AI 生成的 suggested 关联，留下可追溯的人工判断。'
    },
    about: {
      hash: '#/about',
      title: '关于',
      kicker: 'ABOUT',
      subtitle: '商品评论管理与重复问题发现系统 · 初步前端界面。'
    }
  };

  var ROUTE_IDS = Object.keys(ROUTE_META);
  var DEFAULT_ROUTE = 'batches';

  var ISSUE_STATUS_META = {
    proposed: {
      label: '待确认',
      desc: 'AI 新建，等待人工判断'
    },
    confirmed: {
      label: '已确认',
      desc: '人工确认，正在跟进'
    },
    resolved: {
      label: '已解决',
      desc: '已记录处理并关闭'
    },
    dismissed: {
      label: '已忽略',
      desc: '人工驳回或暂不跟进'
    }
  };

  var REVIEW_STATUS_META = {
    suggested: { label: '待复核', tone: 'pending' },
    accepted: { label: '已接受', tone: 'accepted' },
    rejected: { label: '已拒绝', tone: 'rejected' },
    changed: { label: '已改判', tone: 'changed' }
  };

  var ANALYSIS_STATUS_META = {
    analyzed: { label: '已分析', tone: 'success' },
    queued: { label: '排队中', tone: 'processing' },
    analyzing: { label: '分析中', tone: 'processing' },
    failed: { label: '分析失败', tone: 'danger' }
  };

  var HAS_ISSUE_META = {
    yes: { label: 'has_issue · 有', tone: 'warning' },
    no: { label: 'has_issue · 无', tone: 'success' },
    unknown: { label: 'has_issue · 待判断', tone: 'neutral' }
  };

  var ICONS = {
    inbox: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4.5 12.5 7 5.5h10l2.5 7v5A1.5 1.5 0 0 1 18 19H6a1.5 1.5 0 0 1-1.5-1.5v-5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M4.5 12.5H9l1 2h4l1-2h4.5" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>',
    spark: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" fill="currentColor"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 4.5 20 19H4L12 4.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 9.5v4.2M12 16.5v.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    upload: '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 15.5V4.5m0 0-3.7 3.7M12 4.5l3.7 3.7M5 14.5v4A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  var appRoot = document.getElementById('app');
  var pageTitle = document.getElementById('page-title');
  var pageKicker = document.getElementById('page-kicker');
  var pageSubtitle = document.getElementById('page-subtitle');
  var navLinks = Array.prototype.slice.call(document.querySelectorAll('.nav-link[data-route]'));
  var toast = document.getElementById('toast');
  var toastMessage = document.getElementById('toast-message');
  var toastTimer = null;

  var state = {
    filters: {
      product: 'all',
      status: 'all',
      hasIssue: 'all'
    },
    // 复核状态放在内存中，切换页面后仍会保留；刷新页面即重置。
    reviews: MOCK.reviews.map(function (item) {
      return Object.assign({}, item, { status: 'suggested' });
    }),
    auditLog: MOCK.auditLog.map(function (item) {
      return Object.assign({}, item);
    })
  };

  // ---------- 工具函数 ----------

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (character) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[character];
    });
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  // 将 mock 数据中的证据短语在原文内高亮，先转义再插入 <mark>。
  function highlightEvidence(text, evidenceList) {
    var output = escapeHtml(text);
    (evidenceList || []).forEach(function (evidence) {
      if (!evidence) {
        return;
      }
      var safeEvidence = escapeHtml(evidence);
      var pattern = new RegExp(escapeRegExp(safeEvidence), 'g');
      output = output.replace(pattern, '<mark class="evidence">' + safeEvidence + '</mark>');
    });
    return output;
  }

  function statusBadge(label, tone, dot) {
    return '<span class="status-badge status-badge--' + tone + '">' +
      (dot ? '<span class="status-dot" aria-hidden="true"></span>' : '') +
      escapeHtml(label) +
      '</span>';
  }

  function hasIssueBadge(value) {
    var meta = HAS_ISSUE_META[value] || HAS_ISSUE_META.unknown;
    return statusBadge(meta.label, meta.tone, false);
  }

  function option(value, label, selected) {
    return '<option value="' + escapeHtml(value) + '"' +
      (value === selected ? ' selected' : '') + '>' +
      escapeHtml(label) +
      '</option>';
  }

  function showToast(message) {
    if (!toast || !toastMessage) {
      return;
    }
    toastMessage.textContent = message;
    toast.hidden = false;
    // 重新触发入场动画，让连续操作也有明确反馈。
    toast.style.animation = 'none';
    void toast.offsetWidth;
    toast.style.animation = '';

    if (toastTimer) {
      window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(function () {
      toast.hidden = true;
    }, 2800);
  }

  function getRouteFromHash() {
    var raw = window.location.hash || '';
    var route = raw.replace(/^#\/?/, '').split('?')[0].replace(/\/+$/, '');
    return ROUTE_IDS.indexOf(route) !== -1 ? route : null;
  }

  function normalizeUrlToDefault() {
    var fallbackHash = ROUTE_META[DEFAULT_ROUTE].hash;
    try {
      window.history.replaceState(null, '', fallbackHash);
    } catch (error) {
      // 个别浏览器在 file:// 下限制 History API，退回直接修改 hash。
      window.location.hash = fallbackHash;
    }
  }

  function updateChrome(route) {
    var meta = ROUTE_META[route];

    pageTitle.textContent = meta.title;
    pageKicker.textContent = meta.kicker;
    pageSubtitle.textContent = meta.subtitle;
    document.title = meta.title + ' · ReviewLens 评论洞察';

    navLinks.forEach(function (link) {
      var isActive = link.getAttribute('data-route') === route;
      link.classList.toggle('is-active', isActive);
      if (isActive) {
        link.setAttribute('aria-current', 'page');
      } else {
        link.removeAttribute('aria-current');
      }
    });
  }

  // ---------- 视图：批次上传 ----------

  function renderStats() {
    return '<div class="stats-grid">' + MOCK.stats.map(function (stat) {
      var icon = ICONS[stat.icon] || ICONS.spark;
      return '' +
        '<article class="stat-card stat-card--' + escapeHtml(stat.tone || 'primary') + '">' +
          '<div class="stat-head">' +
            '<span class="stat-label">' + escapeHtml(stat.label) + '</span>' +
            '<span class="stat-icon">' + icon + '</span>' +
          '</div>' +
          '<div class="stat-value">' + escapeHtml(stat.value) + '</div>' +
          '<div class="stat-foot">' +
            '<span>' + escapeHtml(stat.note) + '</span>' +
            '<span class="stat-trend">' + escapeHtml(stat.trend) + '</span>' +
          '</div>' +
        '</article>';
    }).join('') + '</div>';
  }

  function renderBatches() {
    var rows = MOCK.batches.map(function (batch) {
      return '' +
        '<tr>' +
          '<td><span class="batch-id">' + escapeHtml(batch.id) + '</span></td>' +
          '<td><span class="file-name" title="' + escapeHtml(batch.file) + '">' + escapeHtml(batch.file) + '</span></td>' +
          '<td class="numeric">' + escapeHtml(batch.accepted) + '</td>' +
          '<td class="numeric">' + escapeHtml(batch.duplicates) + '</td>' +
          '<td class="numeric">' + escapeHtml(batch.invalid) + '</td>' +
          '<td>' + statusBadge(batch.status, batch.statusTone, true) + '</td>' +
          '<td><span class="batch-time">' + escapeHtml(batch.time) + '</span></td>' +
        '</tr>';
    }).join('');

    return '' +
      '<div class="view">' +
        renderStats() +

        '<div class="ingestion-grid">' +
          '<section class="panel upload-panel" aria-labelledby="upload-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="upload-title">上传评论批次</h2>' +
                '<p>选择 CSV → 校验 → 入库建 Job。本页仅模拟受理结果。</p>' +
              '</div>' +
              statusBadge('CSV', 'neutral', false) +
            '</div>' +
            '<form class="upload-form" id="upload-form" autocomplete="off">' +
              '<div class="upload-drop">' +
                '<span class="upload-icon" aria-hidden="true">' + ICONS.upload + '</span>' +
                '<p class="upload-title">选择批次文件</p>' +
                '<p class="upload-help">演示不会读取真实文件，输入文件名即可体验流程。</p>' +
                '<div class="upload-row">' +
                  '<label class="sr-only" for="file-name">CSV 文件名</label>' +
                  '<input class="input" id="file-name" name="file-name" type="text" placeholder="reviews_2026-10-24.csv" spellcheck="false">' +
                  '<button class="btn btn-primary" type="submit">上传并校验</button>' +
                '</div>' +
              '</div>' +
            '</form>' +
            '<p class="upload-feedback" id="upload-feedback" role="status" hidden></p>' +
            '<div class="upload-constraints">' +
              '<span>≤ 5,000 行</span>' +
              '<span>≤ 10 MB</span>' +
              '<span>正文 ≤ 2,000 字符</span>' +
              '<span>单平台 CSV</span>' +
            '</div>' +
          '</section>' +

          '<section class="panel flow-panel" aria-labelledby="flow-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="flow-title">处理流程</h2>' +
                '<p>接收即返回，分析在后台逐条完成。</p>' +
              '</div>' +
              '<span class="count-chip">3 步</span>' +
            '</div>' +
            '<ol class="flow-list">' +
              '<li class="flow-step">' +
                '<span class="flow-num">01</span>' +
                '<div>' +
                  '<h3>选择 CSV</h3>' +
                  '<p>从选定平台导出评论文本，保留来源编号、商品与日期等字段。</p>' +
                '</div>' +
              '</li>' +
              '<li class="flow-step">' +
                '<span class="flow-num">02</span>' +
                '<div>' +
                  '<h3>校验与去重</h3>' +
                  '<p>检查编码、必填列、行数上限；命中去重键的记录保留为疑似重复行。</p>' +
                '</div>' +
              '</li>' +
              '<li class="flow-step">' +
                '<span class="flow-num">03</span>' +
                '<div>' +
                  '<h3>入库建 Job</h3>' +
                  '<p>有效评论与 <code>extract_issues</code> 任务在同一事务中写入，等待 Worker 认领。</p>' +
                '</div>' +
              '</li>' +
            '</ol>' +
            '<div class="flow-note">校验失败不会覆盖旧批次；修正后可重传，生成新的批次 ID。</div>' +
          '</section>' +
        '</div>' +

        '<section class="panel table-panel" aria-labelledby="batches-title">' +
          '<div class="panel-head">' +
            '<div>' +
              '<h2 id="batches-title">最近批次</h2>' +
              '<p>接收量与行级校验结果来自 mock 数据。</p>' +
            '</div>' +
            '<a class="text-link" href="#/about">查看接口约定 <span aria-hidden="true">→</span></a>' +
          '</div>' +
          '<div class="table-wrap">' +
            '<table class="data-table">' +
              '<caption class="sr-only">评论批次列表，含接收、重复、无效行统计</caption>' +
              '<thead>' +
                '<tr>' +
                  '<th scope="col">批次 ID</th>' +
                  '<th scope="col">文件名</th>' +
                  '<th scope="col" class="numeric">接收</th>' +
                  '<th scope="col" class="numeric">重复</th>' +
                  '<th scope="col" class="numeric">无效行</th>' +
                  '<th scope="col">状态</th>' +
                  '<th scope="col">时间</th>' +
                '</tr>' +
              '</thead>' +
              '<tbody>' + rows + '</tbody>' +
            '</table>' +
          '</div>' +
          '<div class="table-foot">' +
            '<span>共 ' + MOCK.batches.length + ' 个批次 · 时间均为本地时间</span>' +
            '<span>最近同步 2026-10-24 14:32</span>' +
          '</div>' +
        '</section>' +
      '</div>';
  }

  // ---------- 视图：评论 ----------

  function getFilteredComments() {
    return MOCK.comments.filter(function (comment) {
      var matchesProduct = state.filters.product === 'all' || comment.productId === state.filters.product;
      var matchesStatus = state.filters.status === 'all' || comment.analysisStatus === state.filters.status;
      var matchesIssue = state.filters.hasIssue === 'all' || comment.hasIssue === state.filters.hasIssue;
      return matchesProduct && matchesStatus && matchesIssue;
    });
  }

  function commentCountText(count) {
    return '显示 ' + count + ' / ' + MOCK.comments.length + ' 条';
  }

  function renderCommentCard(comment) {
    var analysisMeta = ANALYSIS_STATUS_META[comment.analysisStatus] || {
      label: comment.analysisStatus || '未知',
      tone: 'neutral'
    };
    var issueMarkup = '';

    if (comment.hasIssue === 'yes' && comment.issueCategory) {
      issueMarkup =
        '<div class="comment-issue">' +
          '<span class="tag tag--' + escapeHtml(comment.issueTone || 'blue') + '">' + escapeHtml(comment.issueCategory) + '</span>' +
          '<span class="confidence">AI 置信度 ' + Math.round((comment.confidence || 0) * 100) + '%</span>' +
          '<span class="issue-spacer"></span>' +
          '<span class="evidence-hint">原文证据已高亮</span>' +
        '</div>';
    } else if (comment.analysisStatus === 'failed') {
      issueMarkup =
        '<div class="comment-issue">' +
          '<span class="issue-error">分析失败</span>' +
          '<span class="confidence">' + escapeHtml(comment.errorCode || 'UNKNOWN_ERROR') + '</span>' +
          '<span class="issue-spacer"></span>' +
          '<span>等待重试</span>' +
        '</div>';
    } else if (comment.analysisStatus === 'queued' || comment.analysisStatus === 'analyzing') {
      issueMarkup =
        '<div class="comment-issue">' +
          '<span class="issue-queued">排队中</span>' +
          '<span class="issue-spacer"></span>' +
          '<span>尚未产生问题判断</span>' +
        '</div>';
    } else if (comment.hasIssue === 'no') {
      issueMarkup =
        '<div class="comment-issue">' +
          '<span class="clear-issue">未发现重复问题</span>' +
          '<span class="issue-spacer"></span>' +
          '<span class="confidence">AI 置信度 ' + Math.round((comment.confidence || 0) * 100) + '%</span>' +
        '</div>';
    } else {
      issueMarkup =
        '<div class="comment-issue">' +
          '<span class="issue-queued">待判断</span>' +
          '<span class="issue-spacer"></span>' +
          '<span>分析结果待人工确认</span>' +
        '</div>';
    }

    return '' +
      '<article class="comment-card">' +
        '<div class="comment-top">' +
          '<div class="source-line">' +
            '<span class="platform-pill">' + escapeHtml(comment.platform) + '</span>' +
            '<span>' + escapeHtml(comment.shop) + '</span>' +
          '</div>' +
          '<div class="comment-flags">' +
            statusBadge(analysisMeta.label, analysisMeta.tone, comment.analysisStatus === 'processing') +
            hasIssueBadge(comment.hasIssue) +
          '</div>' +
        '</div>' +
        '<div class="comment-product">' +
          '<span>' + escapeHtml(comment.product) + '</span>' +
          '<span class="rating">★ ' + Number(comment.rating || 0).toFixed(1) + '</span>' +
        '</div>' +
        '<p class="comment-text">' + highlightEvidence(comment.content, comment.evidence) + '</p>' +
        '<div class="comment-meta">' +
          '<span>' + escapeHtml(comment.id) + '</span>' +
          '<span>' + escapeHtml(comment.date) + '</span>' +
        '</div>' +
        issueMarkup +
      '</article>';
  }

  function renderCommentList(filtered) {
    if (!filtered.length) {
      return '' +
        '<div class="empty-state">' +
          '<strong>没有符合条件的评论</strong>' +
          '<span>尝试放宽商品、分析状态或 has_issue 筛选。</span>' +
        '</div>';
    }
    return filtered.map(renderCommentCard).join('');
  }

  function renderComments() {
    var filtered = getFilteredComments();
    var productOptions = option('all', '全部商品', state.filters.product) +
      MOCK.products.map(function (product) {
        return option(product.id, product.name, state.filters.product);
      }).join('');

    var statusOptions = option('all', '全部状态', state.filters.status) +
      option('analyzed', '已分析', state.filters.status) +
      option('queued', '排队中', state.filters.status) +
      option('failed', '分析失败', state.filters.status);

    var issueOptions = option('all', '全部', state.filters.hasIssue) +
      option('yes', '有', state.filters.hasIssue) +
      option('no', '无', state.filters.hasIssue) +
      option('unknown', '无法判断', state.filters.hasIssue);

    return '' +
      '<div class="view">' +
        '<section class="panel filter-panel" aria-labelledby="filter-title">' +
          '<div class="panel-head">' +
            '<div>' +
              '<h2 id="filter-title">筛选评论</h2>' +
              '<p>筛选仅作用于当前页面的 mock 列表，不会请求后端。</p>' +
            '</div>' +
            '<span class="count-chip" id="comment-count" aria-live="polite">' + commentCountText(filtered.length) + '</span>' +
          '</div>' +
          '<div class="filter-grid">' +
            '<label class="filter-field">' +
              '<span>商品</span>' +
              '<select class="select" data-comment-filter="product" id="filter-product">' + productOptions + '</select>' +
            '</label>' +
            '<label class="filter-field">' +
              '<span>分析状态</span>' +
              '<select class="select" data-comment-filter="status" id="filter-status">' + statusOptions + '</select>' +
            '</label>' +
            '<label class="filter-field">' +
              '<span>has_issue</span>' +
              '<select class="select" data-comment-filter="hasIssue" id="filter-has-issue">' + issueOptions + '</select>' +
            '</label>' +
            '<div class="filter-actions">' +
              '<button class="btn btn-ghost" id="reset-comment-filters" type="button">重置筛选</button>' +
            '</div>' +
          '</div>' +
        '</section>' +

        '<div class="comment-grid" id="comments-list">' + renderCommentList(filtered) + '</div>' +
      '</div>';
  }

  function refreshCommentList() {
    var list = document.getElementById('comments-list');
    var count = document.getElementById('comment-count');
    if (!list) {
      return;
    }
    var filtered = getFilteredComments();
    list.innerHTML = renderCommentList(filtered);
    if (count) {
      count.textContent = commentCountText(filtered.length);
    }
  }

  // ---------- 视图：问题组 ----------

  function renderIssueCard(issue) {
    var detailId = 'issue-detail-' + issue.id;
    var closeNote = issue.closeNote ?
      '<div class="issue-close-note">' + escapeHtml(issue.closeNote) + '</div>' : '';

    return '' +
      '<article class="issue-card" data-issue-card="' + escapeHtml(issue.id) + '">' +
        '<button class="issue-toggle" type="button" data-issue-toggle aria-expanded="false" aria-controls="' + escapeHtml(detailId) + '">' +
          '<span class="issue-title">' + escapeHtml(issue.title) + '</span>' +
          '<span class="issue-chevron" aria-hidden="true">⌄</span>' +
        '</button>' +
        '<div class="issue-tag-row">' +
          '<span class="tag tag--' + escapeHtml(issue.categoryTone) + '">' + escapeHtml(issue.category) + '</span>' +
          '<span class="issue-product" title="' + escapeHtml(issue.product) + '">' + escapeHtml(issue.product) + '</span>' +
        '</div>' +
        '<div class="issue-counts">' +
          '<div class="issue-count"><strong>' + escapeHtml(issue.suggested) + '</strong><span>AI 建议</span></div>' +
          '<div class="issue-count"><strong>' + escapeHtml(issue.confirmed) + '</strong><span>人工确认</span></div>' +
        '</div>' +
        '<div class="issue-detail" id="' + escapeHtml(detailId) + '" hidden>' +
          '<p>' + escapeHtml(issue.description) + '</p>' +
          '<div class="issue-detail-block">' +
            '<span class="issue-detail-label">原文证据</span>' +
            '<blockquote class="issue-evidence">' + escapeHtml(issue.evidence) + '</blockquote>' +
          '</div>' +
          '<div class="issue-detail-block">' +
            '<span class="issue-detail-label">建议跟进</span>' +
            '<p>' + escapeHtml(issue.recommendation) + '</p>' +
          '</div>' +
          '<dl class="issue-detail-grid">' +
            '<div><dt>严重度</dt><dd>' + escapeHtml(issue.severity) + '</dd></div>' +
            '<div><dt>最近更新</dt><dd>' + escapeHtml(issue.updated) + '</dd></div>' +
            '<div><dt>涉及批次</dt><dd>' + escapeHtml(issue.batches) + '</dd></div>' +
            '<div><dt>状态</dt><dd>' + escapeHtml(issue.status) + '</dd></div>' +
          '</dl>' +
          closeNote +
        '</div>' +
        '<div class="issue-footer">' +
          '<time>' + escapeHtml(issue.updated) + '</time>' +
          '<span class="issue-toggle-label" data-toggle-label>查看详情</span>' +
        '</div>' +
      '</article>';
  }

  function renderIssues() {
    var proposed = MOCK.issues.filter(function (issue) { return issue.status === 'proposed'; }).length;
    var columns = Object.keys(ISSUE_STATUS_META).map(function (status) {
      var meta = ISSUE_STATUS_META[status];
      var items = MOCK.issues.filter(function (issue) { return issue.status === status; });
      var cards = items.length ?
        items.map(renderIssueCard).join('') :
        '<div class="empty-state"><strong>暂无问题组</strong><span>新一批分析结果会出现在这里。</span></div>';

      return '' +
        '<section class="kanban-column kanban-column--' + status + '" aria-label="' + escapeHtml(meta.label) + '问题组">' +
          '<header class="kanban-head">' +
            '<div class="kanban-title-line">' +
              '<span class="kanban-title">' + escapeHtml(meta.label) + ' <code>' + escapeHtml(status) + '</code></span>' +
              '<span class="kanban-count">' + items.length + '</span>' +
            '</div>' +
            '<p class="kanban-desc">' + escapeHtml(meta.desc) + '</p>' +
          '</header>' +
          '<div class="kanban-stack">' + cards + '</div>' +
        '</section>';
    }).join('');

    return '' +
      '<div class="view">' +
        '<div class="board-meta">' +
          '<span>共 ' + MOCK.issues.length + ' 个问题组 · <strong>' + proposed + '</strong> 个等待人工确认</span>' +
          '<span class="legend">' +
            '<span class="legend-item"><span class="legend-dot legend-dot--proposed"></span>待确认</span>' +
            '<span class="legend-item"><span class="legend-dot legend-dot--confirmed"></span>已确认</span>' +
            '<span class="legend-item"><span class="legend-dot legend-dot--resolved"></span>已解决</span>' +
            '<span class="legend-item"><span class="legend-dot legend-dot--dismissed"></span>已忽略</span>' +
          '</span>' +
        '</div>' +
        '<div class="kanban">' + columns + '</div>' +
      '</div>';
  }

  function toggleIssue(toggle) {
    var card = toggle.closest('.issue-card');
    if (!card) {
      return;
    }
    var detail = card.querySelector('.issue-detail');
    var label = card.querySelector('[data-toggle-label]');
    if (!detail) {
      return;
    }
    var isOpen = toggle.getAttribute('aria-expanded') === 'true';
    var nextOpen = !isOpen;

    toggle.setAttribute('aria-expanded', String(nextOpen));
    card.classList.toggle('is-open', nextOpen);
    detail.hidden = !nextOpen;
    if (label) {
      label.textContent = nextOpen ? '收起详情' : '查看详情';
    }
  }

  // ---------- 视图：人工复核 ----------

  function getReviewById(reviewId) {
    return state.reviews.filter(function (review) {
      return review.id === reviewId;
    })[0] || null;
  }

  function renderReviewCard(review) {
    var statusMeta = REVIEW_STATUS_META[review.status] || REVIEW_STATUS_META.suggested;
    var evidence = (review.evidence || []).map(function (item) {
      return '<span class="evidence-chip">“' + escapeHtml(item) + '”</span>';
    }).join('');

    return '' +
      '<article class="review-item" data-review-id="' + escapeHtml(review.id) + '" data-status="' + escapeHtml(review.status) + '">' +
        '<div class="review-top">' +
          '<div class="review-link">' +
            '<span class="review-eyebrow">建议关联</span>' +
            '<span class="review-arrow" aria-hidden="true">→</span>' +
            '<strong>' + escapeHtml(review.issueTitle) + '</strong>' +
          '</div>' +
          '<span class="status-badge status-badge--' + statusMeta.tone + '" data-review-status>' + statusMeta.label + '</span>' +
        '</div>' +
        '<div class="review-tag-row">' +
          '<span class="tag tag--' + escapeHtml(review.categoryTone) + '">' + escapeHtml(review.category) + '</span>' +
          '<span class="ai-origin">AI 生成 · ' + escapeHtml(review.suggestedAt) + '</span>' +
        '</div>' +
        '<blockquote class="review-quote">' + highlightEvidence(review.comment, review.evidence) + '</blockquote>' +
        '<div class="review-evidence">' +
          '<span class="review-evidence-label">证据片段</span>' + evidence +
        '</div>' +
        '<div class="review-meta">' +
          '<span class="meta-strong">' + escapeHtml(review.commentId) + '</span>' +
          '<span>' + escapeHtml(review.product) + '</span>' +
          '<span>' + escapeHtml(review.platform) + ' / ' + escapeHtml(review.shop) + '</span>' +
          '<span>置信度 ' + Math.round((review.confidence || 0) * 100) + '%</span>' +
        '</div>' +
        '<div class="review-actions">' +
          '<button class="btn btn-sm btn-accept' + (review.status === 'accepted' ? ' is-selected' : '') + '" type="button" data-review-action="accepted" data-review-id="' + escapeHtml(review.id) + '">接受</button>' +
          '<button class="btn btn-sm btn-reject' + (review.status === 'rejected' ? ' is-selected' : '') + '" type="button" data-review-action="rejected" data-review-id="' + escapeHtml(review.id) + '">拒绝</button>' +
          '<button class="btn btn-sm btn-change' + (review.status === 'changed' ? ' is-selected' : '') + '" type="button" data-review-action="changed" data-review-id="' + escapeHtml(review.id) + '">改判</button>' +
          '<span class="review-hint">决策仅写入本地 mock 审计</span>' +
        '</div>' +
      '</article>';
  }

  function renderAuditLog() {
    return state.auditLog.map(function (entry) {
      return '' +
        '<li class="audit-item">' +
          '<span class="audit-dot audit-dot--' + escapeHtml(entry.tone || 'system') + '" aria-hidden="true"></span>' +
          '<div class="audit-body">' +
            '<p class="audit-line"><strong>' + escapeHtml(entry.actor) + '</strong> ' + escapeHtml(entry.action) + '</p>' +
            '<p class="audit-target">' + escapeHtml(entry.target) + '</p>' +
            '<time class="audit-time">' + escapeHtml(entry.time) + '</time>' +
          '</div>' +
        '</li>';
    }).join('');
  }

  function pendingReviewCount() {
    return state.reviews.filter(function (review) {
      return review.status === 'suggested';
    }).length;
  }

  function renderReviews() {
    var queue = state.reviews.length ?
      state.reviews.map(renderReviewCard).join('') :
      '<div class="empty-state"><strong>暂无待复核关联</strong><span>AI 产生新的 suggested 关联后会出现在这里。</span></div>';

    return '' +
      '<div class="view">' +
        '<div class="review-layout">' +
          '<section class="panel review-panel" aria-labelledby="review-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="review-title" class="heading-with-count">待复核队列 ' +
                  '<span class="count-chip" id="review-pending-count" aria-live="polite">' + pendingReviewCount() + ' 条待复核</span>' +
                '</h2>' +
                '<p>这些是 AI 生成的 suggested 关联。接受、拒绝或改判后，可在右侧审计记录中看到本地动作。</p>' +
              '</div>' +
              '<span class="count-chip">AI 建议 · suggested</span>' +
            '</div>' +
            '<div class="review-list" id="review-queue">' + queue + '</div>' +
          '</section>' +

          '<aside class="panel audit-panel" aria-labelledby="audit-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="audit-title">审计记录</h2>' +
                '<p>接受 / 拒绝 / 改判的本地追踪。</p>' +
              '</div>' +
              '<span class="live-chip">LOCAL</span>' +
            '</div>' +
            '<ol class="audit-list" id="audit-log">' + renderAuditLog() + '</ol>' +
            '<p class="audit-note">演示模式：动作仅更新当前页面状态，刷新页面后恢复初始 mock。接入后应对应 append-only 的 issue_actions。</p>' +
          '</aside>' +
        '</div>' +
      '</div>';
  }

  function refreshReviewView() {
    var queue = document.getElementById('review-queue');
    var auditLog = document.getElementById('audit-log');
    var count = document.getElementById('review-pending-count');

    if (queue) {
      queue.innerHTML = state.reviews.length ?
        state.reviews.map(renderReviewCard).join('') :
        '<div class="empty-state"><strong>暂无待复核关联</strong><span>AI 产生新的 suggested 关联后会出现在这里。</span></div>';
    }
    if (auditLog) {
      auditLog.innerHTML = renderAuditLog();
    }
    if (count) {
      count.textContent = pendingReviewCount() + ' 条待复核';
    }
  }

  function handleReviewAction(button) {
    var reviewId = button.getAttribute('data-review-id');
    var nextStatus = button.getAttribute('data-review-action');
    var review = getReviewById(reviewId);
    if (!review || !REVIEW_STATUS_META[nextStatus]) {
      return;
    }

    var actionLabel = {
      accepted: '接受关联',
      rejected: '拒绝关联',
      changed: '改判关联'
    }[nextStatus];
    var toastLabel = {
      accepted: '已接受该关联（mock）',
      rejected: '已拒绝该关联（mock）',
      changed: '已改判该关联（mock）'
    }[nextStatus];

    review.status = nextStatus;
    review.decidedAt = '刚刚';

    // mock 审计：新动作置顶，视觉上模拟 append-only 审计时间线。
    state.auditLog.unshift({
      time: '刚刚',
      actor: '当前用户',
      action: actionLabel,
      target: review.commentId + ' → ' + review.issueTitle,
      tone: 'human'
    });

    refreshReviewView();
    showToast(toastLabel);
  }

  // ---------- 视图：关于 ----------

  function renderAbout() {
    var endpoints = [
      { method: 'POST', path: '/review-batches', desc: '创建评论批次，返回 202 与 batch_id' },
      { method: 'GET', path: '/review-batches/{id}', desc: '批次进度、行级计数与分析覆盖率' },
      { method: 'GET', path: '/comments', desc: '评论列表，支持商品 / 状态 / has_issue 筛选' },
      { method: 'GET', path: '/issues', desc: '问题组列表，按状态与类别组织' },
      { method: 'GET', path: '/jobs/{id}', desc: '单条分析任务的状态与错误码' },
      { method: 'GET', path: '/docs', desc: 'Swagger / OpenAPI 交互文档' }
    ];

    var team = [
      { initials: 'FW', name: 'FEI Wenxiang' },
      { initials: 'XK', name: 'XIANG Ke' },
      { initials: 'XC', name: 'XU Chao' },
      { initials: 'ZM', name: 'ZHANG Mingyang' }
    ];

    var endpointRows = endpoints.map(function (endpoint) {
      return '' +
        '<div class="endpoint-row">' +
          '<span class="method method--' + endpoint.method.toLowerCase() + '">' + endpoint.method + '</span> ' +
          '<code class="endpoint-path">' + escapeHtml(endpoint.path) + '</code>' +
          '<span class="endpoint-desc">' + escapeHtml(endpoint.desc) + '</span>' +
        '</div>';
    }).join('');

    var members = team.map(function (member) {
      return '' +
        '<div class="member">' +
          '<span class="avatar" aria-hidden="true">' + member.initials + '</span>' +
          '<strong>' + escapeHtml(member.name) + '</strong>' +
        '</div>';
    }).join('');

    return '' +
      '<div class="view">' +
        '<section class="about-hero">' +
          '<div class="about-hero-copy">' +
            '<p class="eyebrow">ABOUT REVIEWLENS</p>' +
            '<h2>把零散评论，整理成可复核的问题线索。</h2>' +
            '<p>系统面向选定平台的电商商家：集中接收商品评论，由 AI 提取具体问题并归组，再由人工确认、驳回和跟进。AI 只提供线索，不判定产品缺陷、责任或根因。</p>' +
            '<div class="about-tags">' +
              '<span>单平台首版</span>' +
              '<span>AI 线索 + 人工判断</span>' +
              '<span>证据可追溯</span>' +
              '<span>不做自动处置</span>' +
            '</div>' +
          '</div>' +
          '<div class="about-stamp" aria-hidden="true">' +
            '<span class="about-stamp-label">BUILD</span>' +
            '<strong>W11</strong>' +
            '<span>前端初版 / Mock</span>' +
          '</div>' +
        '</section>' +

        '<div class="about-grid">' +
          '<section class="panel" aria-labelledby="stack-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="stack-title">技术栈</h2>' +
                '<p>首版以清晰边界和可追溯性优先。</p>' +
              '</div>' +
              '<span class="count-chip">STATIC DEMO</span>' +
            '</div>' +
            '<div class="stack-list">' +
              '<div class="stack-item"><span class="stack-key">前端</span><span class="stack-value">原生 HTML / CSS / JavaScript，无构建步骤、无框架、无外部 CDN。</span></div>' +
              '<div class="stack-item"><span class="stack-key">API</span><span class="stack-value">FastAPI（Python），批次接收返回 <code>202</code>，查询接口返回 JSON。</span></div>' +
              '<div class="stack-item"><span class="stack-key">数据</span><span class="stack-value">PostgreSQL；评论事实、AI 推断与人工审计分表存储。</span></div>' +
              '<div class="stack-item"><span class="stack-key">异步处理</span><span class="stack-value">Worker 认领分析 <code>Job</code>，调用内部 AI Service 逐条提取问题。</span></div>' +
              '<div class="stack-item"><span class="stack-key">本演示</span><span class="stack-value">全部数据为前端 mock，不发送网络请求，仅用于确认页面结构与跳转。</span></div>' +
            '</div>' +
          '</section>' +

          '<section class="panel" aria-labelledby="api-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="api-title">API 端点一览</h2>' +
                '<p>与系统架构文档中的对外接口保持一致。</p>' +
              '</div>' +
              '<span class="count-chip">6 ENDPOINTS</span>' +
            '</div>' +
            '<div class="endpoint-list">' + endpointRows + '</div>' +
          '</section>' +
        '</div>' +

        '<div class="about-grid">' +
          '<section class="panel" aria-labelledby="docs-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="docs-title">项目文档</h2>' +
                '<p>了解完整流程、状态机与数据模型。</p>' +
              '</div>' +
            '</div>' +
            '<div class="doc-list">' +
              '<a class="doc-link" href="../docs/architecture.md" target="_blank" rel="noopener">' +
                '<span class="doc-badge">MD</span>' +
                '<span class="doc-copy"><strong>系统架构文档</strong><code>../docs/architecture.md</code></span>' +
                '<span class="doc-arrow" aria-hidden="true">↗</span>' +
              '</a>' +
              '<a class="doc-link" href="../README.md" target="_blank" rel="noopener">' +
                '<span class="doc-badge">MD</span>' +
                '<span class="doc-copy"><strong>项目 README</strong><code>../README.md</code></span>' +
                '<span class="doc-arrow" aria-hidden="true">↗</span>' +
              '</a>' +
            '</div>' +
          '</section>' +

          '<section class="panel" aria-labelledby="team-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="team-title">队伍成员</h2>' +
                '<p>MAIE6000c · 商品评论管理与重复问题发现系统</p>' +
              '</div>' +
              '<span class="count-chip">4 MEMBERS</span>' +
            '</div>' +
            '<div class="team-grid">' + members + '</div>' +
          '</section>' +
        '</div>' +

        '<p class="about-disclaimer">本页面为初步前端界面，所有统计、评论、问题组与复核记录均为 mock；文档链接与 API 列表仅作演示说明。</p>' +
      '</div>';
  }

  // ---------- 路由与事件 ----------

  var renderers = {
    batches: renderBatches,
    comments: renderComments,
    issues: renderIssues,
    reviews: renderReviews,
    about: renderAbout
  };

  function renderRoute(route) {
    updateChrome(route);
    appRoot.innerHTML = renderers[route]();
    window.scrollTo(0, 0);
  }

  function handleRoute() {
    var route = getRouteFromHash();

    if (!route) {
      // 未知 hash（包括空 hash）回退到默认批次页。
      normalizeUrlToDefault();
      route = DEFAULT_ROUTE;
    }

    renderRoute(route);
  }

  function handleRootClick(event) {
    var resetButton = event.target.closest('#reset-comment-filters');
    if (resetButton) {
      state.filters = { product: 'all', status: 'all', hasIssue: 'all' };
      Array.prototype.forEach.call(appRoot.querySelectorAll('[data-comment-filter]'), function (select) {
        select.value = 'all';
      });
      refreshCommentList();
      showToast('筛选已重置（mock）');
      return;
    }

    var reviewButton = event.target.closest('[data-review-action]');
    if (reviewButton) {
      handleReviewAction(reviewButton);
      return;
    }

    var issueToggle = event.target.closest('[data-issue-toggle]');
    if (issueToggle) {
      toggleIssue(issueToggle);
      return;
    }

    // 点击问题卡片其它空白区域也可展开；详情区域内的点击不折叠。
    var issueCard = event.target.closest('.issue-card');
    if (issueCard && !event.target.closest('.issue-detail')) {
      var cardToggle = issueCard.querySelector('[data-issue-toggle]');
      if (cardToggle) {
        toggleIssue(cardToggle);
      }
    }
  }

  function handleRootChange(event) {
    var select = event.target.closest('[data-comment-filter]');
    if (!select) {
      return;
    }
    var key = select.getAttribute('data-comment-filter');
    if (Object.prototype.hasOwnProperty.call(state.filters, key)) {
      state.filters[key] = select.value;
      refreshCommentList();
    }
  }

  function handleRootSubmit(event) {
    var form = event.target.closest('#upload-form');
    if (!form) {
      return;
    }
    event.preventDefault();

    var input = document.getElementById('file-name');
    var fileName = input ? input.value.trim() : '';
    if (!fileName) {
      fileName = 'reviews_2026-10-24.csv';
      if (input) {
        input.value = fileName;
      }
    }

    var feedback = document.getElementById('upload-feedback');
    if (feedback) {
      feedback.innerHTML = '已受理（mock）· <strong>' + escapeHtml(fileName) +
        '</strong> 将进入“校验 → 入库建 Job”流程，本次未上传真实文件。';
      feedback.hidden = false;
    }

    showToast('已受理（mock）');
  }

  function init() {
    if (!appRoot) {
      return;
    }

    appRoot.addEventListener('click', handleRootClick);
    appRoot.addEventListener('change', handleRootChange);
    appRoot.addEventListener('submit', handleRootSubmit);
    window.addEventListener('hashchange', handleRoute);

    navLinks.forEach(function (link) {
      link.addEventListener('click', function () {
        // 点击当前路由时没有 hashchange，手动回到顶部即可。
        if (link.classList.contains('is-active')) {
          window.scrollTo(0, 0);
        }
      });
    });

    handleRoute();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
