# S0 评估基线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 建立可重复、隔离、默认离线的业务任务评估。

**Architecture:** 新增 backend/task_evaluation 包，不与 backend/evaluation.py 重名。保留旧单问答评估接口，新入口显式 Mock。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---


## 执行约定

工作树：`D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor`。所有相对文件名均相对此目录。先读总设计和总入口计划。新文件标“新增”，现有文件标“修改”。文中的契约示例是测试/实现起点，不代表现有 API。
每个任务按 RED → 最小实现 → GREEN → 回归完成；先确认失败来自预期断言，不把导入/环境失败当作业务缺陷证据。一个任务可拆为多个小提交检查点，但提交前需获得用户授权，只暂存本任务文件。
不调用真实 Provider、不改生产数据。所有日期/时钟、网关和存储在测试中注入；不使用睡眠测试到期。

### 执行记录（2026-10-11）

当前仅推进 S0，尚未启动 S1–S5；变更保留在上述工作树，未提交/推送。已有业务基线（排除未完成的 `backend/tests/task_evaluation`）：**1500 passed**，453.13 秒。前端 `npm --prefix frontend test`：**36 files / 229 tests passed**；`npm --prefix frontend run build`：成功，保留现有大于 500 kB bundle 警告。前端最初因沙箱 `realpath EPERM` 未能执行，取得授权后在沙箱外重跑通过；这不是业务断言失败。后续仍需验证 S0 新执行器和完整 CLI，不将本段基线当作阶段完成验收。

### 执行记录（2026-10-13）

以下为此前实现记录，变更仍保留在工作树，**未提交/推送**。后续独立审核发现预算和 provenance 等缺口，因此不能据此认定四个任务全部完成；以末尾收尾验收记录为准。

- 修复 spawn 子进程 `worker_error`：`worker.py` 的禁网钩子误伤 Windows asyncio 的回环自管道（`_fallback_socketpair` 真连 `127.0.0.1`），改为仅拒绝非本地连接（放行 `127.0.0.1/::1/localhost` 与 AF_UNIX）。
- 目标套件 `backend/tests/task_evaluation`：**65 passed**（修复前为 54 passed / 1 failed）。
- `report.py` 新增 `render_json`；mock 与 live 混合时顶层模型/规则版本记 `unknown`。
- 新增 `scenarios/baseline.json` 六类场景；`--mode mock` 运行六类均产出实际结果与 provenance，`coach-in-scope` 触发 2 次网关调用、其余为 0 次。
- 新增 `docs/evaluation/task-evaluation.md` 记录新旧两个评估入口与报告字段约定。
- 此前全量回归记录（2026-10-13，HEAD `1029a27`）：后端 `backend/tests` **1560 passed / 5 failed**，涉及 SQLite 并发用例的 `attempt to write a readonly database`；前端 **228 passed / 1 failed**，涉及 `AccountSettings` 导出用例。以上是历史结果，失败归因需通过可信环境下的新回归核实，不直接认定与改动无关。沙箱权限或守卫阻断时申请沙箱外执行，不能关闭安全守卫以绕过权限。

### 独立审核与收尾（2026-10-13 至 2026-10-14）

独立重跑目标套件 **65 passed**、六类基线均通过，但确认 `--max-tokens` 未接入账本、配置指纹为占位值、来源与候选耗时未采集、混合模式成本汇总及失败退出码不可靠。用户已授权完成 S0；收尾范围仅评估包、测试和本文档，不启动 S1–S5，不执行真实模型或生产迁移。最终验证前，不把“命令能跑”视为阶段完成。

收尾前已有业务回归（2026-10-14，批准后沙箱外执行）：`backend/tests --ignore=backend/tests/task_evaluation -q -p no:cacheprovider --tb=short --basetemp .tmp/s0-finish-existing-20261013`，**1500 passed**，526.81 秒；前端 **36 files / 229 passed**，构建成功，仅有既有 bundle 大小警告。本次没有重现此前记录的 SQLite 并发失败和前端导出失败；这段仅覆盖已有业务，仍需验证最终 S0 新实现。

最终验收状态：**S0 实现与离线验收完成**；验收时未提交，后续提交/推送状态以 Git 为准，尚未合并到 main。规格复核及代码质量复核通过。完整后端 **1598 passed**（551.21 秒）；随后增加的超估算 unknown 回归连同全部最终 S0 测试重跑为 **99 passed**（94.20 秒）。六类真实 Mock 回放 **6/6 passed**，退出码 0；token=1 与 deadline=1 秒负例均返回退出码 1 并保留报告。前端 **229 passed**、构建成功。完整命令、报告路径和计数口径见 `docs/evaluation/task-evaluation.md`。

修复点：双预算原子预留及失败 unknown、真实配置/源码/目录/场景摘要、实际策略/规则与 retry events、首个校验候选及确认版本关联、计划存储安全结构、spawn 声明意图、跨用户/幂等实际状态、失败退出码与清理状态。S0 不启用 live；旧 profile 字段种子及尚未实现的多轮能力明确 unsupported，不能算通过。没有改动生产业务代码或主仓库用户改动；不进入 S1–S5，不把 Mock 当真实效果指标。

PowerShell 初始化（每个新终端）：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
```

测试文件尚未新增前不运行下列目标测试命令。先新增测试再运行，最小实现后重新运行同一命令，期望 PASS。若现有实现已经通过新测试，记录已有能力，不为制造 RED 破坏代码。

## 文件分工

新增 `backend/task_evaluation/__init__.py`、`contracts.py`、`runner.py`、`scorers.py`、`report.py`、`cli.py`（均位于同一目录）；
新增 `backend/task_evaluation/scenarios/baseline.json`；
新增 `backend/tests/task_evaluation/test_contracts.py`、`test_runner.py`、`test_report.py`、`test_cli.py`。
旧 `backend/evaluation.py` 本阶段只加兼容回归，不静默更改其 live 默认值。
新增 `docs/evaluation/task-evaluation.md` 记录两入口区别。

### Task 1：场景契约与确定性判分

- [x] 在 test_contracts.py 添加以下契约测试；Scenario/score_state 在本任务分别新增到 contracts.py/scorers.py：

```python
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.scorers import score_state

def test_expected_state_is_not_keyword_success():
    scenario = Scenario.model_validate({
        "id": "entry-confirm", "version": 1,
        "steps": [], "expected": {"saved_count": 2},
    })
    assert not score_state(scenario.expected, {"saved_count": 0}).passed
```

- [x] RED：运行 `& $taskPython -m pytest backend/tests/task_evaluation/test_contracts.py -q`。
- [x] contracts.py 定义 Pydantic extra=forbid 的 Scenario：id、version、initial_state、steps、expected。initial_state 保存合成档案、目录、记录、计划、授权范围及注入故障；只接受声明的种子类型，不从任意文件路径导入。steps 为 method/path/body/expected_status/capture/answer_by_field；capture 把返回字段映射到变量名，后续请求以结构化变量引用取值。path 仅允许本地相对 API 路径，不接受 URL。initial_state/capture 默认空对象，保持上面最小测试成立。后续扩展使用 schema version。
- [x] scorers.py 最小判分内核如下；禁止缺字段被当作 None 相等：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Score:
    passed: bool
    failed_fields: tuple[str, ...]

def score_state(expected: dict, actual: dict) -> Score:
    failed = tuple(k for k, v in expected.items()
                   if k not in actual or actual[k] != v)
    return Score(not failed, failed)
```

- [x] 增加无效 URL、未知字段、缺观察结果测试，GREEN 后形成场景契约检查点。

Task 1 验证（2026-10-11）：规格复核及代码质量复核通过。新增边界测试先出现预期断言失败；修复后父代理独立运行 `test_contracts.py -q -p no:cacheprovider --basetemp .tmp/s0-contracts-resume-parent-20261011`，结果 **33 passed**。场景契约通过不代表隔离执行器或 CLI 已完成。

### Task 2：隔离公开入口执行器

- [x] test_runner.py 用 tmp_path 创建两个不同 DATA_DIR，分别注册合成用户、调用现有创建草稿/确认接口；断言第二环境记录数为零。Provider 替身遇到联网调用立即 AssertionError。
- [x] RED：`& $taskPython -m pytest backend/tests/task_evaluation/test_runner.py -q`。
- [x] runner.py 复用 `backend.main.create_app` 与 TestClient、现有认证测试构造方式。每案例子进程使用独立临时 DATA_DIR，同时将 SQLITE_DATABASE_PATH 明确指向此目录，禁用读取工作树.env的生产路径；防止环境变量、get_settings 缓存或进程级资源污染。子进程启动使用 Windows spawn 兼容入口，不把不可序列化网关传给子进程。Mock 在子进程内构造 scripted gateway 并覆盖API依赖，live分支必须先通过准入检查。子进程结果只返回脱敏 JSON；退出释放文件句柄。
- [x] 通过 API 捕获 draft_id、version、record IDs，使用符号引用传给后续步骤；变量引用不存在判 case_error，不跳过确认。回答按 missing_field 名匹配，超出脚本定义问题判 unexpected_question。
- [x] 对状态存储做只读观察，分别统计响应成功与写入效果。先覆盖现有单轮流程；多轮案例在 S2/S3 引入前标 unsupported，不能 PASS。
- [x] GREEN：重复同一场景两次、并发不同案例、强制异常后清理句柄；用户存储路径不能被 runner 接受为临时目录。

### Task 3：指标和报告

- [x] test_report.py 添加可计算样本：两任务成本分别 10/20 token，只有一个成功，成功任务平均成本应为 30，不是 10；零成功返回 null 并保留总成本。
- [x] RED：`& $taskPython -m pytest backend/tests/task_evaluation/test_report.py -q`。
- [x] report.py 用如下基础函数，不以失败样本丢弃来改善数字：

```python
def cost_per_success(total_tokens: int, successes: int) -> float | None:
    return total_tokens / successes if successes else None
```

- [x] 每条 run 保存模式、case/version、git SHA、工作区 diff 摘要、配置指纹、模型/规则版本、系统处理时间、候选时间、成功状态、调用/token、重试和错误分类。禁止输出密钥、原始用户隐私、隐藏推理。
- [x] 输出 JSON 与 Markdown：Mock/live 分组；失败耗时单列；样本数不足时不做 P95 优势声明。服务端处理耗时不包含用户思考。
- [x] GREEN：缺失 token 记 unknown，不能算零；模型版本未知标 unknown；不同模式不能配对比较。

### Task 4：CLI、基线与操作文档

- [x] test_cli.py 验证不指定模式时 mock；指定 live 但无 --allow-live、无正预算拒绝，且构造 Provider 前拒绝。
- [x] CLI 用 argparse：--mode mock|live 默认 mock、--suite、--output、--max-calls、--max-tokens、--max-seconds、--allow-live；本阶段测试 live 拒绝路径，不执行 live。live要求三种预算均为正数。Mock未传预算时使用本地测试配置的有限默认值。
- [x] runner提供父进程维护的批次预算账本：子进程每次Provider调用/重试/审核前向父进程预留调用与token额度，结束结算，未知用量按预留上限保留。父进程用锁保护计数，批次使用monotonic deadline，禁止每个case分别获得整个批次额度。到期终止未完成案例并保存partial报告；网关timeout不得超过批次剩余时间。加入两个worker竞争剩余一次调用、子进程异常退出、deadline耗尽的离线测试；S5扩展准入，复用本账本。
- [x] 新增 baseline.json：正常录入、幂等重试、跨用户拒绝、过期草稿、计划当前激活流程、普通范围内问答六类；预期值来源于合成种子数据。
- [x] 运行：

```powershell
& $taskPython -m pytest backend/tests/task_evaluation -q
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/baseline.json --output .tmp/task-evaluation/s0
```

- [x] 期望六类均有实际结果与 provenance；未支持的新能力单列，不以“全通过”掩盖。记录总入口中的全量回归结果到操作文档。
