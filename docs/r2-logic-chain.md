# 从评论导入到结果保存：R2 的运行逻辑

本文中的函数都用“文件名.函数名”标注。为区分几个同名的 main.py，接入服务写作 `api/main.py`，后台入口写作 `worker/main.py`，分析服务写作 `ai/main.py`。它们分别位于 `services/api/app/`、`services/worker/app/` 和 `services/ai/app/`。文中的 `jobs.py`、`analysis.py` 和 `policy.py` 都位于 `services/worker/app/`。

下面以“这个背包的拉链拉到一半就卡住了”这条评论，说明当前代码怎样完成一次处理。

## 1. R1 导入评论，为 R2 准备分析任务

用户提交 CSV 后，请求首先进入 `api/main.py.create_batch()`。这个函数负责接收一次导入，创建批次记录，再把 CSV 内容交给 `ingestion.py.parse_csv()` 解析。这里的 `ingestion.py` 位于 `services/api/app/`。

`ingestion.py.parse_csv()` 检查表头、读取每一行，并通过 `ingestion.py._build_comment()` 检查商品编号、店铺编号、正文等字段。检查通过的评论会被整理成可入库的数据，错误行则留下原因。

随后，`api/main.py.create_batch()` 把有效评论交给 `ingestion.py.ingest_comments()`。这个函数先判断评论是否已经存在：新评论会被保存，完全重复的评论不会重复创建；如果已有评论的正文发生变化，则更新正文并留下版本记录。

保存评论时，`ingestion.py.ingest_comments()` 还会调用 `ingestion.py._ensure_job()`，确保评论有一张待处理的分析工作单。它通过 `ingestion.py._active_job()` 检查同一评论是否已经有排队或处理中的任务；如果没有，就创建一个新的 Job。

最后，`api/main.py.create_batch()` 将批次、评论、任务和错误记录一起提交到数据库，再返回导入结果。到这里，评论已经存好，评论状态是 `queued`，任务状态是 `pending`，但 AI 还没有开始分析。

**R1 给 R2 准备的是两样东西：Comment 保存“要分析的评论”，Job 表示“需要分析这条评论”。**

## 2. R2 发现任务，领取这一条评论的工作单

后台程序从 `worker/main.py.run_worker()` 开始运行。它会持续调用 `worker/main.py.run_once()`，一轮一轮地检查有没有工作需要处理。

每一轮开始时，`worker/main.py.run_once()` 先通过 `worker/main.py.recover_stale_jobs()` 调用 `jobs.py.recover_stale_jobs()`，检查之前是否有处理超时、需要回收的任务。随后，`metrics.py.update_queue_metrics()` 更新任务数量等运行指标，然后才进入领取步骤。

领取入口是 `worker/main.py.claim_next_pending_job()`，实际规则在它调用的 `jobs.py.claim_next_pending_job()` 中。后者从数据库中寻找状态为 `pending`、已经到达允许执行时间、而且尝试次数还没用尽的任务，并使用数据库锁避免其他 Worker 同时领取它。

领到我们的背包评论后，`jobs.py.claim_next_pending_job()` 把 Job 从 `pending` 改为 `claimed`，把评论从 `queued` 改为 `analyzing`，同时增加一次尝试次数，写入领取时间和到期时间。

这些变化保存成功后，它返回一份 JobClaim。JobClaim 不只是任务编号，还带着本次领取的时间和次数。后面处理结果时，R2 会用它证明“我仍然拥有这一次任务”。

接着，`worker/main.py.run_once()` 将这份凭据交给 `worker/main.py.process_job(claim)`，开始处理这一条评论。如果本轮没有领到任务，外层程序就等待一段时间，再检查下一轮。

## 3. R2 读取本次正文，再把材料交给 R3

`worker/main.py.process_job(claim)` 是单条任务的协调者。它先调用 `jobs.py.load_input_for_claim()`，准备本次分析需要的材料。

`jobs.py.load_input_for_claim()` 首先调用 `jobs.py.lock_owned_job()`，确认任务仍处于本次领取之下，而且还没有过期。如果任务已经被回收或重新分配，本次执行就停止，不再调用 AI。

确认可以继续后，`jobs.py.load_input_for_claim()` 调用 `analysis.py.load_analysis_input()`。这个函数读取评论正文、商品和来源信息，同时计算正文哈希、读取版本标记，形成一份固定的 AnalysisInput。

固定这份输入，是为了记住“本次送给 AI 的到底是哪一版评论”。后面即使数据库正文更新了，也不能把旧正文的分析结果当作新正文的结果。

读取结束后，数据库会话关闭并释放锁。然后，`worker/main.py.process_job(claim)` 调用 `analysis.py.call_ai_service()`，将这份固定输入中的评论编号、商品编号和正文发送给 R3 的 `/extract-issues` 接口。

对端由 `ai/main.py.extract()` 接收请求，再调用 `ai/main.py.extract_issues()` 分析评论。当前代码使用关键词规则，通过 `ai/main.py._find_evidence()` 找到原文片段，返回是否有问题、问题类别、描述和证据。

因此，这一步的分工是：**R2 负责把材料正确送出去，R3 负责给出分析内容。** 后续 R3 换成大模型时，只要保持接口格式，R2 仍可沿用这条处理链。

## 4. R2 检查回复，确认结果能否使用

收到 R3 的回复后，`analysis.py.call_ai_service()` 检查 HTTP 是否成功、能否解析 JSON，再把原始结果和调用耗时返回给 `worker/main.py.process_job(claim)`。

接下来，`worker/main.py.process_job(claim)` 先调用 `analysis.py.validate_ai_result()`。这个函数检查返回格式、评论编号、版本和类别是否符合约定，避免把其他评论的结果或不合格的数据继续保存。

格式检查通过后，再调用 `analysis.py.verify_evidence()`，在本次固定的正文中查找每一段原文证据。例如，模型说问题是“拉链卡顿”，引用的“拉链拉到一半就卡住了”必须确实出现在这条评论中。

找到证据，就记录它在正文中的位置；找不到，就丢弃对应问题并将判断降为 `unknown`，其他证据有效的问题仍可保留。最后，这个函数将检查后的内容整理成 VerifiedAnalysis，交给保存阶段。

这里需要区分：“没有发现问题”和“无法判断”都可以是有效的分析结果，不一定表示程序失败；调用超时、返回格式错误等，才会转入异常处理。

## 5. R2 再检查一次，然后把结果完整保存

取得检查后的结果，`worker/main.py.process_job(claim)` 会调用 `jobs.py.complete_job()`，准备写入数据库。

`jobs.py.complete_job()` 并不会直接保存。它先再次调用 `jobs.py.lock_owned_job()`，检查原来的 JobClaim 是否仍然有效；再调用 `analysis.py.load_analysis_input()`，读取当前正文，与之前送给 AI 的 AnalysisInput 比较。

这两次检查是因为：等待 AI 回复期间，任务可能已经交给别人，评论正文也可能已经更新。只有确认任务归属和输入都仍然匹配，结果才能成为当前结果。

检查通过后，`jobs.py.complete_job()` 调用 `jobs.py._record_run()` 创建 AnalysisRun，记录本次输入哈希、分析输出、模型版本和耗时等。随后，它调用 `jobs.py.save_issue_links()`，保存问题组及评论关联。

`jobs.py.save_issue_links()` 先通过 `jobs.py._group_lock()`，让同一范围内的并发建组按顺序进行，再通过 `jobs.py._supersede_suggestions()` 标记未人工处理的旧 AI 建议失效。接着，它查询同平台、同店铺、同商品、同类别的有效问题组：找到就复用，没有就创建候选组，并保存评论与问题组之间的原文证据。

**当前归组仍是类别基线，没有比较问题描述的语义，也没有调用分组建议接口。** 后续 R3 可以改进归组判断，R2 继续负责安全保存。

如果已有的评论关联被人工接受、拒绝、手动建立，或者已经有人工决定信息，`jobs.py.save_issue_links()` 会保留这些决定和证据；AI 只能更新尚待人工处理的建议。

这些内容准备好后，`jobs.py.complete_job()` 将评论改为 `analyzed`，保存最终判断，将 Job 改为 `completed`，再通过 `jobs.py._clear_claim()` 清理领取信息，最后统一提交数据库。

**分析记录、问题组、证据、评论结果和任务完成状态一起提交。** 如果保存中途出错，就回滚这组修改，避免出现“任务显示成功，但结果只保存了一半”。

## 6. R4 通过查询接口看到保存结果

结果保存后，前端可以通过 `api/main.py.read_comment()` 查询评论和分析记录，通过 `api/main.py.read_issue()` 查询问题组及原文证据，通过 `api/main.py.read_job()` 查询任务状态。

批次进度则由 `api/main.py.read_batch_progress()` 调用 `api/main.py._batch_progress()` 汇总得到，R2 不再另外维护一份批次完成计数。

因此，R2 与 R4 的连接方式是：**R2 把结果存进数据库，查询接口把结果交给页面，再由人工查看、确认和跟进。** 原项目前端连接真实数据仍属于 R4 的工作；AI 不会自动把问题确认或标记为已解决。

## 7. 如果调用失败，R2 怎样回到这条正常链

假设等待 R3 时发生超时，异常会回到 `worker/main.py.process_job(claim)`。它先调用 `policy.py.classify_error()`，把异常整理成错误码、是否可重试和安全错误摘要，再把这些信息交给 `jobs.py.handle_job_failure()`。

`jobs.py.handle_job_failure()` 先通过 `jobs.py.lock_owned_job()` 检查本次领取是否仍有效，再读取当前评论。如果有本次固定输入，它会通过 `jobs.py._record_run()` 记录这次失败。

如果正文没有变化，`jobs.py.handle_job_failure()` 就调用 `policy.py.should_retry()`，判断错误是否适合重试、次数是否还够。允许重试时，再调用 `policy.py.calculate_retry_delay()` 计算等待时间，把 Job 放回 `pending`、评论放回 `queued`，并写入下一次允许执行的时间。

Worker 随后可以处理其他任务。到了时间，`jobs.py.claim_next_pending_job()` 会再次领取这张工作单，重新进入读取正文、调用 AI、校验和保存的正常链条。重试不需要另一套分析流程。

如果已经达到次数上限，或错误本身不适合重试，`jobs.py.handle_job_failure()` 就把任务和评论保存为最终失败。默认最多尝试三次，包括首次执行；次数只在真正领取时增加。

例如第一次超时、第二次成功，数据库会保留第一次失败和第二次成功的两条 AnalysisRun，而 Job 最终仍是 `completed`。**一次调用失败，不等于整张工作单最终失败。**

如果数据库也不可用，连失败记录都写不进去，`worker/main.py.process_job(claim)` 会留下简短日志并结束本次尝试，后续依靠任务到期回收；这种情况下不能保证留下完整的分析记录。

## 8. 如果 Worker 中断，任务怎样继续

程序被强制关闭时，可能来不及进入上述失败处理，任务会停留在 `claimed`。

后续 Worker 运行到 `worker/main.py.run_once()` 时，会通过回收入口调用 `jobs.py.recover_stale_jobs()`。这个函数检查已到期的任务：仍有尝试次数就重新排队，没有次数就标记最终失败，同时同步评论状态并清除旧领取信息。回收本身不增加尝试次数。

重新领取后，任务会获得新的 JobClaim。如果旧 Worker 之后才返回，它持有的领取时间和次数已经失效，`jobs.py.lock_owned_job()` 会拦住它，拒绝其成功或失败写入。

所以，回收与归属检查共同完成一件事：**让未完成的任务继续执行，同时防止旧执行覆盖新执行的结果。**

## 9. 如果处理中正文更新，旧结果怎样处理

还有一种情况：送给 AI 的是“拉链卡住”，等待期间 R1 把正文更新成了“整体很好”。

`jobs.py.complete_job()` 或 `jobs.py.handle_job_failure()` 重新读取当前输入时，会发现它与原来的 AnalysisInput 不同，于是调用 `jobs.py._requeue_changed_input()`。

这个函数不会把旧分析设置为新正文的当前结果，而是把任务重新放回 `pending`，清除旧领取信息，将评论改回 `queued`，并清除旧的当前判断。因为输入材料已经变了，它还会重置尝试次数，让新材料获得自己的处理预算。

同时，`jobs.py._requeue_changed_input()` 会使未人工处理的旧 AI 建议失效，人工决定仍然保留。之后，下一轮 Worker 再读取新正文并分析。

如果正文更新后 Worker 又中断，`jobs.py.recover_stale_jobs()` 也会识别 R1 留下的“新正文等待分析”状态，为它重新排队。

---

这条链中，**main.py 把步骤串起来，analysis.py 负责取得并核对分析回复，policy.py 提供失败处理规则，jobs.py 将结果和决定安全地保存到数据库。**

正常情况一路保存成功；临时失败回到队列重试；中断由过期回收接手；正文变化则按新材料重新分析。所有路径都围绕同一张工作单展开，并通过领取凭据、固定输入和人工判断保护，避免把旧执行或 AI 建议错误地覆盖到当前数据上。
