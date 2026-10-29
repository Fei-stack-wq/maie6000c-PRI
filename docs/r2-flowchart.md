# R2 Function Flow / R2 函数流程图

## English

Nodes contain file/function names; conditions are written on the edges. Green shows normal
processing, orange retry/failure, purple changed input, and grey adjacent services/queries.
Arrows describe processing order, including HTTP and separate reads, rather than only direct
Python calls. Repeated names mark different call sites. The final `run_once()` means the next poll.
Recovery decisions stay inside `recover_stale_jobs()`; grouping and human-decision protection
stay inside `save_issue_links()`. Current grouping is category-based. The original product UI
is not connected; the midterm demo reads persisted results separately.

[English Mermaid source](r2-flowchart.en.mmd). The saved
[zoomable view](r2-flowchart.html) and [SVG](r2-flowchart.svg) retain the original Chinese labels.

```mermaid
flowchart TB
    A1["api/main.py.create_batch()"] --> A2["ingestion.py.ingest_comments()"]
    A2 --> A3["ingestion.py._ensure_job()"]

    W["worker/main.py.run_worker()"] --> N["worker/main.py.run_once()"]
    N --> REC["jobs.py.recover_stale_jobs()"]
    REC --> MET["metrics.py.update_queue_metrics()"]
    MET --> CLAIM["jobs.py.claim_next_pending_job()"]
    CLAIM -->|"JobClaim returned"| PROC["worker/main.py.process_job()"]
    CLAIM -->|"No job; poll later"| NEXT["worker/main.py.run_once()"]
    PROC --> INPUT["jobs.py.load_input_for_claim()"]
    INPUT --> OWN1{"jobs.py.lock_owned_job()"}
    OWN1 -->|"Valid claim"| SNAP["analysis.py.load_analysis_input()"]
    OWN1 -->|"Stale claim"| NEXT
    SNAP --> CALL["analysis.py.call_ai_service()"]
    CALL --> VALID["analysis.py.validate_ai_result()"]
    VALID --> EVID["analysis.py.verify_evidence()"]
    EVID -->|"Evidence checked"| COMPLETE["jobs.py.complete_job()"]
    COMPLETE --> OWN2{"jobs.py.lock_owned_job()"}
    OWN2 -->|"Valid claim"| CURRENT["analysis.py.load_analysis_input()"]
    OWN2 -->|"Stale; reject write"| NEXT
    CURRENT -->|"Input unchanged"| RECORD["jobs.py._record_run()"]
    RECORD --> SAVE["jobs.py.save_issue_links()"]
    SAVE --> CLEAR["jobs.py._clear_claim()"]
    CLEAR -->|"Committed"| NEXT
    CURRENT -->|"Input changed"| DISCARD["jobs.py._record_run()"]
    DISCARD --> CHANGE["jobs.py._requeue_changed_input()"]
    CHANGE -->|"Queue current input"| NEXT

  A3 -.->|"Pending job persisted"| CLAIM

    AI["ai/main.py.extract()"] --> RULE["ai/main.py.extract_issues()"]
  CALL -.->|"HTTP request"| AI
  RULE -.->|"HTTP response"| VALID

    CLASSIFY["policy.py.classify_error()"] --> HANDLE["jobs.py.handle_job_failure()"]
    HANDLE --> OWN3{"jobs.py.lock_owned_job()"}
    OWN3 -->|"Valid claim"| FAILED_INPUT["analysis.py.load_analysis_input()"]
    FAILED_INPUT -->|"Snapshot available"| FAILED_RUN["jobs.py._record_run()"]
    FAILED_INPUT -->|"No snapshot"| RETRY{"policy.py.should_retry()"}
    FAILED_RUN -->|"Input unchanged"| RETRY
    RETRY -->|"Retry allowed"| DELAY["policy.py.calculate_retry_delay()"]
    DELAY --> CLEAR_RETRY["jobs.py._clear_claim()"]
    RETRY -->|"No retry"| CLEAR_FAILED["jobs.py._clear_claim()"]
  PROC -.->|"Attempt error"| CLASSIFY
  OWN3 -->|"Stale claim"| NEXT
  FAILED_RUN -->|"Input changed"| CHANGE
  CLEAR_RETRY -->|"Wait until due"| NEXT
  CLEAR_FAILED -->|"Final failure"| NEXT
  HANDLE -.->|"Recording failed; recover later"| NEXT

    READ_COMMENT["api/main.py.read_comment()"]
    READ_ISSUE["api/main.py.read_issue()"]
  CLEAR -.->|"Separate read request"| READ_COMMENT
  CLEAR -.->|"Separate read request"| READ_ISSUE

  classDef context fill:#f2f4f6,stroke:#8a959f,color:#29343c;
  classDef normal fill:#edf7f0,stroke:#497b60,color:#173d28;
  classDef failure fill:#fff4e5,stroke:#a4783e,color:#513619;
  classDef changed fill:#f4effb,stroke:#8a6aa6,color:#4c3567;
  class A1,A2,A3,AI,RULE,READ_COMMENT,READ_ISSUE context;
  class W,N,REC,MET,CLAIM,PROC,INPUT,OWN1,SNAP,CALL,VALID,EVID,COMPLETE,OWN2,CURRENT,RECORD,SAVE,CLEAR,NEXT normal;
  class CLASSIFY,HANDLE,OWN3,FAILED_INPUT,FAILED_RUN,RETRY,DELAY,CLEAR_RETRY,CLEAR_FAILED failure;
  class DISCARD,CHANGE changed;

```

## 中文

[打开可缩放流程图](r2-flowchart.html) · [SVG 矢量图](r2-flowchart.svg)

![R2 整体运行流程图](r2-flowchart.svg)

节点中只显示“代码文件 + 函数名”，条件和状态变化放在连线上。

- 绿色：R2 正常处理；橙色：失败与重试；紫色：正文变化；灰色：R1、R3 和查询接口。
- 箭头表示运行链路，不表示每条边都是直接的 Python 调用。HTTP、查询与回到外层循环均已在边上注明。
- 同名函数在不同位置重复出现，表示不同调用时点，不是多份实现。
- 为便于看清业务主线，省略了配置、日志、数据库会话等基础代码，以及只转发调用的两个 main 包装函数。
- 任务过期与次数用尽的回收决策位于 jobs.py.recover_stale_jobs() 内部；分组锁、旧建议失效标记和人工结论保护位于 jobs.py.save_issue_links() 内部。
- 类别归组仍为当前基线；图中不表示已经完成语义归组或原项目的前端接入。

最下方的 `worker/main.py.run_once()` 表示回到下一轮，省略跨越全图的回线。

```mermaid
flowchart TB
    A1["api/main.py.create_batch()"] --> A2["ingestion.py.ingest_comments()"]
    A2 --> A3["ingestion.py._ensure_job()"]

    W["worker/main.py.run_worker()"] --> N["worker/main.py.run_once()"]
    N --> REC["jobs.py.recover_stale_jobs()"]
    REC --> MET["metrics.py.update_queue_metrics()"]
    MET --> CLAIM["jobs.py.claim_next_pending_job()"]
    CLAIM -->|"领到 JobClaim"| PROC["worker/main.py.process_job()"]
    CLAIM -->|"无任务，等待后继续"| NEXT["worker/main.py.run_once()"]
    PROC --> INPUT["jobs.py.load_input_for_claim()"]
    INPUT --> OWN1{"jobs.py.lock_owned_job()"}
    OWN1 -->|"领取有效"| SNAP["analysis.py.load_analysis_input()"]
    OWN1 -->|"领取失效"| NEXT
    SNAP --> CALL["analysis.py.call_ai_service()"]
    CALL --> VALID["analysis.py.validate_ai_result()"]
    VALID --> EVID["analysis.py.verify_evidence()"]
    EVID -->|"证据校验完成"| COMPLETE["jobs.py.complete_job()"]
    COMPLETE --> OWN2{"jobs.py.lock_owned_job()"}
    OWN2 -->|"领取有效"| CURRENT["analysis.py.load_analysis_input()"]
    OWN2 -->|"旧执行，拒绝写入"| NEXT
    CURRENT -->|"输入未变化"| RECORD["jobs.py._record_run()"]
    RECORD --> SAVE["jobs.py.save_issue_links()"]
    SAVE --> CLEAR["jobs.py._clear_claim()"]
    CLEAR -->|"提交成功"| NEXT
    CURRENT -->|"输入已变化"| DISCARD["jobs.py._record_run()"]
    DISCARD --> CHANGE["jobs.py._requeue_changed_input()"]
    CHANGE -->|"新正文重新排队"| NEXT

  A3 -.->|"待处理任务入库"| CLAIM

    AI["ai/main.py.extract()"] --> RULE["ai/main.py.extract_issues()"]
  CALL -.->|"HTTP 分析请求"| AI
  RULE -.->|"HTTP 返回"| VALID

    CLASSIFY["policy.py.classify_error()"] --> HANDLE["jobs.py.handle_job_failure()"]
    HANDLE --> OWN3{"jobs.py.lock_owned_job()"}
    OWN3 -->|"领取有效"| FAILED_INPUT["analysis.py.load_analysis_input()"]
    FAILED_INPUT -->|"有本次输入快照"| FAILED_RUN["jobs.py._record_run()"]
    FAILED_INPUT -->|"无输入快照"| RETRY{"policy.py.should_retry()"}
    FAILED_RUN -->|"输入未变化"| RETRY
    RETRY -->|"允许重试"| DELAY["policy.py.calculate_retry_delay()"]
    DELAY --> CLEAR_RETRY["jobs.py._clear_claim()"]
    RETRY -->|"不可重试"| CLEAR_FAILED["jobs.py._clear_claim()"]
  PROC -.->|"处理异常"| CLASSIFY
  OWN3 -->|"领取失效"| NEXT
  FAILED_RUN -->|"输入已变化"| CHANGE
  CLEAR_RETRY -->|"排队，等待到期"| NEXT
  CLEAR_FAILED -->|"最终失败"| NEXT
  HANDLE -.->|"无法记录，等待回收"| NEXT

    READ_COMMENT["api/main.py.read_comment()"]
    READ_ISSUE["api/main.py.read_issue()"]
  CLEAR -.->|"前端另行查询"| READ_COMMENT
  CLEAR -.->|"前端另行查询"| READ_ISSUE

  classDef context fill:#f2f4f6,stroke:#8a959f,color:#29343c;
  classDef normal fill:#edf7f0,stroke:#497b60,color:#173d28;
  classDef failure fill:#fff4e5,stroke:#a4783e,color:#513619;
  classDef changed fill:#f4effb,stroke:#8a6aa6,color:#4c3567;
  class A1,A2,A3,AI,RULE,READ_COMMENT,READ_ISSUE context;
  class W,N,REC,MET,CLAIM,PROC,INPUT,OWN1,SNAP,CALL,VALID,EVID,COMPLETE,OWN2,CURRENT,RECORD,SAVE,CLEAR,NEXT normal;
  class CLASSIFY,HANDLE,OWN3,FAILED_INPUT,FAILED_RUN,RETRY,DELAY,CLEAR_RETRY,CLEAR_FAILED failure;
  class DISCARD,CHANGE changed;

```
