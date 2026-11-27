# Module Boundaries / 模块边界

## English

The project has four cooperating areas. Their current behaviour is described in
[Architecture](architecture.md) and [Progress](progress.md).

| Area | Responsibility | Main files |
| --- | --- | --- |
| R1: data and ingestion | Validate reviews, deduplicate, record revisions, create jobs and expose queries | `services/api/app/`, `services/common/`, `alembic/` |
| R2: background processing | Claim and recover jobs, call analysis, validate evidence, save results and retry failures | `services/worker/app/` |
| R3: analysis | Extract issue categories and original evidence; improve analysis and grouping quality | `services/ai/app/` |
| R4: product interface and review | Display reviews/issues and support human review and follow-up | `frontend/`, `services/api/app/reviews/`, `services/api/app/auth/` |

R1 creates pending work. R2 sends a fixed review snapshot to R3 over HTTP and saves the validated
response. Query APIs expose the saved result. The midterm interface reads real stored results;
the product frontend now uses the same live API for upload, comments, issue groups and review. Current grouping is category-based, and
AI suggestions do not confirm or resolve issues automatically.

Request/response definitions are in `services/common/schemas.py`; data models are in
`services/common/models.py`. R2 preserves existing human decisions when reprocessing reviews.
Human-review endpoints enforce role checks, freshness tokens, ordered locks and idempotent audit receipts.

These are module boundaries, not fixed personal assignments. Contributors continue from the latest agreed
branch according to availability. See [human review](human-review.md) for the completed local scope.

## 中文

项目由四个协作模块组成，当前行为见[系统架构](architecture.md)和[项目进度](progress.md)。

| 模块 | 职责 | 主要文件 |
| --- | --- | --- |
| R1 数据与接入 | 校验评论、去重、记录版本、创建任务和提供查询 | `services/api/app/`、`services/common/`、`alembic/` |
| R2 后台处理 | 领取和回收任务、调用分析、核对证据、保存结果和失败重试 | `services/worker/app/` |
| R3 分析 | 提取问题类别和原文证据，改进分析与归组质量 | `services/ai/app/` |
| R4 产品界面与复核 | 展示评论／问题，支持人工复核及跟进 | `frontend/`、`services/api/app/reviews/`、`services/api/app/auth/` |

R1 创建等待任务，R2 通过 HTTP 将固定评论输入交给 R3，检查回复后保存，查询接口提供已保存结果。
期中界面读取真实保存的数据；产品前端的上传、评论、问题组及复核也已接入同一套真实 API。当前按类别归组，AI 建议不会自动确认或解决问题。

输入输出定义位于 `services/common/schemas.py`，数据模型位于 `services/common/models.py`。
R2 重跑时保留已有人工决定；人工复核接口通过角色权限、版本 token、有序锁与幂等审计回执处理并发更新。

这里描述模块边界，不是固定的个人分工；成员按时间安排，从团队约定的最新分支继续工作。
本地已完成范围见[人工复核说明](human-review.md)。
