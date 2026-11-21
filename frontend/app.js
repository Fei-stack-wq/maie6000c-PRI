/* ReviewLens · 同源 API 驱动的批次、评论、问题组与人工复核工作台。 */
(function () {
  'use strict';

  var ROUTE_META = {
    batches: {
      hash: '#/batches',
      title: '批次上传',
      kicker: 'INGESTION',
      subtitle: '真实上传 · 校验 CSV、查看分析进度并进入复核。'
    },
    comments: {
      hash: '#/comments',
      title: '评论',
      kicker: 'COMMENTS',
      subtitle: '真实数据 · 查看原文和分析结果，进入证据复核。'
    },
    issues: {
      hash: '#/issues',
      title: '问题组',
      kicker: 'ISSUE GROUPS',
      subtitle: '真实数据 · 核对当前证据，确认问题并记录跟进。'
    },
    reviews: {
      hash: '#/reviews',
      title: '人工复核',
      kicker: 'HUMAN REVIEW',
      subtitle: '真实数据 · 核对原文，保存接受／拒绝决定及操作历史。'
    },
    about: {
      hash: '#/about',
      title: '关于',
      kicker: 'ABOUT',
      subtitle: '商品评论管理与重复问题发现系统 · 初步前端界面。'
    }
  };

  var DEFAULT_ROUTE = 'batches';

  var appRoot = document.getElementById('app');
  var pageTitle = document.getElementById('page-title');
  var pageKicker = document.getElementById('page-kicker');
  var pageSubtitle = document.getElementById('page-subtitle');
  var navLinks = Array.prototype.slice.call(document.querySelectorAll('.nav-link[data-route]'));
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

  function renderAbout() {
    var endpoints = [
      { method: 'POST', path: '/review-batches', desc: '创建评论批次，返回 202 与 batch_id' },
      { method: 'GET', path: '/review-batches/{id}', desc: '批次进度、行级计数与分析覆盖率' },
      { method: 'GET', path: '/comments', desc: '评论列表，支持商品 / 状态 / has_issue 筛选' },
      { method: 'GET', path: '/review-issues', desc: '问题组列表、有效证据与人工状态' },
      { method: 'GET', path: '/review-batches', desc: '真实批次列表、平台筛选与分页' },
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
            '<span>真实 API 联调</span>' +
          '</div>' +
        '</section>' +

        '<div class="about-grid">' +
          '<section class="panel" aria-labelledby="stack-title">' +
            '<div class="panel-head">' +
              '<div>' +
                '<h2 id="stack-title">技术栈</h2>' +
                '<p>首版以清晰边界和可追溯性优先。</p>' +
              '</div>' +
              '<span class="count-chip">LIVE API</span>' +
            '</div>' +
            '<div class="stack-list">' +
              '<div class="stack-item"><span class="stack-key">前端</span><span class="stack-value">原生 HTML / CSS / JavaScript，无构建步骤、无框架、无外部 CDN。</span></div>' +
              '<div class="stack-item"><span class="stack-key">API</span><span class="stack-value">FastAPI（Python），批次接收返回 <code>202</code>，查询接口返回 JSON。</span></div>' +
              '<div class="stack-item"><span class="stack-key">数据</span><span class="stack-value">PostgreSQL；评论事实、AI 推断与人工审计分表存储。</span></div>' +
              '<div class="stack-item"><span class="stack-key">异步处理</span><span class="stack-value">Worker 认领分析 <code>Job</code>，调用内部 AI Service 逐条提取问题。</span></div>' +
              '<div class="stack-item"><span class="stack-key">当前页面</span><span class="stack-value">批次上传、评论、问题组与人工复核均接真实 API，使用同一套登录权限。</span></div>' +
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
            '<div class="doc-list">' + [
              ['architecture', '系统架构文档', '组件、数据流与状态边界'],
              ['human-review', '人工复核与验收', '账号权限、复核流程和验收步骤'],
              ['operations', '启动与运行说明', '环境准备、日志和测试命令'],
              ['readme', '项目 README', '项目概览与使用入口']
            ].map(function (doc) {
              return '<a class="doc-link" href="/project-docs/' + doc[0] + '" target="_blank" rel="noopener">' +
                '<span class="doc-badge">MD</span><span class="doc-copy"><strong>' + doc[1] +
                '</strong><span>' + doc[2] + '</span></span><span class="doc-arrow" aria-hidden="true">↗</span></a>';
            }).join('') + '</div>' +
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

        '<p class="about-disclaimer">批次上传、评论、问题组与人工复核使用真实数据库。AI 判断与人工决定分别保留。</p>' +
      '</div>';
  }

  // ---------- 路由与事件 ----------

  function renderRoute(parsed) {
    ReviewAuth.unmount();
    updateChrome(parsed.route);
    if (['batches', 'comments', 'issues', 'reviews'].includes(parsed.route)) {
      appRoot.innerHTML = '<div id="live-product-root"></div>';
      var root = document.getElementById('live-product-root');
      if (parsed.route === 'reviews') HumanReview.mount(root, parsed);
      else if (parsed.route === 'batches') BatchPages.mount(root, parsed);
      else ProductPages.mount(root, parsed);
    } else {
      appRoot.innerHTML = renderAbout();
    }
    window.scrollTo(0, 0);
  }

  function handleRoute() {
    if (!window.location.hash || window.location.hash === '#/') normalizeUrlToDefault();
    var parsed = ProductRoutes.parse(window.location.hash);
    if (!parsed) {
      ReviewAuth.unmount();
      appRoot.innerHTML = '<section class="panel"><h2>链接格式无效</h2><p>请从主导航重新选择页面。</p></section>';
      return;
    }
    renderRoute(parsed);
  }

  function init() {
    if (!appRoot) {
      return;
    }

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
