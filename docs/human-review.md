# Review workflow / 人工复核流程

## English

### Read the board

Open `/ui/#/issues`. Select one, several or all batches, then choose products from that scope.
Each batch has its own product sections. Each product shows the five categories in a fixed order:
Quality, Delivery, Not as described, User experience, Other.

Within a category, **Grouped** appears first and **Needs human confirmation** follows.
Entries show their specific issue title, review text, original evidence and operation links.
A review mentioning multiple categories can appear in each relevant section with its own evidence.

| Label | Meaning |
| --- | --- |
| AI auto-confirmed | The model and local evidence/category/grouping checks passed the automatic rule |
| Human confirmed | A person accepted the association |
| Human assigned | A person manually created or moved the association |
| Needs human confirmation | The assignment is uncertain, came from fallback, or needs evidence rechecking |

Automatic assignment is not a claim that a defect or root cause has been proved. Issue follow-up
has its own proposed/confirmed/resolved/dismissed states.

### Confirm and correct

- Check the quoted evidence against the full review before clicking Confirm assignment.
- Review / reassign opens the existing workbench. Accept/reject, revise decisions, or move an
  association to another active group within the same batch/platform/store/product.
- Either automatic or human-accepted entries can be corrected. A rejected source association and
  accepted destination retain both histories. Cross-category correction is allowed; cross-batch movement is blocked.
- Use manual addition for a missed issue, with an exact quote and a required reason. `unknown`
  and failed analyses can still be checked manually where the workflow allows it.
- Merge/split reorganizes groups within the same batch/product scope. It preserves evidence and
  prior decisions, and returns affected issue follow-up to proposed for a fresh check.

Human operations retain operator, reason, evidence, versions and request receipts. Stale submissions
are rejected instead of silently overwriting another person's work. Retry an unconfirmed submission
only after checking the latest state. Worker reruns preserve human choices.

### Batch operations and source history

Each upload creates independent comment snapshots. Uploading a changed source again does not
invalidate a previous batch's accepted evidence. If a stored occurrence is corrected through an
internal maintenance process, its revision/evidence checks still detect the change and require rechecking.

Stopping a batch keeps completed analyses and cancels the rest. Trashing hides that batch;
restoring preserves its history without resuming work. Permanent deletion removes that batch's
review/audit content too, so use it only when those records are no longer needed.

Old imports may have missing batch occurrences due to the former global deduplication rule.
They are marked instead of being reconstructed from newer text. Automatic legacy repair never
rewrites groups with human decisions or audit history. Older model results without confidence stay pending.

### Roles and verification

Local demo identity writes real records. Session mode supports reviewer and viewer roles,
revocable sessions and CSRF checks. There is no public account registration. See [operations](operations.md).

The workflow tests cover evidence validation, stale requests, idempotency, human override,
reassignment, manual evidence, issue actions, merge/split, batch boundaries and PostgreSQL concurrency.
Use a separate test database for deletion and stop checks.

## 中文

### 查看问题看板

打开 `/ui/#/issues`，选择一个、多个或全部批次，再从对应范围选择商品。
每个批次分别列出商品，每个商品依次显示五类：质量、物流、描述不符、使用体验、其他。

每类先显示“已归组”，再显示“待人工确认”。记录包含具体问题标题、评论原文、原文证据及操作入口。
一条评论涉及多个类别时，可以分别出现在相关区域，并显示各自证据。

| 标记 | 含义 |
| --- | --- |
| AI 自动确认 | 模型结果与本地证据、类别、归组检查共同满足自动采用规则 |
| 人工已确认 | 工作人员接受了关联 |
| 人工已调整 | 工作人员手工建立或移动了关联 |
| 待人工确认 | 归组不明确、来自备用规则，或需要重新核对证据 |

自动归组不代表缺陷或根因已经得到证实。整个问题的跟进另有待确认、已确认、已处理、已驳回状态。

### 确认与纠错

- 点击“确认归组”前，对照完整评论检查引文。
- “核对／调整归组”进入原有工作台，可以接受、拒绝、修改决定，或移到同批次、同平台、同店铺、同商品的其他活动组。
- AI 自动确认和人工已接受的内容都能纠错；移动时原关联拒绝、目标关联接受，两侧历史保留。允许跨类别，不允许跨批次。
- 人工补充用于发现漏检问题，需要逐字原文证据及原因；工作流允许时也可人工核对 unknown 和失败分析。
- 合并／拆分限定在同批次商品内，保留原有证据和决定，受影响问题的跟进状态回到待确认。

人工操作保存操作者、原因、证据、版本和请求回执；过期页面提交会被拒绝，不静默覆盖他人决定。
提交未确认成功时先核对最新状态，再重试。后台重跑保留人工选择。

### 批次操作与原文历史

每次上传建立独立评论快照，再次上传修改后的来源评论，不会使旧批次的证据失效。
如果通过内部维护修正某个已保存记录，原有版本及证据检查仍能识别变化，并要求重新核对。

停止保留完成结果并取消其余任务；回收站隐藏该批次，恢复保留历史但不继续任务。
永久删除还会清除该批次的复核和审计内容，仅在不再需要这些记录时使用。

旧版全局去重造成缺失的历史批次记录会被标明，不使用较新的正文冒充历史。
旧结果自动整理不改写有人工决定或操作历史的问题组；旧模型没有提供置信度的结果继续待确认。

### 身份与验证

本地演示身份写入真实记录；会话模式提供复核员、只读成员、可撤销会话和 CSRF 检查。
没有公开注册入口，账号管理见[运行说明](operations.md)。

测试覆盖证据、过期提交、幂等、人工纠错、移组、补充、问题跟进、合并／拆分、批次边界及 PostgreSQL 并发。
停止和删除验收使用独立测试数据库。
