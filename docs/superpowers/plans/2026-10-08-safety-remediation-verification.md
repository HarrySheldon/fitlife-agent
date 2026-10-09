# 安全整改验证报告

> 2026-10-09 核查修正：下文为 2026-10-08 的历史执行记录，不应将其中“阶段 A、B、C 已完成”作为当前验收结论。后续发现正式入口未传递结构化网关、结构化建议未接入语义审核、二次审核重复追加提示，以及合成评测样本缺失。补齐记录及最新测试结果见 [2026-10-09 补齐验证报告](./2026-10-09-safety-remediation-followup.md)。历史测试通过不证明这些未覆盖路径已正确接入。

**执行者：** DSH agent
**日期：** 2026-10-08
**计划：** [2026-10-08-safety-correctness-integration-grounding.md](./2026-10-08-safety-correctness-integration-grounding.md)
**基线 HEAD：** `448d5df`
**阶段 A / B 提交：** `a3d93f9` / `f7af014`
**阶段 C 与文档：** 见 `git log` 中本报告所在提交
**分支：** `codex/agent-runtime-refactor`
**工作树：** `D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor`

---

## 0. 状态声明

| 项 | 状态 |
|---|---|
| 程序契约测试 | ✅ 通过（见 §2） |
| **真实模型效果评测** | ❌ **未执行**（见 §5） |
| 报告不得把契约测试通过描述为模型安全率 | 本文遵守 |

**本文不宣称整个安全系统完备。** 计划 §9 明确要求：用户验收后再讨论第四项架构重构。

---

## 1. 三个阶段的提交

| 阶段 | 提交 | 内容 |
|---|---|---|
| **A** | `a3d93f9` | reviewer 失败时保留确定性处置 |
| A 之外 | 同提交 | **修复 adapter 绕过清洗**（计划 §0 指出的相邻风险） |
| **B** | `f7af014` | 结构化审核 Adapter + Runtime 编排 + 三条入口接入 |
| **C** | 本报告同批 | 证据目录 + 确定性渲染 + Writer 接入 |

阶段 A 与 B 各自独立提交；C 与文档更新合并为一次提交。

---

## 2. 执行的命令与结果

### 2.1 全量后端测试（阶段 B 后）

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests -q -p no:cacheprovider --basetemp=.tmp\runB
```

**退出码：** `0`
**结果：** `1323 passed, 1 warning in 429.72s`

### 2.2 全量后端测试（阶段 C 后）

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests -q -p no:cacheprovider --basetemp=.tmp\runC
```

**退出码：** `0`
**结果：** `1373 passed, 1 warning in 463.47s`
**唯一 warning：** `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`（既有，与本次无关）

### 2.2b 全量后端测试（Task V1 合成样本后）

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests -q -p no:cacheprovider --basetemp=.tmp\runV1
```

**退出码：** `0`
**结果：** `1492 passed, 1 warning in 445.96s`

### 2.2c 合成契约套件单独运行

```powershell
& $projectPython -m pytest backend/tests/test_safety_synthetic_contracts.py -q
```

**退出码：** `0`　**结果：** `114 passed`

| 组成 | 数量 | 要求 |
|---|---|---|
| reviewer 样本（明确贬低 / 中性不利事实 / 边界） | **60** | ≥60（20+20+20） |
| grounding 样本（8 类） | **45** | ≥40（每类 ≥5） |
| 结构性与路径断言 | 9 | — |

### 2.3 本阶段新增的测试文件

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `test_safety_review_failure_disposition.py` | 129 | 阶段 A：mask/disclose/refuse/escalate/annotate + 严重度下限 |
| `test_safety_writer_payload_reaches_provider.py` | 154 | adapter 实际发送内容（两个 provider） |
| `test_safety_review_adapter.py` | 123 | `ReviewVerdict` 合法配对与拒绝 |
| `test_safety_review_integration.py` | 207 | Runtime 编排、失败语义、可观测词汇 |
| `test_safety_review_entry.py` | 187 | 生产入口 + Fake Provider，读事件断言 |
| `test_safety_evidence.py` | 203 | 证据目录、非法值、跨指标、跨日期、边界 |
| `test_grounded_answer.py` | 214 | 渲染、数字筛查、空目录 |
| `test_grounded_answer_integration.py` | 209 | **provider 实际收到的 input** |

### 2.4 先红后绿

阶段 A 的用例在修改前 **6 个失败**（`mask`/`disclose`/`refuse`/`escalate`/`annotate`/严重度下限），
修改后 10 个全部通过。红是功能失败，不是 import 错误。

---

## 3. 阶段 A：修复内容

### 3.1 缺陷

`review_output` 的 reviewer 异常分支在 `severity < 6` 时**直接返回草稿**，跳过动作分派：

| 动作 | 修复前 | 修复后 |
|---|---|---|
| `mask` | 不执行 | ✅ 执行 |
| `disclose` | 不执行 | ✅ 执行 |
| `refuse` / `escalate` | 不抛 | ✅ 抛 |
| `annotate` | **连草稿都不按原样返回** | ✅ 原样返回 |

同时该分支**只取 `_with_caveat(...)[0]`，丢弃更新后的 verdict**，导致正文与 verdict 不一致。

### 3.2 修法

删除提前返回，让控制流进入**已有的统一动作分派**；`if decision.outcome == "refuse"`
移入 `else`，避免异常后使用未赋值的 `decision`。高严重度下限保留。

新增：`decision.outcome not in {"allow","refuse"}` 视为**不支持**，进入既有故障处置——
`rewrite` 是我们的决定，不是 reviewer 的；接受它等于在无人检查的标签下发货。

**保留 fail-closed 的适用条件**：`severity >= 6` 且 reviewer 未运行 → 仍然扣下草稿。

---

## 4. 计划 §0 指出的相邻风险：已修复

计划原文：

> 当前 `FitLifeWorkflow._writer` 记录 `writer_payload`，但调用 `gateway.write_answer(state)`；
> 两个生产 Adapter 又调用 `writer_payload(state)` 重新组装数据。应单独核验实际请求是否使用了清理后的载荷。

**核实结果：该风险成立，且是本轮我引入的。**

| 项 | 事实 |
|---|---|
| 我上一轮的声称 | "注入记录被隔离，模型收到的上下文无注入" |
| 实际情况 | `openai_responses.py:90` 与 `openai_chat_completions.py:48` 都调用 `writer_payload(state)` **从原始 state 重新组装** |
| 后果 | **上下文清洗在生产路径上从未生效**；我此前的测试用假 gateway，看不到这一点 |
| 修复 | 新增 `writer_payload_for_model(state)`，优先使用守卫记录的 `writer_payload`；两个 Adapter 均改用它 |
| 证据 | `test_safety_writer_payload_reaches_provider.py` 用**假客户端捕获 provider 实际收到的 input**，断言其中不含注入文本 |

**这正是计划 §0 警告的"检查一份、发送另一份"模式，而我上一轮的测试恰好复制了这个错误。**
计划 §2 Task C3 的对应要求（"测试两个 Provider 实际收到的 input/messages"）在阶段 C 同样执行：
`test_grounded_answer_providers.py` 用假客户端捕获 **Responses 与 Chat Completions 两个 adapter**
实际收到的 `input` / `messages`，断言其中含问题、含证据目录（metric/unit/scope），并断言渲染出的数字来自目录。

---

## 5. 未执行项与限制

### 5.1 未执行

| 项 | 原因 |
|---|---|
| **真实 Provider 评测**（计划 Task V2） | **需用户同意费用与数据发送**；本环境不访问真实模型 |
| ~~合成评测样本（Task V1）~~ | ✅ **已完成**，见 §2.2c |
| 灰度与门槛判定（计划 §7 发布门槛） | 无真实评测数据，不做判断 |
| 阶段 B 的 enforce 上线、阶段 C 的 evidence 上线 | 均为部署决策，默认 `off` / `legacy` |

**关于 Task V1 的诚实说明**：合成样本验证的是**程序契约**，不是模型安全性。
`reviewer_cases.json` 里的 `refuse` 用例由**固定假 provider** 回放期望值，因此它证明的是
"判定一旦产生，就会沿正确路径传递"，**不是"模型会正确判定"**。
把这份套件的通过率描述为模型安全率是错的，计划 §7 也明确禁止。

**词表许可**：ToxiCN 的词表是 CC BY-NC-ND 4.0（禁商用、禁演绎），且实测含有
`草`/`狗`/`猪` 等健身场景正常词。**本套件不包含该词表**，样本中的贬低表述是为测试
程序路径而自写的合成文本。

### 5.2 已知取舍（不隐藏）

1. **说明与建议类文本块只要含数字就被剔除。** 规则很钝，会丢掉有用句子。
   理由是这一层能看见数字、看不见数字对不对。剔除时追加"部分数值内容无法核实，已省略。"
2. **中文数值表述的覆盖有限。** `_CHINESE_NUMBER` 覆盖紧邻量词的中文数词，
   不构成完整的自然语言数值识别。
3. **证据目录只覆盖两个意图。** 其他意图保留 legacy 启发式，**不宣称等价安全**。
4. **证据上限 512 条**，超限抛错而非截断。
5. **`strength_volume` 的 scope 取工具结果中出现的周集合**，因为工具只返回总量。

### 5.3 测试脚手架的两次修正（记录以免误读）

1. 阶段 A 的初始用例把迭代器建在 lambda 内部，每次调用都新建 → 永远返回第一个判定。
   修正为迭代器建一次、由被 patch 的可调用对象消费。
2. 入口级测试最初用 `test_runtime_persistence` 的本地假仓库，其接口与
   `AgentRuntime` 不兼容（`KeyError`）。改用真实
   `backend/infrastructure/agent_runtime/memory_run_repository.py`。

---

## 6. 与计划范围的符合性

| 计划要求 | 状态 |
|---|---|
| 不重构所有工作流的强制安全入口 | ✅ 未做 |
| 不更换完整 Repository 为只读 Adapter | ✅ 未做 |
| 不扩展上下文扫描范围 | ⚠️ **已在上一轮做过**（守卫契约、结构化路径清洗），不在本轮范围内重复 |
| 不实现外链/DLP、后台任务、人工接管 | ✅ 未做 |
| 不训练安全模型 | ✅ 未做 |
| 不承诺医学事实核查 | ✅ 文档与提示词均未承诺 |
| 没有数据库迁移 | ✅ 无 |
| 未修改主仓库用户文件 | ✅ 未动 `research-*.md` |

---

## 7. 结论

- **阶段 A、B、C 的代码与契约测试已完成**，全量 `1492 passed` / 退出码 `0`。
- **Task V1 合成契约套件已完成**（reviewer 60 条、grounding 45 条，`114 passed`）。
- **真实模型效果评测未执行**，因此**不声称**模型安全率、误拒率或漏检率达到任何门槛。
  计划 §7 的发布门槛（误拒率 ≤5%、漏检率 ≤10%、错误数值事实 = 0）**一项都未测量**。
- 计划 §0 指出的相邻风险已核实并修复，且修复方式针对**真实发送路径**而非内部状态。
- 测试对两个 Provider 均断言**实际发送内容**，而非内部状态。
- 发布顺序遵循计划 §8：A 已可上线（不增加调用成本）；B 与 C 的代码已就位但保持
  `off` / `legacy`，切换需要真实评测数据与部署决定。
