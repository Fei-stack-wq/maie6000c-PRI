/* Product UI: real API reads and CSV ingestion; no simulated review writes. */
(() => {
  'use strict';
  const api = window.ReviewAPI;
  const root = document.getElementById('app');
  const key = 'reviewlens.batch-receipts.v1';
  let receipts = [];
  try { receipts = JSON.parse(localStorage.getItem(key) || '[]'); } catch (_) { /* private browsing */ }
  if (!Array.isArray(receipts)) receipts = [];
  receipts = receipts.filter(x => x && typeof x.batch_id === 'string').slice(0, 20);
  let generation = 0;
  let timer;
  let lastUpload = null;
  const pageSize = 20;
  const meta = {
    batches: ['批次上传', 'INGESTION', '上传 CSV，查看校验结果与后台分析进度。'],
    comments: ['评论', 'COMMENTS', '查询已保存评论、分析状态与原文证据。'],
    issues: ['问题组', 'ISSUES', '查看后台保存的问题建议；当前归组仍是类别基线。'],
    reviews: ['人工复核', 'HUMAN REVIEW', '查看问题证据与已有判断；人工操作接口接入后开放编辑。'],
    about: ['关于', 'ABOUT', 'ReviewLens 商品评论管理与问题发现系统。']
  };
  const labels = {queued:'排队中', analyzing:'分析中', analyzed:'已分析', failed:'失败',
    pending:'待处理', claimed:'处理中', completed:'已完成', imported:'已导入',
    partially_failed:'部分失败', rejected:'已拒绝', received:'已接收', validating:'校验中',
    proposed:'待确认', confirmed:'已确认', resolved:'已解决', dismissed:'已忽略',
    suggested:'AI 建议', accepted:'人工已接受', yes:'有问题', no:'未发现问题', unknown:'待判断',
    quality:'质量', logistics:'物流', mismatch:'描述不符', usability:'使用体验', other:'其他',
    llm:'大模型', heuristic:'规则'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const name = value => labels[value] || value || '—';
  const badge = value => `<span class="status-badge status-badge--neutral">${esc(name(value))}</span>`;
  const panel = (title, body) => `<section class="panel live-panel"><h2>${esc(title)}</h2>${body}</section>`;
  const notice = text => `<p class="live-notice" role="status">${esc(text)}</p>`;
  const table = (heads, rows) => `<div class="table-wrap"><table class="data-table"><thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows || `<tr><td colspan="${heads.length}">暂无记录</td></tr>`}</tbody></table></div>`;
  const link = (kind, id, text) => `<a class="text-link" href="#/${kind}/${encodeURIComponent(id)}">${esc(text || id)}</a>`;
  function route() {
    const [path, search = ''] = location.hash.slice(2).split('?');
    const [view, id] = (path || 'batches').split('/');
    return {view: meta[view] ? view : 'batches', id: id ? decodeURIComponent(id) : null,
      params: new URLSearchParams(search)};
  }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(receipts)); } catch (_) { /* API data remains persisted */ }
  }
  function errorView(error) {
    return notice(`读取失败：${error.message}。请确认项目服务已启动。`) + '<button class="btn" data-refresh>重试</button>';
  }
  function statsView(s) {
    return '<div class="stats-grid">' + [
      ['已接收评论',s.received_rows], ['已分析',s.analyzed_rows],
      ['待处理 / 处理中',s.processing_rows], ['分析失败',s.failed_rows],
      ['含待确认 AI 建议的评论',s.ai_suggested_count], ['含人工已接受关联的评论',s.human_accepted_count]
    ].map(([label,value]) => `<article class="stat-card"><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}</div></article>`).join('') + '</div>';
  }
  function uploadForm() {
    return panel('上传评论批次', `<form id="live-upload" class="upload-form">
      <label>来源平台 <input class="input" name="platform" value="amazon_sample" required maxlength="32"></label>
      <label>CSV 文件 <input class="input" name="file" type="file" accept=".csv,text/csv" required></label>
      <p>UTF-8 CSV；必填列：shop_id、product_id、body。可选：source_review_id、review_date、rating。</p>
      <p>最多 5,000 行，正文最多 2,000 字符；本页面单次文件上限 10 MB。</p>
      <button class="btn btn-primary" type="submit">上传并分析</button>
      <p id="upload-result" role="status" aria-live="polite"></p></form>`) +
      panel('查找已有批次', `<form id="find-batch" class="upload-row"><label>批次编号 <input class="input" name="batch" required></label><button class="btn">查询</button></form>`);
  }
  async function batches(token, id) {
    root.innerHTML = uploadForm() + '<div id="live-batches" aria-live="polite">正在读取批次…</div>';
    const ids = id ? [id] : receipts.map(x=>x.batch_id);
    async function refresh() {
      const results = await Promise.allSettled(ids.map(async batchId => {
        const [progress, errors] = await Promise.all([api.batch(batchId), api.errors(batchId)]);
        return {progress, errors, receipt: receipts.find(x=>x.batch_id === batchId)};
      }));
      if (token !== generation) return;
      const rows = results.map((r, i) => {
        if (r.status === 'rejected') return panel(ids[i], errorView(r.reason));
        const {progress:p, errors, receipt:rct} = r.value;
        return panel(`批次 ${p.batch_id}`, `<p>${esc(rct?.filename || '已有批次')} ${badge(p.status)}</p>` +
          (rct ? `<p>接收 ${esc(rct.accepted_rows)} · 重复 ${esc(rct.duplicate_rows)} · 无效 ${esc(rct.invalid_rows)}</p>` : '') +
          `<p>任务 ${p.job_count} · 排队 ${p.pending_rows} · 处理中 ${p.processing_rows} · 已分析 ${p.analyzed_rows} · 失败 ${p.failed_rows}</p>` +
          `<p>分析覆盖率：${p.analysis_coverage == null ? '—' : (p.analysis_coverage * 100).toFixed(0)+'%'}</p>` +
          (p.pending_rows || p.processing_rows ? notice('后台正在处理，每 3 秒更新进度；重试等待期间也会显示排队。') : '') +
          table(['错误行','字段','原因'], errors.map(e=>`<tr><td>${e.row_number}</td><td>${esc(e.column_name)}</td><td>${esc(e.message)}</td></tr>`).join('')) +
          '<p><a class="text-link" href="#/comments">查看评论</a> · <a class="text-link" href="#/issues">查看问题组</a></p>');
      }).join('');
      document.getElementById('live-batches').innerHTML = rows || notice('暂无本浏览器的上传记录。上传记录保存在本浏览器；已知批次编号可在上方查询，业务数据保存在数据库。');
      if (results.some(r=>r.status==='fulfilled' && (r.value.progress.pending_rows || r.value.progress.processing_rows))) {
        timer = setTimeout(() => refresh().catch(showError), 3000);
      }
    }
    function showError(e) { if (token === generation) document.getElementById('live-batches').innerHTML = errorView(e); }
    await refresh();
  }
  function filters(view, p) {
    const option = (key, values) => `<label>${key==='analysis_status'?'分析状态':key==='has_issue'?'问题判断':key==='category_id'?'类别':'问题组状态'} <select class="input" name="${key}"><option value="">全部</option>${values.map(v=>`<option value="${v}" ${p.get(key)===v?'selected':''}>${esc(name(v))}</option>`).join('')}</select></label>`;
    return `<form id="live-filter" class="live-filters" data-view="${view}"><label>商品编号 <input class="input" name="product_id" value="${esc(p.get('product_id'))}" placeholder="例如 B009MA34NY"></label>` +
      (view==='comments' ? option('analysis_status',['queued','analyzing','analyzed','failed'])+option('has_issue',['yes','no','unknown']) :
        option('status',['proposed','confirmed','resolved','dismissed'])+option('category_id',['quality','logistics','mismatch','usability','other'])) +
      '<button class="btn btn-primary">筛选</button><button class="btn" type="button" data-refresh>刷新</button></form>';
  }
  function pager(view, p, offset, more) {
    const target = next => { const q=new URLSearchParams(p);q.set('offset',next);return `#/${view}?${q}`; };
    return `<div class="table-foot"><span>第 ${Math.floor(offset/pageSize)+1} 页 · 每页 ${pageSize} 条</span><span>${offset ? `<a href="${esc(target(Math.max(0,offset-pageSize)))}">上一页</a>`:''} ${more ? `<a href="${esc(target(offset+pageSize))}">下一页</a>`:''}</span></div>`;
  }
  async function listing(view, p, token) {
    const offset = Math.max(0, Number(p.get('offset')) || 0);
    const allowed = view==='comments' ? ['product_id','analysis_status','has_issue'] : ['product_id','status','category_id'];
    const query = Object.fromEntries(allowed.map(k=>[k,p.get(k)]));
    const result = await api[view==='reviews'?'issues':view]({...query,offset,limit:pageSize+1});
    const stats = view==='comments' ? await api.stats({product_id:p.get('product_id')}) : null;
    if (token !== generation) return;
    const items = result.slice(0,pageSize);
    const rows = items.map(x=>view==='comments' ? `<tr><td>${link('comments',x.id,x.source_review_id)}</td><td>${esc(x.product_id)}</td><td class="live-body">${esc(x.body)}</td><td>${esc(x.rating ?? '—')}</td><td>${badge(x.analysis_status)}</td><td>${badge(x.has_issue)}</td></tr>` :
      `<tr><td>${link(view,x.id,x.title)}</td><td>${esc(x.product_id)}</td><td>${esc(name(x.category_id))}</td><td>${badge(x.status)}</td><td>${x.suggested_count}</td><td>${x.accepted_count}</td></tr>`).join('');
    root.innerHTML = (stats ? statsView(stats):'') +
      (view==='reviews'?notice('复核操作接口尚未接入。本页可查看证据和历史，不会模拟接受、拒绝或已解决。'):'') +
      panel(view==='comments'?'评论列表':'问题组列表', filters(view,p) + table(view==='comments' ? ['来源评论编号','商品','正文','评分','分析状态','问题判断'] : ['问题','商品','类别','状态','AI 待确认关联','人工已接受关联'], rows) + pager(view,p,offset,result.length>pageSize));
  }
  function evidence(items) {
    return table(['评论','问题组','判断','证据原文','核验','有效性'],items.map(x=>`<tr><td>${link('comments',x.comment_id)}</td><td>${link('issues',x.issue_id)}</td><td>${badge(x.status)}</td><td class="live-body">${esc(x.evidence_text || '—')}</td><td>${x.evidence_verified?'原文已核验':'未核验'}</td><td>${x.superseded_at?'历史关联（已替代）':'当前关联'}</td></tr>`).join(''));
  }
  async function detail(view, id, token) {
    const x = await (view==='comments'?api.comment(id):api.issue(id));
    if (token !== generation) return;
    const back = `<p><a class="text-link" href="#/${view}">← 返回列表</a> <button class="btn" data-refresh>刷新</button></p>`;
    if (view==='comments') {
      const r=x.latest_analysis_run;
      root.innerHTML = back + panel('评论详情', `<p>商品 ${esc(x.product_id)} · 评分 ${esc(x.rating ?? '—')} · 日期 ${esc(x.review_date || '—')}</p><p>${badge(x.analysis_status)} ${badge(x.has_issue)}</p><blockquote class="live-body">${esc(x.body)}</blockquote>` +
        (x.analysis_error ? notice(x.analysis_error):'') + (r ? `<p>来源：${esc(name(r.source))} · 模型：${esc(r.model_version)} · 提示词：${esc(r.prompt_version)} · 分析记录：${esc(r.status)}</p><p>回退原因：${esc(r.fallback_reason || '无')} · 耗时：${esc(r.latency_ms ?? '—')} ms</p>` : notice('尚无分析记录，等待后台处理。'))) +
        panel('问题关联与原文证据', evidence(x.issues)) + panel('评论版本',table(['版本','正文'],x.revisions.map(r=>`<tr><td>${r.version}</td><td class="live-body">${esc(r.body)}</td></tr>`).join('')));
    } else {
      root.innerHTML = back + panel(x.title, `<p>商品 ${esc(x.product_id)} · ${esc(name(x.category_id))} · ${badge(x.status)}</p><p>${esc(x.description || '')}</p><p>待确认关联 ${x.suggested_count} · 人工已接受关联 ${x.accepted_count}</p>` + notice('当前只读。确认、拒绝、合并与处理备注将在人工操作接口完成后接入。')) +
        panel('评论证据（含历史关联）',evidence(x.links)) + panel('操作历史',table(['时间','操作','操作人','备注'],x.actions.map(a=>`<tr><td>${esc(a.created_at)}</td><td>${esc(a.action)}</td><td>${esc(a.operator)}</td><td>${esc(a.note)}</td></tr>`).join('')));
    }
  }
  async function render() {
    clearTimeout(timer);
    const token=++generation;
    const {view,id,params}=route();
    const [title,kicker,subtitle]=meta[view];
    document.getElementById('page-title').textContent=title;
    document.getElementById('page-kicker').textContent=kicker;
    document.getElementById('page-subtitle').textContent=subtitle;
    document.title=`${title} · ReviewLens`;
    document.querySelectorAll('[data-route]').forEach(a=>{a.classList.toggle('is-active',a.dataset.route===view);if(a.dataset.route===view)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    root.innerHTML=notice('正在加载…');
    try {
      if (location.protocol==='file:') throw new Error('请启动项目后通过 http://localhost:8000/ui/ 打开');
      if (view==='batches') await batches(token,id);
      else if (view==='about') root.innerHTML=panel('当前功能', '<p>CSV 导入 → 数据库存储 → Worker 后台分析 → 证据核验 → 评论与问题查询。</p><p>AI 仅提供建议；当前归组采用类别基线，语义归组与人工操作由后续模块提供。</p><p><a href="/docs">API 文档</a> · <a href="../legacy/">原始静态设计预览（模拟数据）</a></p>');
      else if (id) await detail(view,id,token);
      else await listing(view,params,token);
    } catch(e) { if(token===generation) root.innerHTML=errorView(e); }
  }
  root.addEventListener('click', e=>{if(e.target.closest('[data-refresh]'))render();});
  root.addEventListener('submit', async e=>{
    e.preventDefault();
    const form=e.target;
    if(form.id==='live-filter') { const p=new URLSearchParams(new FormData(form));location.hash=`/${form.dataset.view}?${p}`;return; }
    if(form.id==='find-batch') {location.hash=`/batches/${encodeURIComponent(form.elements.batch.value.trim())}`;return;}
    if(form.id!=='live-upload')return;
    const button=form.querySelector('button[type="submit"]');
    const output=document.getElementById('upload-result');
    const file=form.elements.file.files[0];
    if(!file)return;
    const token=generation;
    button.disabled=true;output.textContent='正在上传，请勿重复提交…';
    try {
      if(file.size>10*1024*1024)throw new Error('文件超过 10 MB，请拆分后上传。');
      const payload={platform:form.elements.platform.value.trim(),filename:file.name,csv_text:await file.text()};
      if(!payload.platform)throw new Error('请填写来源平台。');
      const signature=JSON.stringify(payload);
      // Reuse the key after a network timeout; a later retry must not duplicate a received batch.
      if(!lastUpload || lastUpload.signature!==signature)lastUpload={signature,id:crypto.randomUUID()};
      const receipt=await api.upload({...payload,idempotency_key:lastUpload.id});
      lastUpload=null;
      receipts=[{...receipt,filename:file.name},...receipts.filter(x=>x.batch_id!==receipt.batch_id)].slice(0,20);
      persist();
      if(token===generation) {location.hash=`/batches/${encodeURIComponent(receipt.batch_id)}`;}
    } catch(error) {
      if(error.status && error.status<500)lastUpload=null;
      if(error.detail?.batch_id && token===generation) {
        location.hash=`/batches/${encodeURIComponent(error.detail.batch_id)}`;
      } else if(token===generation)output.textContent=`上传失败：${error.message}`;
    } finally {button.disabled=false;}
  });
  window.addEventListener('hashchange',render);
  render();
})();
