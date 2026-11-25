# Integrated workbench / 整合工作台

## English

Start Docker Desktop, then run from the repository root:

```powershell
.\scripts\start_product_ui.ps1
```

Open <http://localhost:8000/ui/>. The script keeps an existing `.env`, builds the services and applies migrations through `20261121_0006`. The first AI build installs a CPU sentence model and downloads its weights, so it takes longer than a rule-only build. Keep Docker Desktop running.

The default entry loads `api-client.js`, the session controls, product routes and the team's modular batch/comment/review/issue pages. It does not load the old `api.js`/`live.js` pair. Both previous versions remain archived, not mixed into the active router.

1. Upload the 10-row CSV with platform `amazon_sample`, inspect progress and row errors.
2. Open Comments; filter and paginate. Comment details include original evidence, model/rule source, model attempts and fallback reason.
3. Open Human review to accept/reject suggestions, reassign or recheck evidence, or manually add an issue to a missed review.
4. Open Issue groups to confirm/dismiss, add follow-up notes, resolve/reopen, merge or split. Evidence acceptance and issue resolution are distinct operations.

The API supplies identity and version tokens. If another user/Worker changes the record, reload current evidence before resubmitting; do not force an outdated decision. Session mode uses reviewer/viewer accounts; demo mode clearly labels its non-login identity and still writes real data.

Lists are loaded from the server, including batches. Refresh and deep links preserve their filters. Old completed reviews do not automatically acquire new semantic grouping. The first 10-row sample is included in the 60-row sample, so consistent reimports deduplicate.

Frontend checks: `node --test tests/frontend/*.cjs`. The old adapter tests cover the archived read-only client; the routing/upload tests cover the active workbench. Full API and concurrent-write tests run with pytest; see Operations.

## 中文

先启动 Docker Desktop，在仓库根目录运行：

```powershell
.\scripts\start_product_ui.ps1
```

打开 <http://localhost:8000/ui/>。脚本保留已有 `.env`，构建服务并迁移数据库到 `20261121_0006`。首次构建 AI 服务需要安装 CPU 语义模型并下载权重，会比纯规则版更久。运行时保持 Docker Desktop 开启。

默认入口加载 `api-client.js`、身份控件、产品路由和组员拆分的批次／评论／复核／问题页面，不再加载旧的 `api.js`／`live.js`。旧版本已归档，不混入当前路由。

1. 使用 `amazon_sample` 平台上传 10 条 CSV，查看进度和错误行。
2. 打开评论列表进行筛选、分页。详情展示原文证据、模型／规则来源、模型尝试次数和回退原因。
3. 在人工复核中接受／拒绝建议、改归组、重核证据，或为漏识别评论人工补充问题。
4. 在问题组中确认／忽略、填写跟进备注、解决／重开、合并或拆分。接受证据与解决问题是不同操作。

身份与版本凭据由后端提供。其他成员或后台修改记录后，应重新加载最新证据再提交，不强行覆盖旧版本。会话模式使用复核员／只读成员账号；演示模式明确标记非登录身份，操作仍真实写库。

包括批次在内的列表均读取服务器。刷新和详情跳转保留筛选。已完成旧评论不会自动获得新语义归组。10 条样本包含在 60 条样本中，平台一致时重复导入会去重。

前端检查：`node --test tests/frontend/*.cjs`。旧适配器测试覆盖归档只读客户端，路由／上传测试覆盖当前工作台。完整 API 和并发写入测试通过 pytest 执行，见运行说明。
