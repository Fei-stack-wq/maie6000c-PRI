# Week 07 — Midterm Milestone / 期中里程碑

## English

### 1. Project information

- Project: Product Review Analysis & Issue Discovery.
- Team members: FEI, Wenxiang; XIANG, Ke; XU, Chao; ZHANG, Mingyang.
- Repository: <https://github.com/Fei-stack-wq/maie6000c-PRI>.
- Demonstration: review ingestion, background analysis, persisted results and bounded retries.

### 2. What we demonstrate

We submit one product review, persist the comment and analysis job, run a background Worker,
then display the saved category, original evidence and attempt history. We also demonstrate a
temporary service failure followed by successful retry, and repeated failure reaching the limit.
The analysis uses Chinese/English rules. Semantic grouping, LLM analysis and
the complete staff-review workflow remain under development.

**Known analysis limit:** The demo does not recognise all complaints. Warranty refusal and other
after-sales wording can be missed in either language. “No specific issue was identified” records
what the current rules found; it is not a conclusion that the review has no problem. We use this
milestone to demonstrate the running system path. Analysis coverage and quality remain limited.

### 3. Reproduce the demonstration

Download the project, start Docker Desktop and open a terminal at the
repository root. Follow the [run instructions](../../../demo/midterm/README.md).
Windows starts with ` .\scripts\start_midterm_demo.ps1 `; macOS/Linux uses
`docker compose -f compose.midterm.yaml up --build -d --wait`.
Open <http://localhost:18717/en> (Chinese: <http://localhost:18717/zh>).

| Step | Action | Evidence |
| --- | --- | --- |
| Input | Keep the English sample, click **1. Submit review** | Comment and pending job are saved through the ingestion API |
| State change | Observe the saved/waiting state, then click **2. Start analysis** | Job moves from pending to claimed; comment becomes analysing |
| Background step | Wait for the worker | A separate Worker process calls the rule service over HTTP |
| Saved output | Read category, source evidence and attempt history | Result, evidence link and analysis run are stored in PostgreSQL |
| Operational signal | Read attempt counts/history; inspect worker log or metrics | State, retries and worker events are observable |

Start a new round to select **fail once, then retry** (second attempt succeeds) or
**fail until the attempt limit** (three attempts, final failure). These faults are deliberately
injected HTTP 503s; the extra three-second delay makes state changes visible.
Both language pages share one round. Reviews and evidence stay in their original language;
the English page uses an English sample.

### 4. Current implementation and integration

| Area | Working now | Still remaining |
| --- | --- | --- |
| Ingestion | CSV text/JSON validation, errors, deduplication, revisions, jobs and read APIs | Real samples, direct file upload and export improvements |
| Worker | Protected claiming/saving, evidence validation, bounded retry, expiry recovery, changed-input handling and metrics | Manual replay APIs/tools and task-operation audit |
| Analysis | Chinese/English rule extraction and category grouping | LLM, semantic grouping, labelled quality evaluation |
| Product frontend | Five-page layout with mock interactions | Live backend data, human decisions and follow-up persistence |
| Midterm interface | Separate source-buildable demo using the real backend and its own database | No further demo features planned for this milestone |

Compared with the earlier target design, we have made the background path runnable and added
reliability checks and a small presentation interface. The original frontend is kept intact.
The demo is temporary. This milestone covers the working analysis path; the final frontend,
human review and group-management actions remain under development.

### 5. Evidence and verification

- [Verification record](assets/verification.md): test conditions, commands and observed results.
- [Saved-result screenshot, Chinese view](assets/demo-result-zh.jpg): category, verbatim evidence and stored attempt history.
- [Current architecture and data flow](../../../docs/architecture.md).
- [R2 execution chain](../../../docs/r2-logic-chain.md) and [function flowchart](../../../docs/r2-flowchart.md).

Recorded results: 94 unit/integration tests including six PostgreSQL checks; five real HTTP smoke
tests; migration round-trip and normal Worker shutdown; a separate ten-case bilingual demo acceptance.
The isolated demo restart retained five jobs and eight analysis records. R2 statement coverage is
92%, not model accuracy. The result screenshot was captured through the Chinese page.
The later delivery-rule extension passed 78 analysis unit tests and four live demo regressions.
These were separate checks, not a repeat of the complete suite. The developer checked English-page buttons. No general analysis-accuracy result is reported.

### 6. Risks and next work

| Risk or limitation | Next action |
| --- | --- |
| Warranty/after-sales complaints and paraphrases can be missed; false alarms also remain | Keep source text for human checking; add these cases to a labelled evaluation before claiming broader coverage |
| Rule extraction and category grouping are coarse | Add labelled samples, model extraction and semantic-grouping evaluation |
| Original product frontend is not connected | Connect read APIs, then implement reviewed writes and follow-up |
| Demo is a shared, local session | Use one presenter at a time; keep source-run instructions as the reproducible entry |

Work after this milestone: verify platform samples and scope; complete/evaluate analysis and
grouping; connect the product frontend and human review; then repeat integration and regression
checks on the team version. Multi-platform ingestion, training and automated platform actions
remain outside the current scope.

### 7. AI Use Statement

We used ChatGPT to improve and polish the documentation and to assist with code scaffolding and testing.

## 中文

### 1. 项目信息

- 项目：商品评论分析与问题发现。
- 成员：FEI, Wenxiang；XIANG, Ke；XU, Chao；ZHANG, Mingyang。
- 仓库：<https://github.com/Fei-stack-wq/maie6000c-PRI>。
- 演示内容：评论导入、后台分析、结果保存和有限重试。

### 2. 本次展示内容

提交一条商品评论，保存评论和分析任务，由后台 Worker 处理，再展示已保存的类别、原文证据和
尝试记录。同时展示临时服务失败后重试成功，以及持续失败达到上限。
当前分析使用中英文规则，语义归组、大模型分析和完整人工复核流程仍在开发。

**已知分析边界：** Demo 不能识别所有投诉，中英文的拒绝保修等售后表述都可能漏检。
“未发现具体问题”只表示当前规则本次的识别结果，不表示评论确实没有问题。
本次里程碑用于展示可运行的系统流程，分析覆盖和质量仍有局限。

### 3. 复现演示

下载项目，启动 Docker Desktop，在仓库根目录打开终端。
按[中英运行说明](../../../demo/midterm/README.md) 操作：Windows 使用
` .\scripts\start_midterm_demo.ps1 `；macOS/Linux 使用
`docker compose -f compose.midterm.yaml up --build -d --wait`。
打开 <http://localhost:18717/en>，中文版为 <http://localhost:18717/zh>。

| 步骤 | 操作 | 对应证据 |
| --- | --- | --- |
| 输入 | 保留英文示例，点击“① 提交评论” | 导入接口保存评论和等待任务 |
| 状态变化 | 查看入库／等待状态，再点击“② 启动分析” | 任务从 pending 到 claimed，评论进入分析中 |
| 后台步骤 | 等待 Worker | 独立 Worker 进程通过 HTTP 调用规则服务 |
| 结果保存 | 查看类别、原文证据和尝试记录 | PostgreSQL 保存结果、证据关联及分析记录 |
| 运行信号 | 查看次数／历史，检查日志或指标 | 可观察任务状态、重试和 Worker 事件 |

新一轮可选择“首次失败后自动重试”（第二次成功）或“持续失败至重试上限”（三次后失败）。
故障为主动注入的 HTTP 503，额外三秒等待用于展示状态变化。
中英文页面共用同一轮，评论和证据保持原语言，英文页使用英文示例。

### 4. 当前实现与整合

| 方面 | 当前可运行 | 尚待完成 |
| --- | --- | --- |
| 接入 | CSV 文本／JSON 校验、错误、去重、版本、任务和查询 | 真实样本、直接文件上传及导出改进 |
| Worker | 受保护的领取／保存、证据检查、有限重试、过期回收、正文变更处理和指标 | 人工重放接口／工具与任务操作审计 |
| 分析 | 中英文规则提取和按类别归组 | 大模型、语义归组、标注质量评测 |
| 产品前端 | 五页布局和模拟交互 | 真实后台数据、人工决定及跟进落库 |
| 期中界面 | 可从源码构建的独立 Demo，连接真实后台并使用独立数据库 | 本阶段不再扩展演示功能 |

相较早期目标设计，目前已接通后台主链，增加可靠性检查和小型展示入口，原前端继续保留。
Demo 是临时展示页面。本阶段覆盖可运行的分析流程；最终产品前端、人工复核和问题组管理动作仍在开发。

### 5. 证据与验证

- [验证记录](assets/verification.md)：条件、命令和已观察结果。
- [中文版结果截图](assets/demo-result-zh.jpg)：类别、原文证据和已保存尝试记录。
- [当前架构与数据流](../../../docs/architecture.md)。
- [R2 运行链条](../../../docs/r2-logic-chain.md)和[函数流程图](../../../docs/r2-flowchart.md)。

已有记录：94 项单元／集成（含六项 PostgreSQL）、5 项真实 HTTP 冒烟、迁移往返与正常退出，
另有独立 Demo 十例双语验收。一次隔离 Demo 重启后保留五个任务、八条分析记录。
R2 语句覆盖率为 92%，不是模型准确率。结果截图通过中文版页面获取。
后续物流规则扩展另通过 78 项分析单元测试和四例真实 Demo 回归；
这些是单独检查，并非再次运行完整测试。开发者已检查英文按钮，当前没有通用分析准确率结果。

### 6. 风险与后续工作

| 风险或限制 | 后续处理 |
| --- | --- |
| 保修／售后、不同说法可能漏检，也可能误判 | 保留原文供人工核对，后续将这些情况纳入标注评测后再扩大覆盖声明 |
| 规则提取和类别归组较粗 | 补标注样本、模型提取和语义归组评测 |
| 原产品前端尚未接通 | 先接查询，再实现人工写入和跟进 |
| Demo 为本地共享会话 | 轮流演示，以源码启动说明保证可复现 |

后半程依次完成平台样本与范围确认、分析和归组的实现与评测、产品前端及人工复核接入，
再在团队版本执行集成和回归检查。多平台、模型训练和自动平台操作仍不在当前范围内。

### 7. AI 使用说明

我们使用 ChatGPT 完善和润色文档说明，并辅助进行代码框架构造和测试。
