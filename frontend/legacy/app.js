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
    issueFilters: {
      status: 'all',
      category: 'all',
      product: 'all',
      query: ''
    },
    issueScroll: 0,
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

  var ISSUE_STATUS_ORDER = ['proposed', 'confirmed', 'resolved', 'dismissed'];

  function getIssueById(issueId) {
    return MOCK.issues.filter(function (issue) {
      return issue.id === issueId;
    })[0] || null;
  }

  function getIssueComments(issueId) {
    return MOCK.comments.filter(function (comment) {
      return comment.issueId === issueId;
    });
  }

  function getIssueReviews(issueId) {
    return state.reviews.filter(function (review) {
      return review.issueId === issueId;
    });
  }

  function uniqueValues(list) {
    var seen = {};
    return list.filter(function (value) {
      if (!value || seen[value]) {
        return false;
      }
      seen[value] = true;
      return true;
    });
  }

  function issueFiltersActive() {
    var filters = state.issueFilters;
    return filters.status !== 'all' || filters.category !== 'all' ||
      filters.product !== 'all' || !!filters.query;
  }

  function getFilteredIssues() {
    var filters = state.issueFilters;
    var query = filters.query;

    return MOCK.issues.filter(function (issue) {
      if (filters.status !== 'all' && issue.status !== filters.status) {
        return false;
      }
      if (filters.category !== 'all' && issue.category !== filters.category) {
        return false;
      }
      if (filters.product !== 'all' && issue.product !== filters.product) {
        return false;
      }
      if (!query) {
        return true;
      }
      var haystack = [
        issue.title,
        issue.category,
        issue.product,
        issue.description,
        issue.evidence,
        issue.recommendation
      ].join(' ').toLowerCase();
      return haystack.indexOf(query) !== -1;
    });
  }

  function issueStatusTone(status) {
    return {
      proposed: 'warning',
      confirmed: 'pending',
      resolved: 'success',
      dismissed: 'neutral'
    }[status] || 'neutral';
  }

  function issuePriorityTone(severity) {
    return {
      '高': 'high',
      '中': 'mid',
      '低': 'low'
    }[severity] || 'mid';
  }

  function highlightMatch(value, query) {
    var safe = escapeHtml(value);
    if (!query) {
      return safe;
    }
    var safeQuery = escapeHtml(query);
    var pattern = new RegExp(escapeRegExp(safeQuery), 'gi');
    return safe.replace(pattern, '<mark class="search-hit">$&</mark>');
  }

  function issueResultText() {
    var total = MOCK.issues.length;
    var matched = getFilteredIssues().length;
    return issueFiltersActive() ?
      '共 ' + total + ' 组 · 匹配 ' + matched :
      '共 ' + total + ' 组';
  }

  var SEARCH_ICON = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="11" cy="11" r="6.4" stroke="currentColor" stroke-width="1.8"/>' +
    '<path d="m16 16 4.2 4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

  function renderIssueToolbar() {
    var filters = state.issueFilters;
    var categories = uniqueValues(MOCK.issues.map(function (issue) { return issue.category; }));
    var products = uniqueValues(MOCK.issues.map(function (issue) { return issue.product; }));

    var tabs = [{
      value: 'all',
      label: '全部',
      count: MOCK.issues.length
    }].concat(ISSUE_STATUS_ORDER.map(function (status) {
      return {
        value: status,
        label: ISSUE_STATUS_META[status].label,
        count: MOCK.issues.filter(function (issue) { return issue.status === status; }).length
      };
    })).map(function (tab) {
      var active = filters.status === tab.value;
      return '<button class="status-tab' + (active ? ' is-active' : '') + '" type="button" ' +
        'aria-pressed="' + active + '" data-issue-status="' + escapeHtml(tab.value) + '">' +
        escapeHtml(tab.label) +
        '<span class="status-tab-count">' + tab.count + '</span>' +
        '</button>';
    }).join('');

    var categoryOptions = '<option value="all"' + (filters.category === 'all' ? ' selected' : '') +
      '>全部类别</option>' + categories.map(function (category) {
        return option(category, category, filters.category);
      }).join('');

    var productOptions = '<option value="all"' + (filters.product === 'all' ? ' selected' : '') +
      '>全部商品</option>' + products.map(function (product) {
        return option(product, product, filters.product);
      }).join('');

    return '' +
      '<section class="issues-toolbar" aria-label="问题组筛选与搜索">' +
        '<div class="issues-toolbar-top">' +
          '<label class="issue-search">' +
            '<span class="issue-search-icon">' + SEARCH_ICON + '</span>' +
            '<span class="sr-only">搜索问题组</span>' +
            '<input id="issue-search" type="search" placeholder="搜索标题、类别、原文证据…" ' +
              'value="' + escapeHtml(filters.query) + '" autocomplete="off" spellcheck="false">' +
          '</label>' +
          '<button class="btn btn-ghost btn-sm issue-filter-toggle" type="button" ' +
            'id="issue-filter-toggle" aria-expanded="false" aria-controls="issue-secondary-filters">' +
            '筛选</button>' +
          '<div class="issues-filters" id="issue-secondary-filters">' +
            '<label class="select-field">' +
              '<span>类别</span>' +
              '<select class="select" id="issue-category-filter" data-issue-filter="category">' +
                categoryOptions +
              '</select>' +
            '</label>' +
            '<label class="select-field">' +
              '<span>商品</span>' +
              '<select class="select" id="issue-product-filter" data-issue-filter="product">' +
                productOptions +
              '</select>' +
            '</label>' +
          '</div>' +
        '</div>' +
        '<div class="issues-toolbar-bottom">' +
          '<div class="status-tabs" role="group" aria-label="按状态筛选">' +
            '<span class="status-tabs-indicator" aria-hidden="true"></span>' + tabs +
          '</div>' +
          '<div class="issues-result">' +
            '<span id="issue-result-count" aria-live="polite">' + issueResultText() + '</span>' +
            '<button class="btn btn-ghost btn-sm" type="button" id="issue-filter-clear"' +
              (issueFiltersActive() ? '' : ' hidden') + '>清除筛选</button>' +
          '</div>' +
        '</div>' +
      '</section>';
  }

  function renderIssueCard(issue, index) {
    var meta = ISSUE_STATUS_META[issue.status] || ISSUE_STATUS_META.proposed;
    var comments = getIssueComments(issue.id);
    var query = state.issueFilters.query;
    var priorityTone = issuePriorityTone(issue.severity);

    return '' +
      '<a class="issue-card" data-status="' + escapeHtml(issue.status) + '" ' +
        'href="#/issues/' + encodeURIComponent(issue.id) + '" ' +
        'style="--i:' + Math.min(index, 8) + '" ' +
        'aria-label="查看问题组：' + escapeHtml(issue.title) + '">' +
        '<div class="issue-card-top">' +
          statusBadge(meta.label, issueStatusTone(issue.status), false) +
          '<span class="tag issue-category-chip">' + escapeHtml(issue.category) + '</span>' +
          '<span class="issue-priority issue-priority--' + priorityTone + '">' +
            escapeHtml(issue.severity) + '优先级</span>' +
        '</div>' +
        '<h3 class="issue-card-title">' + highlightMatch(issue.title, query) + '</h3>' +
        '<p class="issue-card-product">' + escapeHtml(issue.product) + '</p>' +
        '<p class="issue-card-desc">' + highlightMatch(issue.description, query) + '</p>' +
        '<blockquote class="issue-card-evidence">' +
          highlightMatch(issue.evidence, query) + '</blockquote>' +
        '<div class="issue-card-foot">' +
          '<div class="issue-card-counts">' +
            '<span class="issue-count"><strong>' + escapeHtml(issue.suggested) +
              '</strong><span>AI 建议</span></span>' +
            '<span class="issue-count"><strong>' + escapeHtml(issue.confirmed) +
              '</strong><span>人工确认</span></span>' +
            '<span class="issue-count"><strong>' + comments.length +
              '</strong><span>相关评论</span></span>' +
          '</div>' +
          '<span class="issue-card-cta">查看详情<span aria-hidden="true">→</span></span>' +
        '</div>' +
      '</a>';
  }

  function issueEmptyState() {
    return '<div class="empty-state issue-empty"><strong>没有符合条件的问题组</strong>' +
      '<span>试试换个关键词，或清除筛选条件。</span></div>';
  }

  function renderIssueGrid(filtered) {
    if (!filtered.length) {
      return '<div class="issue-grid is-empty" id="issues-grid">' + issueEmptyState() + '</div>';
    }
    return '<div class="issue-grid" id="issues-grid">' +
      filtered.map(renderIssueCard).join('') +
      '</div>';
  }

  function renderIssues() {
    var filtered = getFilteredIssues();
    return '' +
      '<div class="view issues-view">' +
        renderIssueToolbar() +
        renderIssueGrid(filtered) +
      '</div>';
  }

  function renderRelatedComment(comment, index) {
    var ratingTone = comment.rating <= 2 ? 'danger' : (comment.rating >= 4 ? 'success' : 'neutral');
    return '' +
      '<article class="related-comment" style="--i:' + Math.min(index, 6) + '">' +
        '<div class="related-comment-head">' +
          '<strong>' + escapeHtml(comment.id) + '</strong>' +
          '<span class="status-badge status-badge--' + ratingTone + ' related-comment-rating">评分 ' +
            escapeHtml(comment.rating) + '</span>' +
          '<span class="related-comment-source">' + escapeHtml(comment.platform) + ' / ' +
            escapeHtml(comment.shop) + '</span>' +
          '<time>' + escapeHtml(comment.date) + '</time>' +
        '</div>' +
        '<p class="related-comment-text">' + highlightEvidence(comment.content, comment.evidence) + '</p>' +
        '<div class="related-comment-foot">' +
          '<span class="tag tag--' + escapeHtml(comment.issueTone) + '">' + escapeHtml(comment.issueCategory) + '</span>' +
          hasIssueBadge(comment.hasIssue) +
        '</div>' +
      '</article>';
  }

  function renderIssueSuggestion(review) {
    var meta = REVIEW_STATUS_META[review.status] || REVIEW_STATUS_META.suggested;
    return '' +
      '<li class="issue-suggestion">' +
        '<div class="issue-suggestion-head">' +
          statusBadge(meta.label, meta.tone, false) +
          '<strong>' + escapeHtml(review.commentId) + '</strong>' +
          '<span>置信度 ' + Math.round((review.confidence || 0) * 100) + '%</span>' +
        '</div>' +
        '<span class="issue-suggestion-meta">证据片段见下方相关评论</span>' +
      '</li>';
  }

  function renderIssueDetail(issueId) {
    var issue = getIssueById(issueId);
    if (!issue) {
      return '' +
        '<div class="view issue-detail-view">' +
          '<a class="detail-back" href="#/issues"><span aria-hidden="true">←</span> 返回问题组</a>' +
          '<div class="empty-state issue-empty"><strong>未找到该问题组</strong>' +
            '<span>它可能已被合并，或链接已经失效。</span></div>' +
        '</div>';
    }

    var meta = ISSUE_STATUS_META[issue.status] || ISSUE_STATUS_META.proposed;
    var tone = issueStatusTone(issue.status);
    var comments = getIssueComments(issue.id);
    var reviews = getIssueReviews(issue.id);
    var canConfirm = issue.status === 'proposed';
    var canResolve = issue.status !== 'resolved' && issue.status !== 'dismissed';
    var canDismiss = issue.status !== 'dismissed' && issue.status !== 'resolved';
    var closeRow = issue.closeNote ? '<div class="issue-info-row"><span>关闭说明</span><p>' +
      escapeHtml(issue.closeNote) + '</p></div>' : '';

    var suggestionBlock = reviews.length ? '' +
      '<div class="issue-link-block">' +
        '<h3 class="issue-subhead">AI 建议关联</h3>' +
        '<ul class="issue-link-list">' + reviews.map(renderIssueSuggestion).join('') + '</ul>' +
      '</div>' : '';

    var commentBlock = comments.length ?
      comments.map(renderRelatedComment).join('') :
      '<div class="empty-state issue-empty"><strong>暂无关联评论</strong>' +
        '<span>这批数据里还没有评论归入该问题组。</span></div>';

    var timelineBlock = '' +
      '<div class="issue-link-block">' +
        '<h3 class="issue-subhead">处理记录</h3>' +
        '<ol class="issue-timeline">' +
          '<li>' +
            '<span class="issue-timeline-dot" aria-hidden="true"></span>' +
            '<div><strong>AI 提取问题并建议归组</strong>' +
              '<span>来自评论原文与证据片段</span></div>' +
          '</li>' +
          '<li>' +
            '<span class="issue-timeline-dot" aria-hidden="true"></span>' +
            '<div><strong>' + escapeHtml(meta.label) + '</strong>' +
              '<span>' + escapeHtml(meta.desc) + ' · ' + escapeHtml(issue.updated) + '</span></div>' +
          '</li>' +
        '</ol>' +
      '</div>';

    return '' +
      '<div class="view issue-detail-view" data-status="' + escapeHtml(issue.status) + '">' +
        '<section class="issue-hero" data-status="' + escapeHtml(issue.status) + '">' +
          '<div class="issue-hero-main">' +
            '<a class="detail-back" href="#/issues"><span aria-hidden="true">←</span> 返回问题组</a>' +
            '<div class="issue-hero-eyebrow">' +
              statusBadge(meta.label, tone, false) +
              '<span class="tag issue-category-chip">' + escapeHtml(issue.category) + '</span>' +
              '<span class="issue-priority issue-priority--' + issuePriorityTone(issue.severity) + '">' +
                escapeHtml(issue.severity) + '优先级</span>' +
            '</div>' +
            '<h2 class="issue-hero-title">' + escapeHtml(issue.title) + '</h2>' +
            '<p class="issue-hero-product">' + escapeHtml(issue.product) + '</p>' +
            '<p class="issue-hero-desc">' + escapeHtml(issue.description) + '</p>' +
            '<blockquote class="issue-hero-evidence">' + escapeHtml(issue.evidence) + '</blockquote>' +
            '<div class="issue-hero-meta">' +
              '<span>最近更新 ' + escapeHtml(issue.updated) + '</span>' +
              '<span>涉及批次 ' + escapeHtml(issue.batches) + '</span>' +
            '</div>' +
          '</div>' +
          '<aside class="issue-hero-side" aria-label="问题组计数与操作">' +
            '<div class="issue-hero-stats">' +
              '<div class="issue-stat"><strong>' + escapeHtml(issue.suggested) + '</strong><span>AI 建议</span></div>' +
              '<div class="issue-stat"><strong>' + escapeHtml(issue.confirmed) + '</strong><span>人工确认</span></div>' +
              '<div class="issue-stat"><strong>' + comments.length + '</strong><span>相关评论</span></div>' +
            '</div>' +
            '<div class="issue-hero-actions">' +
              '<button class="btn btn-primary" type="button" data-issue-action="confirm" ' +
                'data-issue-id="' + escapeHtml(issue.id) + '"' + (canConfirm ? '' : ' disabled') +
                '>确认问题组</button>' +
              '<button class="btn btn-ghost" type="button" data-issue-action="resolve" ' +
                'data-issue-id="' + escapeHtml(issue.id) + '"' + (canResolve ? '' : ' disabled') +
                '>记录跟进</button>' +
              '<button class="btn btn-ghost" type="button" data-issue-action="dismiss" ' +
                'data-issue-id="' + escapeHtml(issue.id) + '"' + (canDismiss ? '' : ' disabled') +
                '>驳回问题组</button>' +
            '</div>' +
          '</aside>' +
        '</section>' +

        '<div class="issue-detail-columns">' +
          '<section class="panel issue-info-panel" aria-labelledby="issue-info-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="issue-info-title">判断依据</h2>' +
                '<p>AI 建议、证据来源与当前处理状态。</p>' +
              '</div>' +
              statusBadge(meta.label, tone, false) +
            '</div>' +
            '<div class="issue-info-list">' +
              '<div class="issue-info-row"><span>建议跟进</span><p>' + escapeHtml(issue.recommendation) + '</p></div>' +
              '<div class="issue-info-row"><span>问题类别</span><p>' + escapeHtml(issue.category) + ' · ' +
                escapeHtml(issue.product) + '</p></div>' +
              '<div class="issue-info-row"><span>来源批次</span><p>' + escapeHtml(issue.batches) + '</p></div>' +
              '<div class="issue-info-row"><span>最近更新</span><p>' + escapeHtml(issue.updated) + '</p></div>' +
              closeRow +
            '</div>' +
            suggestionBlock +
            timelineBlock +
          '</section>' +

          '<section class="panel issue-comments-panel" aria-labelledby="issue-comments-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="issue-comments-title">相关评论</h2>' +
                '<p>归属于该问题组的评论原文与证据片段。</p>' +
              '</div>' +
              '<span class="count-chip">' + comments.length + ' 条</span>' +
            '</div>' +
            '<div class="related-comments">' + commentBlock + '</div>' +
          '</section>' +
        '</div>' +
      '</div>';
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

  var issueSearchTimer = null;

  function parseRoute() {
    var raw = (window.location.hash || '')
      .replace(/^#\/?/, '')
      .split('?')[0]
      .replace(/\/+$/, '');
    var parts = raw.split('/').filter(Boolean);
    if (!parts.length) {
      return null;
    }
    var route = parts[0];
    if (route === 'issues' && parts[1]) {
      return { route: 'issues', detailId: decodeURIComponent(parts[1]) };
    }
    return ROUTE_IDS.indexOf(route) !== -1 ? { route: route } : null;
  }

  function updateChrome(route, detailIssue) {
    var meta = ROUTE_META[route];

    if (route === 'issues' && detailIssue) {
      pageTitle.textContent = '问题组';
      pageKicker.textContent = 'ISSUE DETAIL';
      pageSubtitle.textContent = '查看问题组、相关评论与判断依据。';
      document.title = detailIssue.title + ' · ReviewLens 评论洞察';
    } else {
      pageTitle.textContent = meta.title;
      pageKicker.textContent = meta.kicker;
      pageSubtitle.textContent = meta.subtitle;
      document.title = meta.title + ' · ReviewLens 评论洞察';
    }

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

  function moveStatusIndicator() {
    var tabs = document.querySelector('.status-tabs');
    if (!tabs) {
      return;
    }
    var indicator = tabs.querySelector('.status-tabs-indicator');
    var active = tabs.querySelector('.status-tab.is-active');
    if (!indicator || !active) {
      return;
    }

    var apply = function (animate) {
      indicator.style.transition = animate ? '' : 'none';
      indicator.style.width = active.offsetWidth + 'px';
      indicator.style.transform = 'translateX(' + active.offsetLeft + 'px)';
      if (!animate) {
        void indicator.offsetWidth;
        indicator.style.transition = '';
      }
    };

    if (!tabs.dataset.ready) {
      apply(false);
      tabs.dataset.ready = 'true';
    } else {
      apply(true);
    }
  }

  function updateIssueTabs() {
    Array.prototype.forEach.call(appRoot.querySelectorAll('[data-issue-status]'), function (tab) {
      var active = tab.getAttribute('data-issue-status') === state.issueFilters.status;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-pressed', String(active));
    });
  }

  function updateIssueResult() {
    var count = document.getElementById('issue-result-count');
    var clear = document.getElementById('issue-filter-clear');
    if (count) {
      count.textContent = issueResultText();
    }
    if (clear) {
      clear.hidden = !issueFiltersActive();
    }
  }

  function refreshIssues() {
    var grid = document.getElementById('issues-grid');
    if (!grid) {
      return;
    }
    var filtered = getFilteredIssues();
    grid.classList.remove('is-refreshing');
    void grid.offsetWidth;
    grid.classList.add('is-refreshing');
    grid.innerHTML = filtered.length ?
      filtered.map(renderIssueCard).join('') :
      issueEmptyState();
    updateIssueTabs();
    updateIssueResult();
    window.requestAnimationFrame(moveStatusIndicator);
  }

  function setIssueFilter(key, value) {
    if (!Object.prototype.hasOwnProperty.call(state.issueFilters, key)) {
      return;
    }
    state.issueFilters[key] = value;
    refreshIssues();
  }

  function resetIssueFilters() {
    state.issueFilters = { status: 'all', category: 'all', product: 'all', query: '' };
    var search = document.getElementById('issue-search');
    if (search) {
      search.value = '';
    }
    var category = document.getElementById('issue-category-filter');
    if (category) {
      category.value = 'all';
    }
    var product = document.getElementById('issue-product-filter');
    if (product) {
      product.value = 'all';
    }
    refreshIssues();
    showToast('筛选已清除');
  }

  function scheduleIssueSearch(value) {
    var query = value.trim().toLowerCase();
    if (issueSearchTimer) {
      window.clearTimeout(issueSearchTimer);
    }
    issueSearchTimer = window.setTimeout(function () {
      state.issueFilters.query = query;
      refreshIssues();
    }, 140);
  }

  function handleIssueAction(button) {
    var issueId = button.getAttribute('data-issue-id');
    var action = button.getAttribute('data-issue-action');
    var issue = getIssueById(issueId);
    var next = {
      confirm: { status: 'confirmed', message: '已确认该问题组' },
      resolve: { status: 'resolved', message: '已记录跟进，标记为已处理' },
      dismiss: { status: 'dismissed', message: '已驳回该问题组' }
    }[action];
    if (!issue || !next) {
      return;
    }
    issue.status = next.status;
    renderRoute({ route: 'issues', detailId: issueId, preserveScroll: true });
    showToast(next.message);
  }

  function renderRoute(parsed) {
    var route = parsed.route;
    var detailIssue = route === 'issues' && parsed.detailId ? getIssueById(parsed.detailId) : null;
    var isIssueList = route === 'issues' && !parsed.detailId;
    var scrollY = parsed.preserveScroll ? window.scrollY : (isIssueList ? state.issueScroll : 0);

    updateChrome(route, detailIssue);
    if (route === 'issues' && parsed.detailId) {
      appRoot.innerHTML = renderIssueDetail(parsed.detailId);
    } else {
      appRoot.innerHTML = renderers[route]();
    }
    window.scrollTo(0, scrollY);
    if (isIssueList) {
      state.issueScroll = 0;
    }
    if (route === 'issues') {
      window.requestAnimationFrame(moveStatusIndicator);
    }
  }

  function handleRoute() {
    var parsed = parseRoute();
    if (!parsed) {
      // 未知 hash（包括空 hash）回退到默认批次页。
      normalizeUrlToDefault();
      parsed = { route: DEFAULT_ROUTE };
    }
    renderRoute(parsed);
  }

  function handleRootClick(event) {
    var issueLink = event.target.closest('.issue-card');
    if (issueLink) {
      // 记住列表滚动位置，返回时原地恢复。
      state.issueScroll = window.scrollY;
      return;
    }

    var filterToggle = event.target.closest('#issue-filter-toggle');
    if (filterToggle) {
      var toolbar = filterToggle.closest('.issues-toolbar');
      if (toolbar) {
        var isOpen = toolbar.classList.toggle('is-filters-open');
        filterToggle.setAttribute('aria-expanded', String(isOpen));
      }
      return;
    }

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

    var statusTab = event.target.closest('[data-issue-status]');
    if (statusTab) {
      setIssueFilter('status', statusTab.getAttribute('data-issue-status'));
      return;
    }

    var clearButton = event.target.closest('#issue-filter-clear');
    if (clearButton) {
      resetIssueFilters();
      return;
    }

    var actionButton = event.target.closest('[data-issue-action]');
    if (actionButton) {
      handleIssueAction(actionButton);
      return;
    }
  }

  function handleRootChange(event) {
    var select = event.target.closest('[data-comment-filter]');
    if (select) {
      var key = select.getAttribute('data-comment-filter');
      if (Object.prototype.hasOwnProperty.call(state.filters, key)) {
        state.filters[key] = select.value;
        refreshCommentList();
      }
      return;
    }

    var issueSelect = event.target.closest('[data-issue-filter]');
    if (issueSelect) {
      setIssueFilter(issueSelect.getAttribute('data-issue-filter'), issueSelect.value);
    }
  }

  function handleRootInput(event) {
    if (event.target && event.target.id === 'issue-search') {
      scheduleIssueSearch(event.target.value);
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
    appRoot.addEventListener('input', handleRootInput);
    appRoot.addEventListener('submit', handleRootSubmit);
    window.addEventListener('hashchange', handleRoute);
    window.addEventListener('resize', function () {
      if (document.querySelector('.status-tabs')) {
        moveStatusIndicator();
      }
    });

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
