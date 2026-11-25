(function () {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const date = value => value ? new Date(value).toLocaleString() : '未提供';
  const stages = {received: '已接收', validating: '校验中', rejected: '整批拒收', imported: '已入库',
    completed: '处理完成', partially_failed: '部分处理失败'};
  const progressStages = {...stages, imported: '等待或正在分析'};
  const messages = {
    csv_required: '请选择扩展名为 .csv 的文件。', empty_file: '文件为空，请先填入评论数据。',
    file_too_large: '文件超过 10 MiB，请拆分后上传。', invalid_utf8: '文件不是有效的 UTF-8 编码，请另存为 CSV UTF-8 后重试。',
    invalid_platform: '请填写 1–32 个字符的平台标识。', filename_too_long: '文件名超过 255 个字符，请缩短。',
    idempotency_conflict: '此次重试与原请求不一致，请重新选择文件。'
  };
  const codes = {missing_columns: '缺少必填列', unknown_columns: '忽略额外列（提示）',
    required: '缺少必填值', too_long: '内容过长', invalid_rating: '评分应为 0–5 的整数',
    invalid_date: '日期格式不正确', extra_columns: '该行字段数量超出表头', invalid_header: '表头列名为空、重复或含非法字符',
    invalid_csv: 'CSV 引号或字段格式错误', empty_csv: '没有数据行', too_many_rows: '超过 5,000 行',
    file_too_large: '超过 10 MiB', invalid_character: '含不支持的字符', duplicate_row: '批内重复行'};
  const link = (href, label, style = 'btn') => `<a class="${style}" href="${esc(href)}">${esc(label)}</a>`;

  function mountList(root, route) {
    const values = route.filters, page = Number(values.page);
    let loading = false, uploading = false, total = 0, generation = 0;
    root.innerHTML = `<section class="panel batch-upload-panel"><h2>上传评论 CSV</h2>
      <p>每个文件对应一个平台。有效行入库后，后台自动分析；无效行会列出原因，供修正后重传。</p>
      <p>必填列：<code>shop_id, product_id, body</code>；可选列：<code>source_review_id, review_date, rating</code>。</p>
      <p>UTF-8 编码 · 最多 5,000 行 · 最大 10 MiB · 正文最多 2,000 字符</p>
      ${link('./review-template.csv', '下载 CSV 示例', 'text-link')}
      ${ReviewAPI.canReview ? `<form id="batch-upload-form" class="human-review-manual-form">
        <label for="batch-platform">平台标识</label><input id="batch-platform" name="platform" required maxlength="32" placeholder="例如 taobao 或 amazon" autocomplete="off">
        <label for="batch-file">CSV 文件</label><input id="batch-file" name="file" type="file" accept=".csv,text/csv" required>
        <button class="btn btn-primary" type="submit">上传并导入</button></form>` :
        '<p class="human-review-notice">当前账号只读：可以查看批次和进度，上传需要复核员权限。</p>'}
      <p id="batch-upload-feedback" role="status" aria-live="polite"></p>
      <p class="live-product-meta">重复来源编号会去重；正文变化会保留旧版本并触发重新分析，相关人工证据可能需要重新核对。</p>
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
      $('#batch-count').textContent = '正在读取批次…';
      $('#batch-page').textContent = ''; $('#batch-results').innerHTML = '';
      const params = new URLSearchParams({limit: '20', offset: String((page - 1) * 20)});
      for (const key of ['platform', 'q']) if (values[key]) params.set(key, values[key]);
      try {
        const data = await ReviewAPI.request('/review-batches?' + params, undefined, {page: true});
        if (!root.isConnected || call !== generation) return;
        total = data.total;
        if (!data.items.length && page > 1) { navigate({...values, page: String(Math.max(1, Math.ceil(total / 20)))}); return; }
        $('#batch-count').textContent = `符合条件：${total} 个批次`;
        $('#batch-page').textContent = `第 ${page} / ${Math.max(1, Math.ceil(total / 20))} 页`;
        $('#batch-results').innerHTML = data.items.length ? data.items.map(b => `<article class="panel live-product-card">
          <div class="live-product-tags"><span>${esc(b.platform)}</span><span>${esc(stages[b.status] || b.status)}</span></div>
          <h3>${link(ProductRoutes.href('batches', b.id, values), b.file_ref || '未提供文件名', 'text-link')}</h3>
          <p>新增 ${b.accepted_rows} · 重复来源 ${b.duplicate_rows} · 无效 ${b.invalid_rows}</p>
          <p class="live-product-meta">${esc(b.id)}<br>${esc(date(b.created_at))}</p>
          ${link(ProductRoutes.href('batches', b.id, values), '查看进度与校验结果')}</article>`).join('') :
          '<section class="panel"><p>没有符合条件的批次。</p></section>';
      } catch (_) {
        if (!root.isConnected || call !== generation) return;
        total = 0; $('#batch-count').textContent = '批次加载失败，请点击“刷新批次”重试。';
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
      feedback.textContent = '正在读取文件并提交，请稍候…';
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
          '上传未确认完成。请先查看批次记录，或使用相同文件及平台重试；本浏览器会话内会复用同一请求，避免重复创建批次。';
      } finally {
        uploading = false; form.inert = false; root.setAttribute('aria-busy', 'false');
      }
    });
    load();
  }

  function mountDetail(root, route) {
    let generation = 0, timer = null;
    root.innerHTML = `<div class="human-review-actions">${link(ProductRoutes.href('batches', null, route.filters), '← 返回批次列表')}
      <button class="btn" id="batch-detail-reload">刷新进度</button></div>
      <p id="batch-refresh-status" role="status" aria-live="polite"></p><div id="batch-detail"></div>`;
    const area = root.querySelector('#batch-detail'), notice = root.querySelector('#batch-refresh-status');
    const button = root.querySelector('#batch-detail-reload');
    const base = '/review-batches/' + encodeURIComponent(route.detailId);
    async function load() {
      clearTimeout(timer);
      const call = ++generation;
      button.disabled = true; notice.textContent = '正在读取批次进度…';
      try {
        const [data, errors] = await Promise.all([ReviewAPI.request(base), ReviewAPI.request(base + '/errors')]);
        if (!root.isConnected || call !== generation) return;
        const b = data.batch, waiting = data.pending_rows + data.processing_rows + data.waiting_rows > 0;
        area.innerHTML = `<section class="panel live-comment-detail"><div class="live-product-tags">
          <span>${esc(progressStages[data.status] || data.status)}</span><span>${esc(b.platform)}</span></div>
          <h2>${esc(b.file_ref || '未提供文件名')}</h2><p class="live-product-meta">批次：${esc(b.id)}<br>创建：${esc(date(b.created_at))}</p>
          ${data.status === 'rejected' ? '<p class="human-review-notice">整批拒收：没有导入本批次评论。请按下方原因修正文件后重新上传。</p>' : ''}
          <h3>导入结果</h3><div class="batch-metrics">
            <p>读取数据行<strong>${b.declared_rows ?? '—'}</strong></p><p>新增评论<strong>${b.accepted_rows}</strong></p>
            <p>重复来源<strong>${b.duplicate_rows}</strong></p><p>无效行<strong>${b.invalid_rows}</strong></p></div>
          <p>重复来源包括正文未变的去重记录和正文已变的更新记录；更新会保留历史并重新分析。无效行数按校验记录统计，整批拒收时不代表每行都已检查。</p>
          <h3>当前分析进度</h3><div class="batch-metrics">
            <p>当前关联评论<strong>${data.current_rows}</strong></p><p>分析完成<strong>${data.analyzed_rows}</strong></p>
            <p>等待或分析中<strong>${data.waiting_rows}</strong></p><p>分析失败<strong>${data.failed_rows}</strong></p></div>
          <p>分析覆盖率：${data.analysis_coverage == null ? '不适用' : (data.analysis_coverage * 100).toFixed(1) + '%'}。
            本批次任务 ${data.job_count} 个，待处理 ${data.pending_rows}、处理中 ${data.processing_rows}、失败 ${data.failed_jobs}。</p>
          <p class="live-product-meta">评论再次更新后会归入新批次；这里的覆盖率以当前关联评论为分母，导入时的计数保持不变。</p>
          ${link(ProductRoutes.href('comments', null, {batch_id: b.id}), '查看本批次当前评论', 'btn btn-primary')}
          </section><section class="panel batch-errors"><h2>校验结果 · ${errors.length} 条记录</h2>
          ${errors.length ? '<ol>' + errors.map(e => `<li><strong>第 ${e.row_number} 条记录${e.column_name ? ' · ' + esc(e.column_name) : ''}：${esc(codes[e.code] || e.code)}</strong>
            <p>${esc(e.message)}</p></li>`).join('') + '</ol>' : '<p>没有行级错误或列名提示。</p>'}
          <p class="live-product-meta">CSV 表头计为第 1 条记录，带换行的引号字段仍计为一条记录。“忽略额外列”是提示，不计入无效行。</p></section>`;
        notice.textContent = `已更新：${new Date().toLocaleTimeString()}。${waiting ? '后台分析尚未结束，每 5 秒自动刷新。' : '需要查看最新状态时可点击刷新。'}`;
        if (waiting) timer = setTimeout(() => { if (root.isConnected) load(); }, 5000);
      } catch (error) {
        if (!root.isConnected || call !== generation) return;
        area.innerHTML = '';
        notice.textContent = error.message === 'batch_not_found' ? '批次不存在，请返回列表重新选择。' : '批次进度加载失败，请点击“刷新进度”重试。';
      } finally {
        if (root.isConnected && call === generation) button.disabled = false;
      }
    }
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
