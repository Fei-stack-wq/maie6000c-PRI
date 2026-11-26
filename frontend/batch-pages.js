(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const date = value => value ? new Date(value).toLocaleString(I18n.locale) : I18n.t('未提供');
  const stages = {received: I18n.t('已接收'), validating: I18n.t('校验中'), rejected: I18n.t('整批拒收'), imported: I18n.t('已入库'),
    stopped: WorkbenchUI.tr('已停止', 'Stopped'), completed: I18n.t('处理完成'), partially_failed: I18n.t('部分处理失败')};
  const progressStages = {...stages, imported: I18n.t('等待或正在分析')};
  const messages = {
    csv_required: I18n.t('请选择扩展名为 .csv 的文件。'), empty_file: I18n.t('文件为空，请先填入评论数据。'),
    file_too_large: I18n.t('文件超过 10 MiB，请拆分后上传。'), invalid_utf8: I18n.t('文件不是有效的 UTF-8 编码，请另存为 CSV UTF-8 后重试。'),
    invalid_platform: I18n.t('请填写 1–32 个字符的平台标识。'), filename_too_long: I18n.t('文件名超过 255 个字符，请缩短。'),
    idempotency_conflict: I18n.t('此次重试与原请求不一致，请重新选择文件。')
  };
  const codes = {missing_columns: I18n.t('缺少必填列'), unknown_columns: I18n.t('忽略额外列（提示）'),
    required: I18n.t('缺少必填值'), too_long: I18n.t('内容过长'), invalid_rating: I18n.t('评分应为 0–5 的整数'),
    invalid_date: I18n.t('日期格式不正确'), extra_columns: I18n.t('该行字段数量超出表头'), invalid_header: I18n.t('表头列名为空、重复或含非法字符'),
    invalid_csv: I18n.t('CSV 引号或字段格式错误'), empty_csv: I18n.t('没有数据行'), too_many_rows: I18n.t('超过 5,000 行'),
    file_too_large: I18n.t('超过 10 MiB'), invalid_character: I18n.t('含不支持的字符'), duplicate_row: I18n.t('批内重复行')};
  const link = (href, label, style = 'btn') => `<a class="${style}" href="${esc(href)}">${esc(label)}</a>`;

  function mountList(root, route) {
    const values = route.filters, page = Number(values.page);
    let loading = false, uploading = false, total = 0, generation = 0;
    root.innerHTML = `<div class="batch-recycle-toolbar"><h2>${values.trash === '1' ? WorkbenchUI.tr('回收站', 'Trash') : WorkbenchUI.tr('批次管理', 'Batch management')}</h2>
      ${link(ProductRoutes.href('batches'), WorkbenchUI.tr('正常批次', 'Active batches'))}
      ${link(ProductRoutes.href('batches', null, {trash: '1'}), WorkbenchUI.tr('回收站', 'Trash'))}</div>` + I18n.html`<section class="panel batch-upload-panel"><h2>上传评论 CSV</h2>
      <p>每个文件对应一个平台。有效行入库后，后台自动分析；无效行会列出原因，供修正后重传。</p>
      <p>必填列：<code>shop_id, product_id, body</code>；可选列：<code>source_review_id, review_date, rating</code>。</p>
      <p>UTF-8 编码 · 最多 5,000 行 · 最大 10 MiB · 正文最多 2,000 字符</p>
      <div class="human-review-actions">
        ${link('./review-template.csv', I18n.t('下载 CSV 示例'), 'text-link')}
        <a class="text-link" href="./test-data/chinese_product_reviews_50.csv" download="chinese_product_reviews_50.csv">${WorkbenchUI.tr('下载中文测试集（50 条）', 'Download Chinese test reviews (50)')}</a>
        <a class="text-link" href="./test-data/amazon_fashion_60.csv" download="amazon_fashion_60.csv">${WorkbenchUI.tr('下载英文测试集（60 条）', 'Download English test reviews (60)')}</a>
      </div>
      ${ReviewAPI.canReview ? I18n.html`<form id="batch-upload-form" class="human-review-manual-form">
        <label for="batch-platform">平台标识</label><input id="batch-platform" name="platform" required maxlength="32" placeholder="例如 taobao 或 amazon" autocomplete="off">
        <label for="batch-file">CSV 文件</label><input id="batch-file" name="file" type="file" accept=".csv,text/csv" required>
        <button class="btn btn-primary" type="submit">上传并导入</button></form>` :
        I18n.t('<p class="human-review-notice">当前账号只读：可以查看批次和进度，上传需要复核员权限。</p>')}
      <p id="batch-upload-feedback" role="status" aria-live="polite"></p>
      <p class="live-product-meta">${WorkbenchUI.tr('不同批次分别保存、分析和归组；同批次的重复来源编号按导入规则处理。', 'Different batches are saved, analyzed and grouped independently. Repeated source IDs within one batch follow the import rules.')}</p>
      </section><section class="panel live-product-head"><h2>批次记录</h2>
      <p>列表显示导入阶段的结果，进入详情可查看后台分析进度。</p>
      <form id="batch-filter" class="human-review-filters">
        <label>筛选平台<input name="platform" maxlength="32" value="${esc(values.platform)}" placeholder="全部平台"></label>
        <label>搜索文件名<input name="q" maxlength="200" value="${esc(values.q)}"></label>
        <button class="btn btn-primary">查询批次</button><button class="btn" type="button" id="batch-clear">清除筛选</button>
      </form></section><div class="live-product-summary"><p id="batch-count" role="status"></p>
        <button class="btn" id="batch-reload">刷新批次</button></div>
      <div id="batch-results" class="live-product-cards"></div>
      <div class="human-review-pagination"><button class="btn" id="batch-prev" disabled>上一页</button>
        <span id="batch-page"></span><button class="btn" id="batch-next" disabled>下一页</button></div>`;
    const $ = s => root.querySelector(s);
    root.querySelector('a[href="./review-template.csv"]').setAttribute('download', 'review-template.csv');
    if (values.trash === '1') root.querySelector('.batch-upload-panel').hidden = true;
    BatchActions.mount(root, () => load());
    function controls() {
      $('#batch-prev').disabled = loading || page <= 1;
      $('#batch-next').disabled = loading || page * 20 >= total;
      $('#batch-reload').disabled = loading;
    }
    function navigate(filters) {
      const hash = ProductRoutes.href('batches', null, filters);
      if (window.location.hash === hash) load(); else window.location.hash = hash;
    }
    async function load() {
      const call = ++generation;
      loading = true; controls();
      $('#batch-count').textContent = I18n.t('正在读取批次…');
      $('#batch-page').textContent = ''; $('#batch-results').innerHTML = '';
      const params = new URLSearchParams({limit: '20', offset: String((page - 1) * 20)});
      for (const key of ['platform', 'q', 'trash']) if (values[key]) params.set(key, values[key]);
      try {
        const data = await ReviewAPI.request('/review-batches?' + params, undefined, {page: true});
        if (!root.isConnected || call !== generation) return;
        total = data.total;
        if (!data.items.length && page > 1) { navigate({...values, page: String(Math.max(1, Math.ceil(total / 20)))}); return; }
        $('#batch-count').textContent = I18n.html`符合条件：${total} 个批次`;
        $('#batch-page').textContent = I18n.html`第 ${page} / ${Math.max(1, Math.ceil(total / 20))} 页`;
        $('#batch-results').innerHTML = data.items.length ? data.items.map(b => I18n.html`<article class="panel live-product-card">
          <div class="live-product-tags"><span>${esc(b.platform)}</span><span>${esc(stages[b.status] || b.status)}</span></div>
          <h3>${b.deleted_at ? esc(b.file_ref || I18n.t('未提供文件名')) : link(ProductRoutes.href('batches', b.id, values), b.file_ref || I18n.t('未提供文件名'), 'text-link')}</h3>
          <p>新增 ${b.accepted_rows} · 重复来源 ${b.duplicate_rows} · 无效 ${b.invalid_rows}</p>
          <p class="live-product-meta">${esc(b.id)}<br>${esc(date(b.created_at))}</p>
          ${b.deleted_at ? '' : link(ProductRoutes.href('batches', b.id, values), I18n.t('查看进度与校验结果'))}${BatchActions.html(b)}</article>`).join('') :
          I18n.t('<section class="panel"><p>没有符合条件的批次。</p></section>');
      } catch (_) {
        if (!root.isConnected || call !== generation) return;
        total = 0; $('#batch-count').textContent = I18n.t('批次加载失败，请点击“刷新批次”重试。');
      } finally {
        if (root.isConnected && call === generation) { loading = false; controls(); }
      }
    }
    $('#batch-filter').addEventListener('submit', event => {
      event.preventDefault(); navigate({...Object.fromEntries(new FormData(event.currentTarget)), page: '1'});
    });
    $('#batch-clear').addEventListener('click', () => navigate({}));
    $('#batch-reload').addEventListener('click', load);
    $('#batch-prev').addEventListener('click', () => navigate({...values, page: String(page - 1)}));
    $('#batch-next').addEventListener('click', () => navigate({...values, page: String(page + 1)}));
    $('#batch-upload-form')?.addEventListener('submit', async event => {
      event.preventDefault();
      if (uploading || !ReviewAPI.canReview) return;
      const form = event.currentTarget, feedback = $('#batch-upload-feedback');
      uploading = true; form.inert = true; root.setAttribute('aria-busy', 'true');
      feedback.textContent = I18n.t('正在读取文件并提交，请稍候…');
      try {
        const payload = await BatchUpload.prepare($('#batch-file').files[0], $('#batch-platform').value);
        if (!root.isConnected) return;
        const data = await ReviewAPI.request('/review-batches', payload);
        if (root.isConnected) window.location.hash = ProductRoutes.href('batches', data.batch_id, values);
      } catch (error) {
        if (!root.isConnected) return;
        if (error.detail?.code === 'batch_rejected' && error.detail.batch_id) {
          window.location.hash = ProductRoutes.href('batches', error.detail.batch_id, values);
        } else feedback.textContent = messages[error.message] ||
          I18n.t('上传未确认完成。请先查看批次记录，或使用相同文件及平台重试；本浏览器会话内会复用同一请求，避免重复创建批次。');
      } finally {
        uploading = false; form.inert = false; root.setAttribute('aria-busy', 'false');
      }
    });
    load();
  }

  function mountDetail(root, route) {
    let generation = 0, timer = null;
    root.innerHTML = I18n.html`<div class="human-review-actions">${link(ProductRoutes.href('batches', null, route.filters), I18n.t('← 返回批次列表'))}
      <button class="btn" id="batch-detail-reload">刷新进度</button></div>
      <p id="batch-refresh-status" role="status" aria-live="polite"></p><div id="batch-detail"></div>`;
    const area = root.querySelector('#batch-detail'), notice = root.querySelector('#batch-refresh-status');
    const button = root.querySelector('#batch-detail-reload');
    const base = '/review-batches/' + encodeURIComponent(route.detailId);
    async function load() {
      clearTimeout(timer);
      const call = ++generation;
      button.disabled = true; notice.textContent = I18n.t('正在读取批次进度…');
      try {
        const [data, errors] = await Promise.all([ReviewAPI.request(base), ReviewAPI.request(base + '/errors')]);
        if (!root.isConnected || call !== generation) return;
        const b = data.batch, waiting = data.pending_rows + data.processing_rows + data.waiting_rows > 0;
        area.innerHTML = I18n.html`<section class="panel live-comment-detail"><div class="live-product-tags">
          <span>${esc(progressStages[data.status] || data.status)}</span><span>${esc(b.platform)}</span></div>
          <h2>${esc(b.file_ref || I18n.t('未提供文件名'))}</h2><p class="live-product-meta">批次：${esc(b.id)}<br>创建：${esc(date(b.created_at))}</p>
          ${data.status === 'rejected' ? I18n.t('<p class="human-review-notice">整批拒收：没有导入本批次评论。请按下方原因修正文件后重新上传。</p>') : ''}
          <h3>导入结果</h3><div class="batch-metrics">
            <p>读取数据行<strong>${b.declared_rows ?? '—'}</strong></p><p>新增评论<strong>${b.accepted_rows}</strong></p>
            <p>重复来源<strong>${b.duplicate_rows}</strong></p><p>无效行<strong>${b.invalid_rows}</strong></p></div>
          <p>${WorkbenchUI.tr('每次上传保留独立批次记录，不覆盖其他批次；同一请求重试不会重复建立批次。无效行数按校验记录统计。', 'Each upload keeps an independent batch snapshot. Retrying the same request does not create another batch. Invalid rows follow validation records.')}</p>
          <h3>当前分析进度</h3><div class="batch-metrics">
            <p>当前关联评论<strong>${data.current_rows}</strong></p><p>分析完成<strong>${data.analyzed_rows}</strong></p>
            <p>${WorkbenchUI.tr('已取消', 'Cancelled')}<strong>${data.cancelled_rows}</strong></p><p>等待或分析中<strong>${data.waiting_rows}</strong></p><p>分析失败<strong>${data.failed_rows}</strong></p></div>
          <p>${WorkbenchUI.tr('分析覆盖率', 'Analysis coverage')}: ${data.analysis_coverage == null ? I18n.t('不适用') : (data.analysis_coverage * 100).toFixed(1) + '%'}.
            ${WorkbenchUI.tr('本批次任务', 'Jobs in this batch')}: ${data.job_count}; ${WorkbenchUI.tr('待处理', 'Pending')}: ${data.pending_rows}, ${WorkbenchUI.tr('处理中', 'Processing')}: ${data.processing_rows}, ${WorkbenchUI.tr('失败', 'Failed')}: ${data.failed_jobs}.</p>
          <p class="live-product-meta">${WorkbenchUI.tr('评论与分析结果固定归属本批次。停止后仅展示已完成结果，原始导入记录保留取消状态。', 'Reviews and results belong to this batch. After stopping, result pages show only completed analyses; imported records retain cancellation status.')}</p>
          ${link(ProductRoutes.href('comments', null, {batch_id: b.id}), I18n.t('查看本批次当前评论'), 'btn btn-primary')}
          ${link(ProductRoutes.href('issues', null, {batch_ids: b.id}), WorkbenchUI.tr('查看本批次问题', 'View this batch’s issues'))}
          ${BatchActions.html({...b, unfinished_rows: data.waiting_rows + data.failed_rows})}
          ${b.legacy_incomplete ? '<p class="human-review-notice">' + WorkbenchUI.tr('旧版导入未完整保留全部历史批次记录。', 'Older imports did not retain every historical batch occurrence.') + '</p>' : ''}
          </section><section class="panel batch-errors"><h2>${WorkbenchUI.tr('校验结果', 'Validation results')} · ${errors.length} ${WorkbenchUI.tr('条记录', 'records')}</h2>
          ${errors.length ? '<ol>' + errors.map(e => I18n.html`<li><strong>第 ${e.row_number} 条记录${e.column_name ? ' · ' + esc(e.column_name) : ''}：${esc(codes[e.code] || e.code)}</strong>
            <p>${esc(e.message)}</p></li>`).join('') + '</ol>' : I18n.t('<p>没有行级错误或列名提示。</p>')}
          <p class="live-product-meta">CSV 表头计为第 1 条记录，带换行的引号字段仍计为一条记录。“忽略额外列”是提示，不计入无效行。</p></section>`;
        BatchActions.records(area, b.id);
        notice.textContent = I18n.html`已更新：${new Date().toLocaleTimeString(I18n.locale)}。${waiting ? I18n.t('后台分析尚未结束，每 5 秒自动刷新。') : I18n.t('需要查看最新状态时可点击刷新。')}`;
        if (waiting) timer = setTimeout(() => { if (root.isConnected) load(); }, 5000);
      } catch (error) {
        if (!root.isConnected || call !== generation) return;
        area.innerHTML = '';
        notice.textContent = error.message === 'batch_not_found' ? I18n.t('批次不存在，请返回列表重新选择。') : I18n.t('批次进度加载失败，请点击“刷新进度”重试。');
      } finally {
        if (root.isConnected && call === generation) button.disabled = false;
      }
    }
    BatchActions.mount(root, async action => {
      if (['trash', 'purge'].includes(action)) window.location.hash = ProductRoutes.href('batches', null, route.filters);
      else await load();
    });
    button.addEventListener('click', load); load();
  }
  window.BatchPages = {mount(root, route) {
    ReviewAuth.mount(root, workspace => {
      workspace.innerHTML = '<div id="review-workspace" aria-busy="false"></div>';
      const host = workspace.firstElementChild;
      const current = ProductRoutes.parse(window.location.hash) || route;
      if (current.detailId) mountDetail(host, current); else mountList(host, current);
    });
  }};
})();
