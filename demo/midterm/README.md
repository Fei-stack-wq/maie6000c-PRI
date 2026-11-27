# Midterm Demo / 期中演示

## English

### 1. Start the demo

Start Docker Desktop, then open a terminal in the repository root.

**Windows (PowerShell):**

```powershell
.\scripts\start_midterm_demo.ps1
```

**macOS / Linux:**

```bash
docker compose -f compose.midterm.yaml up --build -d --wait
```

When startup finishes, open:

- English: **<http://localhost:18717/en>**
- Chinese: <http://localhost:18717/zh>

The first run downloads dependencies and may take a few minutes. Default rule mode starts
without a key. Model mode uses local `LLM_*` settings; see [AI configuration](../../docs/operations.md#7-ai-configuration).

For a fresh clone after the model branch has been pushed to GitHub:

```bash
git clone https://github.com/Fei-stack-wq/maie6000c-PRI.git
cd maie6000c-PRI
git fetch origin feature/lab8-llm
git switch -c feature/lab8-llm FETCH_HEAD
```

Then run the startup command above.

### 2. Run a demonstration

1. Keep the sample review and select **Normal analysis**.
2. Click **1. Submit review**, then **2. Start analysis**.
3. Wait for the result. The page shows the category, source evidence and attempt history.
4. Click **Start a new round** to try another scenario.

| Scenario | Expected result |
| --- | --- |
| Normal analysis | Completes on the first attempt |
| Fail once, then retry | Completes on the second attempt |
| Fail until the attempt limit | Stops after three failed attempts |

Analysis supports configured models, Chinese/English rules and rule fallback. Attempt history shows
`llm` or `heuristic` and any fallback reason. The English page supplies an English review, and
evidence stays in its original language. Rules cover selected phrases; model quality remains unevaluated.

**Reading the result:** “No specific issue was identified” means this run did not identify an issue
through the selected analysis path. It does not establish that the review is problem-free. Statements such as
“商家不提供保修” / “The seller does not provide a warranty” are outside the current rule coverage and
may be missed. Uncovered complaints can return `no` or `unknown`, depending on language and context.
Read the original review when judging the result. Both missed complaints and false alarms remain possible.

### 3. Stop or check the demo

**Windows:**

```powershell
.\scripts\start_midterm_demo.ps1 -Action stop
```

**macOS / Linux:**

```bash
docker compose -f compose.midterm.yaml down
```

Stopping keeps the saved data. Use the startup command to run the demo again.

Optional verification (leave the page idle):

- Windows: ` .\scripts\start_midterm_demo.ps1 -Action check `
- macOS/Linux: `docker compose -f compose.midterm.yaml exec midterm-demo python demo/midterm/check_demo.py`

Use `LLM_PROVIDER=heuristic` and restart before this check. The ten cases assert rule-mode results
and cover issue / no-issue / unknown, retry success and final failure in both languages.

### 4. Notes and troubleshooting

The Week 07 demo now also displays the Week 08 model integration. It calls the project API, Worker and model/rule AI,
and saves results in a separate PostgreSQL database. The team frontend in
`frontend/` remains separate; this page does not determine the final product UI.

Both language pages share one round, so use them one at a time. Starting a new
round keeps previous database records. Restarting the service returns the page to
an empty round, while saved records remain in the database.

Failure scenarios simulate HTTP 503 responses. Each analysis request has a
three-second pause; retry waits are shortened to three and six seconds for the demo.

| Problem | What to do |
| --- | --- |
| Docker is unavailable | Start Docker Desktop and use Linux containers |
| Port 18717 is occupied | On Windows, run `.\scripts\start_midterm_demo.ps1 -Port 18727`, then open `http://localhost:18727/en` |
| Port 18717 is occupied on macOS/Linux | Run `MIDTERM_DEMO_PORT=18727 docker compose -f compose.midterm.yaml up --build -d --wait`, then open `http://localhost:18727/en` |
| Build or startup fails | Check the terminal output; inspect the `maie6000c-midterm` container logs in Docker Desktop |

---

## 中文

### 1. 启动 Demo

先启动 Docker Desktop，再在仓库根目录打开终端。

**Windows（PowerShell）：**

```powershell
.\scripts\start_midterm_demo.ps1
```

**macOS / Linux：**

```bash
docker compose -f compose.midterm.yaml up --build -d --wait
```

启动完成后，打开：

- 英文版：**<http://localhost:18717/en>**
- 中文版：<http://localhost:18717/zh>

首次运行需要下载依赖，可能需要几分钟。默认规则模式无需模型密钥；模型模式读取本地 `LLM_*` 配置，
见[模型配置](../../docs/operations.md#7-ai-configuration)。

模型分支推送到 GitHub 后，全新下载使用：

```bash
git clone https://github.com/Fei-stack-wq/maie6000c-PRI.git
cd maie6000c-PRI
git fetch origin feature/lab8-llm
git switch -c feature/lab8-llm FETCH_HEAD
```

再执行上面的启动命令。

### 2. 操作演示

1. 保留示例评论，选择“正常分析”。
2. 点击“① 提交评论”，再点击“② 启动分析”。
3. 等待结果，查看问题类别、原文证据和尝试记录。
4. 点击“开始新一轮演示”，切换其他场景。

| 场景 | 预期结果 |
| --- | --- |
| 正常分析 | 第一次分析成功 |
| 首次失败后自动重试 | 第二次分析成功 |
| 持续失败至重试上限 | 三次失败后停止 |

当前支持配置的模型、中英文规则和规则回退，尝试记录显示 `llm`／`heuristic` 及回退原因。
英文页使用英文评论，证据保持原语言。规则覆盖部分表达，模型质量仍待评测。

**如何理解结果：** “未发现具体问题”表示本次所用分析路径没有识别出问题，不代表评论没有投诉。
例如“商家不提供保修”／“The seller does not provide a warranty”不在当前规则覆盖范围内，可能漏检。
未覆盖的投诉可能因语言和上下文返回 `no` 或 `unknown`，应结合原评论判断。中英文都仍可能漏检或误判。

### 3. 停止或检查 Demo

**Windows：**

```powershell
.\scripts\start_midterm_demo.ps1 -Action stop
```

**macOS / Linux：**

```bash
docker compose -f compose.midterm.yaml down
```

停止后保留数据，下次执行启动命令即可继续使用。

可选测试（先让页面停在等待提交状态）：

- Windows：` .\scripts\start_midterm_demo.ps1 -Action check `
- macOS/Linux：`docker compose -f compose.midterm.yaml exec midterm-demo python demo/midterm/check_demo.py`

检查前设置 `LLM_PROVIDER=heuristic` 并重新启动。十例检查断言规则模式结果，
覆盖中英文的有问题、无问题、无法判断、重试成功和最终失败。

### 4. 其他事项与排查

Week 07 小型演示现已加入 Week 08 模型接入展示，调用项目现有的 API、Worker 和模型／规则 AI，结果保存在独立的
PostgreSQL 数据库中。组员编写的 `frontend/` 继续保留，后续完整产品不必采用这个页面。

中英文页面共用同一轮演示，请轮流操作。开始新一轮不会删除之前的数据库记录。
重启服务后页面回到新一轮，已有记录仍保留在数据库中。

故障场景通过模拟 HTTP 503 展示重试。每次分析额外等待三秒；演示中的重试间隔缩短为
三秒、六秒。

| 问题 | 处理方式 |
| --- | --- |
| 无法连接 Docker | 启动 Docker Desktop，并使用 Linux containers |
| 18717 端口被占用 | Windows 执行 `.\scripts\start_midterm_demo.ps1 -Port 18727`，再打开 `http://localhost:18727/en` |
| macOS/Linux 的 18717 端口被占用 | 执行 `MIDTERM_DEMO_PORT=18727 docker compose -f compose.midterm.yaml up --build -d --wait`，再打开 `http://localhost:18727/en` |
| 构建或启动失败 | 查看终端报错，在 Docker Desktop 中查看 `maie6000c-midterm` 容器日志 |
