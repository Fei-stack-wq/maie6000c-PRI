# Product frontend / 产品前端

## English

Start Docker Desktop, then run from the repository root:

```powershell
.\scripts\start_product_ui.ps1
```

Open http://localhost:8000/ui/. The script creates `.env` only if it is missing and keeps existing model settings. Startup applies database migrations. Without model settings, analysis uses rules.

1. On **Batch upload**, keep `amazon_sample` as the platform for the provided samples, choose the 10-row UTF-8 CSV, and upload it.
2. The resulting batch shows accepted, duplicate and invalid rows, then updates analysis progress every three seconds while work remains.
3. Open **Comments** to inspect the saved reviews. Filter by product, analysis status or issue verdict; open a row to see evidence, analysis source and fallback reason. Use Refresh to fetch newer analysis results.
4. Open **Issue groups** for current counts and evidence. **Human review** is read-only until the team supplies its write APIs. AI suggestions do not count as human acceptance.

CSV required columns: `shop_id,product_id,body`. Optional: `source_review_id,review_date,rating`. Maximum 5,000 rows; body maximum 2,000 characters. The browser limits files to 10 MB. The 10-row sample is included in the 60-row sample; repeating an import with the same platform should deduplicate existing reviews.

Batch receipts are kept in this browser (last 20); the backend currently has no batch-list endpoint. Clear browser storage or use another browser and this receipt list will be empty, but database records remain. Look up an existing batch by its ID; comment and issue lists always query the database. Different stacks, including the midterm demo, use different databases.

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
node --test tests/frontend/api.test.cjs
```

Stopping keeps database volumes. On macOS/Linux, create `.env` from `.env.example` on first setup and use `docker compose up -d --build --wait`. If API_HOST_PORT is overridden, use that port instead of 8000.

`api.js` owns HTTP contracts; `live.js` owns routes, forms and rendering; `live.css` supplements the original styles. The original `app.js` and `mock-data.js` remain available through `/ui/mock.html` as a static design preview. The bilingual midterm demo remains separate. Human writes and semantic grouping are pending backend work. These changes introduce no new model calls beyond the existing analysis workflow.

## 中文

先启动 Docker Desktop，在仓库根目录运行：

```powershell
.\scripts\start_product_ui.ps1
```

打开 http://localhost:8000/ui/。脚本只在缺少 `.env` 时创建它，保留已有模型配置；启动时自动执行数据库迁移。没有模型配置时使用规则分析。

1. 在**批次上传**页面，提供的样本保持来源平台为 `amazon_sample`，选择 10 条 UTF-8 CSV 并上传。
2. 页面显示接收、重复和无效行；任务未结束时每三秒更新分析进度。
3. 在**评论**页面查看已保存数据，可按商品、分析状态和问题判断筛选。点击记录查看证据、分析来源和回退原因；点击刷新获取最新分析结果。
4. 在**问题组**页面查看数量和证据。组员提供写接口前，**人工复核**页面只读。AI 建议不计为人工已接受。

CSV 必填列为 `shop_id,product_id,body`，可选列为 `source_review_id,review_date,rating`。最多 5,000 行，正文最多 2,000 字符；页面限制单个文件最多 10 MB。10 条样本包含在 60 条样本内，使用相同平台重复导入时，已有评论应被去重。

批次回执保存在本浏览器（最近 20 条），当前后端没有批次列表接口。清理浏览器记录或换浏览器后列表会为空，但数据库数据仍在。可输入已知批次编号查询；评论与问题列表始终读取数据库。完整项目与期中 Demo 等不同运行环境使用各自的数据库。

```powershell
.\scripts\start_product_ui.ps1 -Action status
.\scripts\start_product_ui.ps1 -Action stop
node --test tests/frontend/api.test.cjs
```

停止不会删除数据库卷。macOS/Linux 首次从 `.env.example` 创建 `.env`，然后执行 `docker compose up -d --build --wait`。如果修改了 API_HOST_PORT，请使用对应端口。

`api.js` 集中处理 HTTP 接口；`live.js` 负责路由、表单和展示；`live.css` 补充原样式。原有 `app.js` 和 `mock-data.js` 保留，通过 `/ui/mock.html` 查看原静态设计。双语期中 Demo 仍单独运行。人工写操作和语义归组等待后端补齐。本次前端接入沿用现有分析流程，不额外调用模型。
