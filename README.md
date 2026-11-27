# Product Review Analysis & Issue Discovery / 商品评论分析与问题发现

## English

### Run the product

Start Docker Desktop, then run from the repository root:

```powershell
.\scripts\start_product_ui.ps1
```

Open <http://localhost:8000/ui/>; switch Chinese/English at the top right. The script keeps an existing `.env`, builds the services and applies migrations through `20261126_0010`. The first AI build installs a CPU sentence model and downloads its weights, so it takes longer than a rule-only build. Keep Docker Desktop running.

Upload a UTF-8 review CSV, follow the batch progress, inspect comments and issue evidence, then accept/reject associations and follow up issues. Review decisions, notes and history are saved in PostgreSQL. Accepting an association does not automatically confirm or resolve its issue.

| Part | Integrated implementation |
| --- | --- |
| Input | CSV/JSON validation, independent batch snapshots, request deduplication and row errors |
| Worker | Claims, bounded job retries, expired-claim recovery, evidence checks and protected saves |
| Analysis | Hosted model extraction (up to three attempts), marked rule fallback, local MiniLM semantic grouping |
| Workbench | Upload/progress, stop, trash/restore/purge, batch/product multi-select, category board and audited review |
| Identity | Explicit local demo identity or named reviewer/viewer sessions |

Local defaults use demo identity and write real data. Named accounts and deployment settings are documented in [human review](docs/human-review.md). Production identity requires session mode and HTTPS.

The model Key remains in ignored local `.env`. Semantic grouping uses a separate local model and needs no additional provider Key. Missing model configuration uses rules immediately; configured model failures receive at most two retries before rule fallback. These are separate from Worker job retries.

Each deliberate upload has independent reviews, jobs and groups; the same request key protects network retries. Use batch/product pickers to select one, several or all scopes. The board lists batch → product → category, with grouped entries above pending entries. Clear model results may be automatically assigned; human corrections remain protected. Older output without confidence stays pending. The extractor permits at most one issue per category per review.

Stop keeps completed analyses and cancels unfinished records. Trash hides only the selected batch; restore does not resume work, and permanent deletion cannot be undone. Startup repairs unreviewed historical grouping locally without model calls and marks unrecoverable old batch records.

### Documentation and previews

- [Operations](docs/operations.md): configuration, startup, identity, monitoring and tests.
- [Architecture](docs/architecture.md): data flow and AI Integration Card.
- [Human review](docs/human-review.md): decisions, evidence, concurrency and workflow contracts.
- [Frontend](frontend/README.md): routes and using the integrated workbench.
- [Progress](docs/progress.md): integrated state and verification scope.
- [Week 07 record](templates/submissions/week07/README.md): historical midterm material.

The original static design is retained at `/ui/legacy/`; `/ui/mock.html` forwards there. The previous read-only frontend is archived at `/ui/previous/`. Only the integrated workbench is the default entry.

The separate bilingual midterm demo remains available via ` .\scripts\start_midterm_demo.ps1 ` at <http://localhost:18717/en> and <http://localhost:18717/zh>, using its own database.

### AI use

We used ChatGPT to improve and polish the documentation and to assist with code scaffolding and testing.

## 中文

### 运行产品

先启动 Docker Desktop，在仓库根目录运行：

```powershell
.\scripts\start_product_ui.ps1
```

打开 <http://localhost:8000/ui/>，右上角切换中英文。脚本保留已有 `.env`，构建服务并迁移数据库到 `20261126_0010`。首次构建 AI 服务需要安装 CPU 语义模型并下载权重，会比纯规则版更久。运行时保持 Docker Desktop 开启。

上传 UTF-8 评论 CSV，查看批次进度、评论和问题证据，再接受／拒绝关联并跟进问题。复核决定、备注和历史保存在 PostgreSQL。接受关联不自动确认或解决整个问题组。

| 部分 | 整合后的实现 |
| --- | --- |
| 接入 | CSV／JSON 校验、独立批次快照、请求去重与错误行 |
| Worker | 领取、有限任务重试、过期回收、证据检查及受保护保存 |
| 分析 | 外部大模型提取（最多三次尝试）、明确标记的规则回退、本地 MiniLM 语义归组 |
| 工作台 | 上传与进度、停止、回收／恢复／删除、批次商品多选、分类看板与人工复核 |
| 身份 | 明确的本地演示身份，或具名复核员／只读成员会话 |

本地默认使用演示身份，操作会写入真实数据库。具名账号及部署配置见[人工复核说明](docs/human-review.md)。正式身份使用会话模式和 HTTPS。

模型 Key 仍保存在已忽略的本地 `.env`。语义归组使用独立本地模型，不需要额外的外部 Key。缺少模型配置时立即使用规则；模型已配置但处理失败时，最多重试两次后回退规则。这与 Worker 的任务重试分开计数。

每次主动上传分别保存评论、任务和问题组，相同请求编号用于防止网络重试重复导入。通过批次／商品选择器查看单个、多个或全部范围。看板按批次 → 商品 → 类别展示，上方已归组、下方待确认。明确的模型结果可自动归组，人工纠错受到保护；旧输出缺少置信度时仍待确认。每条评论每个类别目前最多提取一个问题。

停止保留完成结果并取消未完成记录；回收站仅隐藏所选批次，恢复不继续任务，永久删除不可撤销。启动时用已保存输出在本地整理未人工处理的旧归组，不调用模型，并标明无法还原的旧批次记录。

### 文档与预览

- [运行说明](docs/operations.md)：配置、启动、身份、监控和测试。
- [系统架构](docs/architecture.md)：数据流与 AI 接入卡片。
- [人工复核](docs/human-review.md)：决定、证据、并发与流程契约。
- [前端说明](frontend/README.md)：整合工作台的页面和用法。
- [开发进度](docs/progress.md)：整合状态与验证范围。
- [Week 07 记录](templates/submissions/week07/README.md)：历史期中材料。

原静态设计保留在 `/ui/legacy/`，`/ui/mock.html` 跳转至该预览。上次只读前端归档在 `/ui/previous/`。默认入口只运行整合工作台。

独立双语期中 Demo 仍通过 ` .\scripts\start_midterm_demo.ps1 ` 启动，地址为 <http://localhost:18717/en> 和 <http://localhost:18717/zh>，使用独立数据库。

### AI 使用说明

我们使用 ChatGPT 完善和润色文档说明，并辅助进行代码框架构造和测试。
