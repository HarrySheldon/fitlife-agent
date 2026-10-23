# 统一教练 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans（顺序执行）或用户明确选择后的 subagent-driven-development，逐任务推进；使用当前环境同名技能，不自动委派。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个以渐进式 Skill 和确定性工具完成教练需求、权限不由模型控制、无任意代码执行的统一 Agent。

**Architecture:** 保留 AgentRuntime、会话和任务账本，在其内新增有界决策循环。通用结构化决策 Adapter 解耦供应商协议，统一执行器绑定身份并控制资源；Skill 提供方法但不提供权限，正式写入继续走既有业务与后续 S3。

**Tech Stack:** Python、Pydantic、FastAPI、现有结构化模型 Adapter、pytest、现有 task_evaluation；React/TypeScript/Vitest 仅做教练回归及必要展示适配。

---

## 0. 范围、依据和执行状态

设计：[详细方案](../specs/2026-10-22-unified-coach-agent-design.md)。文档核对基线 `main/a042ed9`。用户已授权实施，开发分支 `codex/unified-coach-agent`。**U0–U6本地实施与离线验收完成，未提交/集成/部署**；最新状态以 [验收记录](../../evaluation/unified-coach-acceptance.md) 为准，历史测试数字不能当作本计划验收。

### 本轮实施对应表

| 检查点 | 当前证据 |
| --- | --- |
| U0.1 / U0.2 | 原请求行为RED→修复，41项目标回归；原版本全量基线2238项 |
| U1.1 / U1.2 | 严格决策、双供应商真实Adapter假client、稳定上下文与隔离测试 |
| U2.1 / U2.2 | 资源目录、digest终态、参考资料、按需发现与扩展；Windows链接用例权限不足明确skip |
| U3.1 / U3.2 | 固定工具、绑定身份/只读授权、空分析、字段/日期限制、执行前复验 |
| U4.1 / U4.2 | 有界循环、模型/工具预算预留、建议与事实数字、必要审核故障不发布原稿 |
| U5.1 / U5.2 | HTTP双入口、会话生命周期回放、所有非Coach业务表及计划/草稿文件前后比较 |
| U6.1 | 修订后28/28隔离Mock场景通过；可信授权撤销注入而非新增许可UI |
| U6.2 | 最终单次完整后端2299通过/1平台skip，配置6通过，前端299通过及构建通过；保留失败修复历史与源码哈希清单 |

下列复选框保留原始操作清单，不补造未逐条保存的RED历史，也不擅自勾选提交/推送。阶段功能与已验证范围按上表和验收记录判定。测试实现将部分原拟拆分文件合并在 `test_tool_authorization.py`、`test_skill_catalog.py`，以实际测试路径为准，不声称不存在的测试文件已运行。

用户确认：不开放任意代码/脚本/命令，计算使用预定义工具；暂不做执行沙箱。权限检查、隐私、健康输出和正式写入隔离仍必须实施。

顺序：S0–S2/M/C0–C4 → **U0–U6（本文）** → S3 → S4 → S5。U 阶段 7 个，每阶段 2 个检查点，共 14 个；每个检查点先失败测试，再最小实现，再目标回归及记录。不要把 U 当作 S3 已完成，不实施正式计划迁移或原子激活。

提交仅在用户授权时进行；下列 commit message 是建议检查点，不授权自动 commit/push。只做文档不需要新分支/备份；实际实施前必须按 AGENTS 备份及隔离。

## 1. 文件责任地图

以下新增名是本文明确规定的拟建路径，未声称已经存在。已有文件实施前重新核对，不覆盖工作区改动。

| 新增文件/目录 | 唯一责任 |
| --- | --- |
| `backend/agent/decision.py` | call/ask/final 的严格结构及结果元数据 |
| `backend/application/ports/agent_decision_gateway.py` | `decide(request)` Interface |
| `backend/infrastructure/model_gateway/agent_decision_adapter.py` | 复用 parse_structured，无原生调用门槛 |
| `backend/agent/context_builder.py`、`backend/agent/prompts/coach_system.md` | 稳定提示词、有界动态状态和数据投影 |
| `backend/agent/skills/catalog.py`、`loader.py` | 发布资源 ID、版本、摘要发现与读取 |
| `backend/coach_skills/{training-plan,nutrition-review,today-explanation}/SKILL.md` | 可复用业务方法，无脚本执行 |
| `backend/agent/tools/contracts.py`、`registry.py` | 工具参数、权限元数据、稳定目录 |
| `backend/agent/tools/executor.py`、`handlers.py` | 可信权限检查、绑定身份查询、确定性计算 |
| `backend/agent/unified_coach.py` | 通用有界循环，不含领域算法 |
| `backend/agent/coach_delivery.py` | 最终可见内容统一校验及结果投影 |
| `backend/tests/unified_coach/` | 通过公开 Interface 测协议/上下文/授权/循环/发布 |
| `backend/task_evaluation/scenarios/unified_coach.json` | 合成可重放场景 |
| `docs/evaluation/unified-coach-baseline.md`、`unified-coach-acceptance.md` | 新鲜基线、阶段证据及局限 |

重点复用/修改：`backend/agent/{workflow,runtime,graph,analyzers,model_payloads}.py`、`backend/agent/tasks/capabilities.py`、`backend/safety/business_scope.py`、`backend/domain/coach_answer.py`、`backend/config.py`、`backend/application/use_cases/coach_turns.py`、已有模型 gateway factory 与教练 composition、`backend/task_evaluation/{contracts,runner,metrics,report}.py`。

不要求所有文件一定修改；能通过注入复用的不为满足清单而重写。尤其 `async_coach_gateway.py` 及其测试已有用户修改，实施前先对照，原则上无需修改它们。

## 2. 公共测试命令与隔离前置

工作树/分支建立之前完成仓库要求的主库备份。核对 `.env` 只读取所需配置，不打印内容或密钥；记录已解析主 SQLite 与独立 Runtime 库（如启用）。运行主 checkout 的解释器：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
$taskPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $taskPython scripts/backup_sqlite.py --help
if ($LASTEXITCODE -ne 0) { throw 'Backup CLI unavailable' }
```

随后按实际 CLI 和配置备份到 `.local-backups` 时间戳绝对路径，验证返回完整性和 checksum；本文不假装知道运行时主库位置，也不提供会误备份默认库的 apply 命令。备份成功后才建用户批准分支/工作树。复制测试数据用备份或合成数据，不复制 live DB。

下面命令在**实际实施 checkout 根目录**执行，使用该 checkout 的已知解释器；若无独立 venv，明确使用上述主解释器绝对路径，不尝试裸 python。先核对主数据路径不等于测试目录，再开始：

```powershell
git status --short
git rev-parse HEAD
$taskPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $taskPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
$taskTestDir = Join-Path (Get-Location).Path ('.tmp\unified-coach-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $taskTestDir -Force | Out-Null
$env:DATA_DIR = $taskTestDir
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
& $taskPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed' }
& $taskPython -m pytest backend/tests --ignore=backend/tests/test_config.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Backend regression failed' }
npm --prefix frontend test
if ($LASTEXITCODE -ne 0) { throw 'Frontend regression failed' }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
```

配置独立组另开 PowerShell 进程，移除 DATA_DIR、SQLITE_DATABASE_PATH、LLM_ENABLED 覆盖后，先 verify pytest，再运行 `backend/tests/test_config.py`；不在该进程启动应用。新增 API 测试必须用 tmp_path 数据库、假凭据及网络阻断 fixture，不能读取真实账户配置后仅用 LLM_ENABLED 自称已隔离。

后续 `& $taskPython -m pytest ...` 均引用上述已验证解释器，测试文件在相应任务创建后才可运行。每个 RED 必须是预期功能断言失败，导入失败只证明缺模块，建立模块后再取得行为 RED。

## U0：可信基线与业务准入修复

### U0.1 记录旧行为和评估分组

文件：新增 `backend/tests/unified_coach/test_scope_regression.py`、`docs/evaluation/unified-coach-baseline.md`；读取 `test_task_business_scope.py`、C4 记录及现有评估 runner。

- [ ] 建立带问候、口语、明确动作、必要条件缺失、范围外、混合问题、中文/英文的固定样本；记录旧返回、模型尝试和工具访问，不把普通缺信息当攻击。
- [ ] 用下面测试钉住实际问题；先证明现有 `needs_clarification=True`，保存基线，再加入目标断言取得 RED：

```python
from backend.safety.business_scope import decide_business_scope

def test_chest_request_is_not_rejected_by_expression():
    text = '教练你好，我需要今天练胸，给出一份完整的训练计划'
    decision = decide_business_scope(text, planner_consulted=True)
    assert decision.scope != 'out_of_scope'
    assert decision.needs_clarification is False
```

- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_scope_regression.py -q`；记录具体断言和旧值，不把此时 RED 报告成实现故障。
- [ ] 跑第 2 节完整新鲜基线，分环境故障/既有失败/新增失败；写明 SHA、dirty 文件、隔离路径、命令和耗时。此项不调用真实模型、不承诺通过。

### U0.2 修复 Unclear 准入而不移除安全检查

文件：修改 `backend/safety/business_scope.py`、`backend/agent/workflow.py`；测试 `test_scope_regression.py`、`backend/tests/test_task_business_scope.py`、`test_safety_guard_contract.py`。

- [ ] 将词法判断降为显式已知范围外/辅助信号；未匹配返回可继续理解，禁止 Planner 后仅用相同规则把正常请求改为必须澄清。
- [ ] 保留输入安全、上下文和最终审核契约；对“未知应允许进入理解”和“允许越权执行”作不同断言。原显式范围外用例仍简短引导。
- [ ] scripted gateway 给正常练胸请求返回合法决策，断言到达后续步骤而非 BoundaryWorkflow；缺器械时可以提出具体问题，不能输出原泛化“请单独说明”。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_scope_regression.py backend/tests/test_task_business_scope.py backend/tests/test_safety_guard_contract.py -q`，预期全绿；更新受影响旧测试的合理新预期，保留历史记录。
- [ ] 检查点建议 `fix(coach): stop treating unmatched phrasing as unsafe`；用户授权才提交。

## U1：统一决策协议与稳定上下文

### U1.1 结构化决策 Adapter

文件：新增 `decision.py`、`agent_decision_gateway.py`、`agent_decision_adapter.py`、`backend/tests/unified_coach/test_decision_gateway.py`；复用 `structured_model_gateway.py`、现有 Responses/Chat Completions Adapter。

- [ ] 在 decision.py 定义下列有类型协议及基于 `kind` 的 discriminated union；每种结构均 extra=forbid，文本字段有正长度上限；`ToolCall` 与工具目录参数验证分离：

```python
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

class ToolCall(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['call'] = 'call'
    call_id: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, object]

class AskDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['ask'] = 'ask'
    question: str = Field(min_length=1, max_length=1200)

class FinalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['final'] = 'final'
    body: str = Field(min_length=1, max_length=12000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=64)

AgentDecision = Annotated[ToolCall | AskDecision | FinalDecision, Field(discriminator='kind')]

class DecisionEnvelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: AgentDecision

def test_final_cannot_smuggle_tool_call():
    import pytest
    with pytest.raises(ValueError):
        TypeAdapter(AgentDecision).validate_python({
            'kind': 'final', 'body': '建议', 'tool': 'delete_account'})
```

- [ ] 测试中从生产模块 import，先对 extra 字段/混合动作取得 RED，再实现严格模型；完整循环允许的篇幅仍由 action 契约决定，12000 是协议硬上限不是默认展示长度。
- [ ] `AgentDecisionRequest` 定义 instructions/messages/tool_descriptions/max_output_tokens；`AgentDecisionResult` 定义 decision/model/usage。`decide` 调用 parse_structured(response_model=DecisionEnvelope)，本地再校验；不增 SDK 隐式重试、不自动调用 probe_tool_call。
- [ ] 对两种既有 provider Adapter 使用假 client：同样输入得到相同决策；纯 JSON fallback、本地拒绝多余字段、格式失败无工具执行，usage 原样送 Runtime 记账。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_decision_gateway.py backend/tests/test_model_protocol_adapters.py backend/tests/test_model_connection_probes.py -q`。预期全部通过，连接保存门槛不变。

### U1.2 稳定提示词和有界状态

文件：新增 `backend/agent/context_builder.py`、`backend/agent/prompts/coach_system.md`、`backend/tests/unified_coach/test_context_builder.py`；复用 `backend/agent/model_payloads.py`、`backend/domain/coach_answer.py` 的语言规则。

- [ ] 定义 `ExecutionPrincipal(owner_id, conversation_id, authorized_domains, policy_version)`，仅可信应用构造；具体 grant 仍需执行时重载。定义 `RuntimeState(revision, as_of, language, answer_mode, task_ref, phase)`，模型返回不得直接覆盖。
- [ ] 测试两次仅时间/进度不同的请求 `instructions` 完全相等、工具 schema 顺序相等、旧上下文是新上下文前缀直到有界压缩；正文含“English”不覆盖显式 zh-CN。
- [ ] 实现 `build_context`：稳定前缀、后置状态、当前聊天有界历史、带来源 observation；裁剪不删当前用户问题/必要硬约束，放不下时受控失败而非静默丢安全限制。
- [ ] 故障用例：另一个聊天、90天过期历史、记录中的伪造权限、密钥形状字段均不得进入敏感位置；过期历史不能通过摘要回流。压缩只作用后部，不承诺压缩前后缓存一定命中。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_context_builder.py backend/tests/test_coach_api.py -q`。预期上下文隔离及旧语言行为都通过。
- [ ] 检查点建议 `feat(agent): add provider-neutral decisions and stable context`。

## U2：渐进式 Skill 与受控资源

### U2.1 版本目录及资源解析

文件：新增 `skills/catalog.py`、`skills/loader.py`、包初始化文件、`backend/tests/unified_coach/test_skill_catalog.py`。

- [ ] 目录建立 SkillMetadata(id/version/title/description/resource_ids/digest)，启动加载时验证重复 ID、引用不存在和摘要；run 保存 release/digest。
- [ ] 编写 `SkillCatalog.search(query, limit)` 和 `SkillCatalog.read(resource_id, expected_digest)` 的行为测试：摘要不含正文；limit≤8；只接受已注册 ID；12000 字符超限返回 `RESOURCE_TOO_LARGE`。
- [ ] 用 tmp_path 建带恶意外部链接的资源，断言读取 `../.env`、绝对路径、UNC、URL、符号链接/Windows junction 逃逸均失败。资源解析校验最终路径仍在发布根下；无法构造链接的环境单独标注该平台用例，不伪造通过。
- [ ] 实现只读发布目录、canonical path 校验和 digest 校验；不使用用户上传路径，不加载脚本，不开放 Skill 写工具。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_skill_catalog.py -q`；预期目录变化产生 `RESOURCE_VERSION_CHANGED`，不是读取新内容继续原 run。

### U2.2 三个首发 Skill

文件：新增三个 SKILL.md 和必要 references、`backend/tests/unified_coach/test_skill_disclosure.py`。

- [ ] training-plan：输入目标/时间/器械/经验/相关限制；必要缺失具体询问；查询训练，不擅自查询饮食；确定性校验建议参数；不宣称保存。nutrition-review：仅授权饮食输入，数值来自工具。today-explanation：使用页面已验证上下文、简短解释、不重复加载全档案。
- [ ] 三个文件都写明停止条件、建议与事实区别、引用/语言/篇幅、无脚本执行；不要写“读取全部数据以获得完整上下文”。
- [ ] scripted 决策测试先 search，再 read 目标正文，再按需读 references；未选中的 Skill 正文不进模型输入，新增一个测试 Skill 不需修改循环或执行器。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_skill_disclosure.py backend/tests/unified_coach/test_skill_catalog.py -q`，预期选中链路及扩展性断言通过。
- [ ] 检查点建议 `feat(agent): add progressive project skill resources`。

## U3：确定性工具与最小权限执行

### U3.1 严格工具目录与绑定身份读取

文件：新增 `tools/{contracts,registry,executor,handlers}.py`、`backend/tests/unified_coach/test_tool_authorization.py`；复用 `AuthorizedTaskReads`，必要时收紧 `analyzers.py` 的只读依赖。

- [ ] ToolSpec 固定 name/参数模型/required_domains/read_only/handler；目录只注册设计中五种工具。参数 extra=forbid，不接受 user_id、owner_id、confirmed、path、sql、code 等未声明字段。
- [ ] 执行器 `execute(principal, call, runtime_context)` 先取消/预算，再解析、重载授权、验证归属/资源/字段，最后 handler；查不到或非本用户资源对外同样受控，不泄漏资源存在性。初始范围由可信应用依据请求和已有许可创建，模型分类不是 grant；不明确的跨域需求走许可流程，不自动扩大。
- [ ] 写穿透测试：假模型提交他人 user_id、缺身份、未许可 diet、撤销后的旧快照、未知工具；断言 repository 的读写 spy 都未被调用。先拿到行为 RED 再实现。
- [ ] fitness.query 将 owner 绑定在只读 Adapter 内，不传完整仓库给 handler；start/end 有序、≤90天、≤200行，profile 字段投影。模型不能用分页无限提取，调用受 run 预算控制。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_tool_authorization.py backend/tests/test_task_capabilities.py backend/tests/test_safety_write_invariant.py -q`，预期越权实际访问次数为 0。

### U3.2 计算、检索与有界返回

文件：修改 handlers、contracts；新增 `backend/tests/unified_coach/test_deterministic_tools.py`、`test_tool_observations.py`；复用 `backend/tools/{meal_analyzer,workout_analyzer,report_generator}.py`、`backend/agent/{generator,validator}.py` 和现有 RAG。

- [ ] 为实际需要的算法建立固定 operation 注册表与各自严格参数模型；不做 eval、不接受自由表达式、不用 getattr 从用户字符串寻找后端函数。
- [ ] 测试相同输入/算法版本结果一致，单位/舍入明确；记录引用必须属于当前 run/owner 且仍有效。建议组数等 typed 输入与 factual observation 分开标记，越界值/未知单位受控拒绝。
- [ ] knowledge.search 限 top_k≤5、query≤1000、授权 scope；不把整份健康档案塞检索词；返回稳定来源与证据 ID。工具结果中的指令文字不改变权限或覆盖系统状态。
- [ ] observation 固定 call_id/tool/status/data/evidence_refs/source_version，结果过大返回错误或显式分页，不静默裁剪安全限制。公开错误只含 code 和必要提示，日志不保存密钥或完整记录。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_deterministic_tools.py backend/tests/unified_coach/test_tool_observations.py backend/tests/test_analyzer_registry.py backend/tests/test_retriever.py -q`，预期算法旧行为兼容、越权引用零成功。
- [ ] 检查点建议 `feat(agent): enforce least privilege on deterministic tools`。

## U4：有界循环与统一交付

### U4.1 通用循环、预算及取消

文件：新增 `unified_coach.py`、`backend/tests/unified_coach/test_agent_loop.py`；必要修改 `runtime.py` 以复用现有调用记账，不另造账本。

- [ ] 使用 ScriptedDecisionGateway（在测试文件定义，按列表 pop 决策并记录请求）驱动 search→read→query→calculate→final，断言 Runtime 真实计数、顺序及唯一 call_id。
- [ ] 实现以下控制算法；这里的 `gateway.decide/executor.execute/delivery.review` Interface 由 U1/U3/U4.2 定义，所有实际模型/工具调用通过 RuntimeContext 包装：

```text
最多12次 decision：
  context.raise_if_cancelled()；检查 deadline
  build_context；经现有预算调用 gateway.decide
  call → executor.execute → 追加有界 observation → 继续
  ask/final → delivery.review → 返回已有 AgentResult
  协议/动作连续失败2次 → 受控失败
循环耗尽 → BUDGET_EXCEEDED
```

- [ ] 同参数/依赖版本未变的成功只读调用允许 run 内复用；复用前重新鉴权。重复 call_id 拒绝；新 call_id 同参数记 cache_hit，不伪造物理执行计数。无效动作不触发 handler，模型尝试照常计费记账。
- [ ] 故障测试：无限调用、非法 JSON、预算预留失败、取消前/中/后、超时、传输未清理、迟到返回；断言停止后不执行工具、不发布、不提前释放账户槽。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_agent_loop.py backend/tests/test_agent_runtime_controls.py backend/tests/test_runtime_task_budget.py backend/tests/infrastructure/test_async_coach_transport.py -q`，预期新旧账本一致；不覆盖用户 transport 修改。

### U4.2 最终文本与候选安全

文件：新增 `coach_delivery.py`、`backend/tests/unified_coach/test_delivery.py`；修改 `domain/coach_answer.py`、复用 safety/evidence/review 和现有 Runtime 最终审核。

- [ ] `delivery.review(decision, principal, evidence, answer_contract)` 生成唯一可发布结果；外层 Runtime 保留必需检查，通过可信执行标记避免重复语义模型审核，标记不能从模型或 Skill 接受。
- [ ] 测试正常“3组×10次”作为建议经确定性校验可展示，但伪造“你昨天做了100kg”无证据拒绝；完整训练建议 action 注册详细篇幅，不继承快捷卡片上限。
- [ ] 对 ask 与 final 同样做隐私/健康/长度/安全渲染；off/shadow/enforce 保持既有含义；enforce 依赖故障不泄露原草稿，shadow 不冒充已阻断。拒绝不得触发私自“修好再提交”。
- [ ] 模型输出“已激活”但没有受控业务回执时禁止成功文案；证据 ID 必须来自本用户本次授权 observation，不能以任意字符串引用历史他人资料。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_delivery.py backend/tests/test_safety_guard_contract.py backend/tests/test_safety_review_failure_disposition.py backend/tests/test_safety_writer_payload_reaches_provider.py -q`。预期未审核故障草稿零发布、同阶段重审核模型调用零重复。
- [ ] 检查点建议 `feat(coach): deliver bounded and safety-checked agent decisions`。

## U5：教练入口集成与 S3 接缝

### U5.1 模式开关与会话兼容

文件：修改 config、既有教练 composition/factory、graph、CoachTurnService 的注入位置；新增 `backend/tests/unified_coach/test_entry_integration.py`，复用现有 C4 测试。

- [ ] 添加 `coach_agent_mode: Literal['legacy','unified']='legacy'`，run 固定选择。编写入口矩阵覆盖会话、页面 Coach、快捷动作及旧兼容路由；新旧身份/幂等/单槽一致。
- [ ] unified 使用新 Workflow；legacy 保留旧工作流但已包含 U0 修复。异常不在同一请求自动 fallback 重跑，关闭模式先取消清理后仅影响新 run。
- [ ] ask 发布为正常 assistant 消息并释放槽；下一轮携带当前聊天的有限历史，不能把跨聊天引用视为同一任务。保留语言、收起后完成、停止与消息入库行为。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_entry_integration.py backend/tests/test_coach_api.py backend/tests/test_chat_api.py backend/tests/task_evaluation/test_coach_conversations.py -q`；再跑 `npm --prefix frontend test -- src/components/coach/CoachWindow.test.tsx src/components/coach/CoachMessages.test.tsx`。

### U5.2 正式业务隔离与旧计划对齐

文件：新增 `backend/tests/unified_coach/test_business_write_separation.py`；必要修改 coach_delivery/入口契约；更新原 S3/总计划的增量说明，保留历史记录。

- [ ] 编写建议型训练计划前后数据库、正式计划文件/当前指针深比较测试；除正常会话/run记录外不得产生正式业务写入。请求“保存/激活”而 S3 未启用时准确说明尚未执行，不伪造候选任务。
- [ ] 现有 Smart Entry 确认仍走同一应用服务；工具集合中无 activate/delete/raw_sql/shell，假模型请求均被拒且无副作用。
- [ ] 写清 S3 接缝：统一 Agent 生成/修复领域候选，原 S3 模块持有范围许可、task版本、共享两轮、差异和原子确认。模型不创建替代任务绕过耗尽额度，聊天清理不删除正式计划。
- [ ] 在实施 S3 前调整其 task 2，不再创建另一套 Planner/Writer 和模型预算；若确需新 tool，限领域候选生成/校验，不将激活作为自由工具开放。
- [ ] 运行 `& $taskPython -m pytest backend/tests/unified_coach/test_business_write_separation.py backend/tests/test_smart_entry_confirmation.py backend/tests/test_task_lifecycle.py backend/tests/test_account_delete_api.py -q`，预期正式数据不变、既有确认无回归。
- [ ] 检查点建议 `feat(coach): integrate unified agent without widening write access`。

## U6：对抗、效果和性能证据

### U6.1 扩展现有评估器与测试集

文件：修改 `backend/task_evaluation/{contracts,runner,metrics,report}.py`、mock gateway；新增 `scenarios/unified_coach.json`、`backend/tests/task_evaluation/test_unified_coach.py`。

- [ ] 新增 scripted 决策序列和白名单观察：decision_count、tool_attempts、tool_executions、tool_denials、cache_hits、loaded_skill_ids、protocol_failures、published_unreviewed、formal_write_count；业务成功由实际消息状态、引用及数据变化判断，不按关键词评分。
- [ ] 扩展契约前先写会被旧 suite 拒绝的 RED；再实现字段和 worker 隔离，未知观察路径仍拒绝。不得允许 suite 读取任意私密正文或仓库字段。
- [ ] 至少建立 24 个固定场景：正常8（原练胸/口语/具体追问/英文/显式语言/完整/短答/多轮）；权限8（跨用户/缺身份/未许可领域/撤销/路径/未知工具/伪造确认/恶意检索）；生命周期与错误8（非法协议/重复ID/重复读取/预算/审核故障/取消/账户删除/聊天过期）。每例写 expected 副作用及失败原因。
- [ ] 对旧模式与新模式可比样本配对；已知旧误拦截记录为 baseline failure，不通过修改旧输出掩盖。旧 C4 中“范围外零模型调用”的 mock 路径仅在仍适用的 legacy 检查，不要求 unified 自然语言理解也必须零调用。
- [ ] 运行 `& $taskPython -m pytest backend/tests/task_evaluation/test_unified_coach.py backend/tests/task_evaluation/test_contracts.py backend/tests/task_evaluation/test_network.py -q`，预期网络阻断、场景观测与计数一致。

### U6.2 完整回归、对照报告和交接

文件：新增 `docs/evaluation/unified-coach-acceptance.md`，更新 baseline、相关计划入口与运行文档。模式默认值不在未授权时切成 unified。

- [ ] 运行第 2 节完整后端、独立配置组、前端及 build；单独记录结果，不相加为“总覆盖”。任何未运行/跳过的平台测试如实列出。
- [ ] 执行新 mock suite：

```powershell
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/unified_coach.json --output .tmp/task-evaluation/unified-coach
if ($LASTEXITCODE -ne 0) { throw 'Unified coach replay failed' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Diff check failed' }
```

- [ ] 通过门槛：固定24场景均达预期；越权实际访问/未经确认正式写入/未审核草稿发布均为0；原练胸请求不再句式拒绝；语言/篇幅/取消/会话隔离兼容。此为该测试集结果，不宣传现实世界0风险。
- [ ] 报告每样本尝试、实际工具执行、重复命中、输入规模和耗时分布。mock 的 token估算/注入延迟只能证明计数与流程，不能给出真实供应商提速百分比。
- [ ] 提供下一步 S3/S4/S5 清单；真实模型评估须另获允许并设置调用/token/时间预算，当前 CLI live 仍未接通时不得把 `--allow-live` 写成已可用的验收命令。
- [ ] 检查点建议 `test(agent): record unified coach safety and performance evidence`；用户授权后再选择提交、推送、合并。合并前重新备份保留主库，不删除开发数据。

## 3. 设计覆盖与收口清单

| 设计要求 | 对应检查点 |
| --- | --- |
| 修复句式误拦截、范围/缺信息/安全分离 | U0.1/U0.2、U4.2 |
| 统一 Agent 与供应商解耦、连接门槛兼容 | U1.1、U4.1、U5.1 |
| 稳定提示词、追加有界状态、隐私投影 | U1.2、U3.1 |
| 渐进式 Skill、版本与资源限制 | U2.1/U2.2 |
| 确定性计算、不开放脚本/文件/SQL | U3.1/U3.2、U5.2 |
| 统一权限、撤销、跨领域许可 | U3.1、U4.1 |
| 预算/取消/重试、业务两轮不重置 | U4.1、U5.2 |
| 健康、隐私、证据、语言与长度 | U4.2、U6.1 |
| 保留 C体验、写入隔离与S3唯一状态机 | U5.1/U5.2 |
| 测试可信基线、对抗、同等安全性能测量 | U0.1、U6.1/U6.2 |

- [ ] 不把新增文档写成“功能已落地”。
- [ ] 没有按练胸/练腿继续增加任务专属工具或 workflow 分支。
- [ ] 没有偷偷新增任意脚本、沙箱或原生 function calling 准入。
- [ ] 没有新建一套权限许可、业务两轮预算或计划激活机制。
- [ ] 没有覆盖用户 dirty 文件、访问真实密钥、改主库、执行生产迁移或擅自发布。
- [ ] 指标报告附范围、失败样本、成本和局限；只有实测数字用于简历。

## 4. 执行交接

用户已审阅并授权 U0→U6，当前在隔离开发分支执行并保留验收证据；任何新增外部数据源、脚本执行或正式写入需求都先回到设计审查，不由实现者自行扩大权限。完成离线验收后保留分支与数据，等待用户决定提交/集成，不自动推进 S3 或生产发布。
