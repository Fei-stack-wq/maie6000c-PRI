# Product workbench / 产品工作台

## English

Start Docker Desktop, run `.\scripts\start_product_ui.ps1`, then open
<http://localhost:8000/ui/>. The top-right selector switches Chinese/English and remembers the choice.
Switching reloads the current route; unsaved form entries receive a confirmation prompt.
Review text, evidence, titles and human notes retain their original language.

The upload page offers the CSV template and Chinese (50 reviews) / English (60 reviews)
test downloads. Files are bundled under `test-data/`; downloading does not import them.
See [sample sources](test-data/README.txt) for provenance and test identifiers.

| Page | Use |
| --- | --- |
| `#/batches` | Upload CSV, inspect progress, stop unfinished work, trash or permanently delete a batch |
| `#/batches?trash=1` | Restore or permanently delete a trashed batch |
| `#/comments` | Select batches/products, inspect analysis and category tags, open full text |
| `#/issues` | Batch → product → category; grouped entries above pending entries |
| `#/reviews` | Evidence decisions, corrections, manual additions, issue follow-up and merge/split |
| `#/about` | Project and documentation links |

Batch and product pickers support multiple selection, search and all. Product choices follow the
selected batches and include complete catalog pages, not only products in the current results page.
Products are distinguished by platform/store/product. Filters survive refresh and review return links.

The board pages whole products. Load more expands a category lane. Colour labels identify the five
categories; a multi-issue review can show several labels. Confirm assignment moves a pending entry
to the grouped section. Review / reassign also works for automatically grouped entries.

The UI uses plain HTML/CSS/JavaScript and same-origin APIs. No frontend build or external CDN is required.

| Module | Responsibility |
| --- | --- |
| `api-client.js`, `auth-ui.js` | Session/CSRF requests, login/roles, empty DELETE responses |
| `product-routes.js` | Refreshable routes and scope filters |
| `scope-filter.js`, `workbench-ui.js` | Complete catalogs, dependent selection and bilingual helpers |
| `scope-pages.js`, `scope.css` | Comment cards and the hierarchical issue board |
| `batch-pages.js`, `batch-actions.js` | Upload/progress, stop, recycle/restore/purge and imported records |
| Existing review modules | Audited decisions, corrections, manual evidence and issue actions |
| `i18n.js`, `i18n-en.js` | Existing UI translation; dynamic review content is never scanned for translation |

Run `node --test tests/frontend/*.cjs` for the frontend checks.
`/ui/legacy/` and `/ui/previous/` remain archived; the port-18717 midterm demo remains separate.

## 中文

启动 Docker Desktop，运行 `.\scripts\start_product_ui.ps1`，打开 <http://localhost:8000/ui/>。
右上角切换中英文并记住选择。切换会刷新当前页面，未保存表单内容会提示确认。
评论、证据、问题标题和人工备注保留原语言。

上传页提供 CSV 示例、中文50条和英文60条测试集下载。文件随项目保存在 `test-data/`，
下载不会自动导入；来源和测试编号说明见[样本说明](test-data/README.txt)。

| 页面 | 用途 |
| --- | --- |
| `#/batches` | CSV 上传、进度、停止剩余分析、回收或永久删除批次 |
| `#/batches?trash=1` | 恢复或永久删除回收站批次 |
| `#/comments` | 选择批次和商品，查看分析、类别标签及完整原文 |
| `#/issues` | 批次 → 商品 → 类别；上方已归组，下方待确认 |
| `#/reviews` | 证据判断、纠错、人工补充、问题跟进及合并／拆分 |
| `#/about` | 项目与文档入口 |

批次和商品选择器支持搜索、多选、全部，商品随批次联动，完整读取选项分页，不只取当前结果页。
商品以平台、店铺和商品编号共同区分。刷新和从人工复核返回时保留筛选。

问题看板按完整商品分页，类别内可以加载更多；五类使用颜色标签，多问题评论可显示多个标签。
确认归组后内容移到上方，自动归组内容也可以通过“核对／调整归组”纠错。

前端使用原生 HTML、CSS、JavaScript 和同源 API，无构建步骤或外部 CDN。
`api-client.js`、`auth-ui.js` 管理请求和身份；`product-routes.js` 管理路由；
`scope-filter.js`、`workbench-ui.js` 管理完整选项及联动；`scope-pages.js`、`scope.css` 提供评论和分层看板；
`batch-pages.js`、`batch-actions.js` 提供上传、进度及批次操作。原复核模块继续处理审计、人工证据及问题跟进，
`i18n.js`、`i18n-en.js` 继续提供界面翻译，不扫描或改写业务正文。

运行 `node --test tests/frontend/*.cjs` 验证前端。
`/ui/legacy/`、`/ui/previous/` 保留为历史预览，18717 端口的期中 Demo 仍独立运行。
