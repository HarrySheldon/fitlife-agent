# S1 任务与安全契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 建立共享任务语义和不可由模型扩大权限的数据边界。

**Architecture:** 新增独立任务契约与业务范围策略；复用已有 safety 风险审核，不改现有 safety/scope.py 的语境消歧含义。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---


## 执行约定

工作树：`D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor`。所有相对文件名均相对此目录。先读总设计和总入口计划。新文件标“新增”，现有文件标“修改”。文中的契约示例是测试/实现起点，不代表现有 API。
每个任务按 RED → 最小实现 → GREEN → 回归完成；先确认失败来自预期断言，不把导入/环境失败当作业务缺陷证据。一个任务可拆为多个小提交检查点，但提交前需获得用户授权，只暂存本任务文件。
不调用真实 Provider、不改生产数据。所有日期/时钟、网关和存储在测试中注入；不使用睡眠测试到期。

PowerShell 初始化（每个新终端）：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
```

测试文件尚未新增前不运行下列目标测试命令。先新增测试再运行，最小实现后重新运行同一命令，期望 PASS。若现有实现已经通过新测试，记录已有能力，不为制造 RED 破坏代码。

## 文件分工

新增 `backend/agent/tasks/__init__.py`、`contracts.py`、`input_contracts.py`、`capabilities.py`（均位于同一目录）；
新增 `backend/safety/business_scope.py`；
修改 `backend/agent/planner.py`、`backend/agent/contracts.py`（任务/run 关联）、`backend/agent/graph.py`、`backend/agent/workflow.py`、`backend/agent/model_payloads.py`、`backend/agent/structured_workflow.py`；
新增 `backend/agent/tasks/boundary_workflow.py`（固定范围回复的受守卫流程）；
修改 `backend/agent/runtime.py`、`backend/infrastructure/agent_runtime/memory_run_repository.py`、`backend/infrastructure/agent_runtime/sqlite_run_repository.py`（持久run关联）；
新增 `backend/tests/test_task_contracts.py`、`test_task_input_contracts.py`、`test_task_capabilities.py`、`test_task_business_scope.py`、`test_task_policy_wiring.py`。
S2/S3 负责将这些契约持久化并接入其公开入口；本阶段完成契约与当前 Planner 接线，不声称所有入口已迁移。

实际接线补充：新增 `tasks/lifecycle.py` 与 `test_task_lifecycle.py`、`test_task_scope_compatibility.py`、`test_structured_stage_payloads.py`；模型边界同步修改 `safety/context.py`、`safety/review.py`、`agent/semantic_review.py`、两个 OpenAI 适配器，以及现有智能录入/计划调整调用方。Memory 仓储直接承载扩展后的不可变快照，无需为文件清单制造额外修改。

### Task 1：任务版本与计数语义

2026-10-15 检查点：任务 1 已完成规格与代码质量复核。新增纯任务契约、不可变 run 关联、运行库 v2 兼容迁移和受控任务错误终态。目标回归 68 passed（3.55s），包括旧 `id`/`run_id` 布局和旧检查点。未新增任务存储；真实持久任务事务和恢复闭环属于 S2/S3。

- [x] test_task_contracts.py 写共享修订计数测试：

```python
import pytest
from backend.agent.tasks.contracts import next_repair_round

def test_repair_round_not_counted_per_module():
    assert next_repair_round(0) == 1
    assert next_repair_round(1) == 2
    with pytest.raises(ValueError, match="REPAIR_LIMIT"):
        next_repair_round(2)
```

- [x] RED：`& $taskPython -m pytest backend/tests/test_task_contracts.py -q`。
- [x] contracts.py 新增纯函数及持久数据类型：

```python
def next_repair_round(current: int) -> int:
    if current not in (0, 1):
        raise ValueError("REPAIR_LIMIT")
    return current + 1
```

TaskRef 定义 task_id/version；RepairRound 定义 round_id/index、pending_domains/completed_domains；TaskBudget 定义已消耗及预留 calls/tokens、预算上限。不得把纯函数当原子计数实现，原子预留由 S2/S3 仓储事务落实。
- [x] AgentCommand新增可选task_ref，普通chat保持None；AgentRunSnapshot新增task_id/task_version。Runtime创建run时复制关联，Memory/SQLite仓储读写一致。SQLite运行表按其现有初始化/迁移方式增加可空列，不能混用records迁移版本；回归旧运行记录与旧checkpoint可读。
- [x] 明确错误映射：不存在或他人资源404、旧版本409、同幂等键异请求409、过期410、预算耗尽受控终态；响应沿用 ApplicationError，不暴露资源主人。
- [x] GREEN：补负数计数、version 单调、重复 round_id 语义；取消/超时只改变当前 run，等待用户任务仍可读取。

### Task 2：业务范围与风险分轴

2026-10-15 检查点：任务 2 已通过规格和代码质量复核；范围/公开安全/旧检查点/可扩展分析器/工作流/应用入口回归 82 passed（6.15s）。明确无关和辅助回复在上下文读取前执行固定受守卫流程；Coach 原文与服务端页面意图分别处理。范围策略是受限语法与保守澄清，不是通用语义分类器，未测真实模型分类准确率。明确声明独立且各子句可判定的混合请求只保留原文健康子句，关联目标或未知句式澄清；原始输入风险审核仍先执行。

- [x] test_task_business_scope.py 测“帮我选股票”无档案/工具读取；“写代码久坐怎么安排训练”不因“代码”拒绝；混合有害任务正常部分不可与有害目标相连。
- [x] RED：`& $taskPython -m pytest backend/tests/test_task_business_scope.py -q`。
- [x] business_scope.py 定义 ScopeDecision(scope, allowed_subtasks, refusal_code, needs_clarification)，scope 为 in_scope/out_of_scope/mixed/unclear。明确产品帮助和寒暄允许；高置信无关走固定文案，其余交 Planner，不扩大关键词黑名单。
- [x] Planner 输出仅为建议，经 policy 产生 allowed_subtasks；风险审核继续调用现有 safety 链，不允许 scope=in_scope 覆盖高风险处置。下游只看到被允许子任务文本。
- [x] GREEN：对 spy repository/tool 断言拒绝路径调用次数为0；加入提示注入要求绕过业务范围的负例。

### Task 3：按阶段输入白名单与能力约束

2026-10-15 检查点：任务 3 已通过规格及代码质量复核；目标与旧安全/Provider/预算回归 59 passed（7.40s）。实际 Chat Completions/Responses 请求级测试覆盖身份清理、无关数据排除、必要过敏限制、审核输入与目录/RAG 注入；真实生成计划、字段 patch 和日期/周聚合事实有保留正例。已修复知识意图丢过敏限制、校验原因缺失、patch 被投影为空及集合路径缺索引。身份文本清理为有限规则，不声称通用去标识能力；真实授权持久化留在 S2/S3。任务 4 继续完成结构化入口和受控澄清接线。

实施中间回归（非验收）：任务 3 目标及旧安全/Provider/预算回归 53 passed（5.31s）。全量后端中间结果 1647 passed / 16 failed（569.81s），失败涉及范围规则对合法问题过度澄清、旧占位问题夹具和审核注入草稿的旧转发契约；将随最终入口接线修复并重新全量验证，不将该结果描述为阶段完成。

- [x] test_task_input_contracts.py 添加自由文本/嵌套值脱敏和字段排除测试；test_task_capabilities.py 添加模型伪造 user_id 与未授权 domain 的拒绝测试。
- [x] RED：`& $taskPython -m pytest backend/tests/test_task_input_contracts.py backend/tests/test_task_capabilities.py -q`。
- [x] input_contracts.py 分 EntryInput、TrainingInput、DietInput、CoordinatorInput、ReviewInput 五种业务 DTO，以及当前chat/coach使用的ChatInput，extra=forbid。字段依据总设计8.2；Builder 不接收全量 state 参数，只接收显式必需数据。ChatInput只含当前问题、允许意图、必要分析摘要/目标/限制、来源与校验结论，按意图选择；用户身份和完整记录不默认发出。
- [x] 能力纯内核：

```python
def require_domain(domain: str, authorized_domains: frozenset[str]) -> None:
    if domain not in authorized_domains:
        raise PermissionError("DOMAIN_NOT_AUTHORIZED")
```

capabilities.py 同时要求认证上下文传入 owner，仓储查询必须含 owner；领域许可来自持久化用户决定，不能从模型字符串构造。
- [x] Provider spy 断言实际 messages 没有姓名/联系方式/无关历史，必要过敏限制仍存在。自由文本身份信息使用现有清理能力；处理后若语义不够必须澄清，不能静默丢限制。
- [x] GREEN：覆盖目录/RAG 注入、旧缓存用户切换、Reviewer 只见必要正文；所有新网关调用有输入构建器。

### Task 4：现有入口接线与生命周期契约

串行拆为 4a（结构化入口、公开澄清错误、Writer 必要初始事实）与 4b（生命周期纯契约、范围性能及全量兼容性），均已通过规格与质量复核。4a 组合回归 105 passed（9.04s）；空计划输入、必需语义被清理均在 Provider 解析前返回受控 422，运行记录保留有界错误码。4b 组合回归 100 passed（5.68s）。中文修饰语重叠回溯已通过原子匹配修复，对抗规模输入只在有超时保护的子进程内测试；最后的测试保护回归 19 passed（2.45s）。

- [x] test_task_policy_wiring.py通过真实Runtime公开入口与spy仓储测试：明显无关请求不调用context_loader/read_profile/retriever；正常健康问题仍执行必需守卫；typed suggestion无法覆盖权限；Chat Writer实际Provider messages符合ChatInput。
- [x] RED：`& $taskPython -m pytest backend/tests/test_task_policy_wiring.py -q`。
- [x] 在graph.py的_LazyFitLifeWorkflow.execute加载业务上下文之前进行范围准入。不能只在workflow.py Planner后拦截，因为当前context_loader已经提前读数据。范围判断使用原始用户任务与页面意图分字段，不能让自动生成的Coach模板遮盖无关用户问题。
- [x] 固定范围回复通过boundary_workflow执行input_guard/context_guard/safety_reviewer，兼容verify_guard_steps顺序并记录run；不读取用户档案。工作流内范围未确定则Planner判定后再决定profile/analysis/retrieval，普通产品帮助不强制load_profile。
- [x] 将model_payloads构建入口换为任务专用最小字段投影，再经已有sanitize_context，Provider仍发送清理后的同一载荷。structured_workflow只接受通过DTO构造的业务上下文，不能由模型字段决定allowlist；用现有Provider接线测试保证清理结果没有在Adapter层被重建为全量state。
- [x] lifecycle约定定义：账户删除使新任务不可恢复；用户导出包含业务草稿；到期410不依赖物理清理。此时先测纯状态/访问契约，S2/S3有真实存储后补账户API集成证据，不在S1写无法运行的新表测试。
- [x] 将“敏感业务草稿”和“诊断事件”分别定义保留字段；诊断只留类别/版本/计数/时间/task与run ID。持久化接线在 S2/S3 与新表一起完成，不能在本阶段报告存储闭环已完成。
- [x] 运行任务契约测试及旧安全接线回归：

```powershell
& $taskPython -m pytest backend/tests/test_task_contracts.py backend/tests/test_task_input_contracts.py backend/tests/test_task_capabilities.py backend/tests/test_task_business_scope.py backend/tests/test_task_policy_wiring.py backend/tests/test_safety_public_wiring.py backend/tests/test_safety_write_invariant.py backend/tests/test_safety_writer_payload_reaches_provider.py -q
```

- [x] 形成检查点：范围策略、风险审核、授权、最小数据各自有独立失败证据，不以一个分类结果替代全部控制。

## 最终验收（2026-10-15）

S1 四个任务完成，分任务规格/代码质量复核及最终跨模块集成审查通过，无剩余重要发现。工作树仍为 `.worktrees/agent-runtime-refactor`、分支 `codex/agent-runtime-refactor`；原验收基线为 `e3027f6` 加 S1 变更，2026-10-15 已提交为 `eff4527`，尚未推送。提交前追加复验任务契约、DTO、范围、权限、守卫、生命周期、结构化载荷与迁移套件，129 passed（3.96 秒，`.tmp/s1-precommit-20261015b`）。未修改 main，未调用真实 Provider。

最终集成审查额外复现并修复了旧运行库并发初始化冲突：`BEGIN IMMEDIATE` 现在覆盖版本/表结构检查、旧主键迁移、新增列和版本写入，使用单条 DDL 执行以避免 `executescript` 提前提交。相同的 20 轮双构造器复现，修复前 20 次失败、修复后 0 次失败；新增 `id`、`run_id`、新库三类并发和重复初始化回归。原始风险绕过的审查推断经 Runtime 外层原文守卫核对后撤回，另补精确混合风险公开入口负例，未削弱任何守卫。

最终证据（均为最新迁移修复之后）：

- 完整后端 **1719 passed**，564.96s，命令：`& $taskPython -m pytest backend/tests -q --basetemp .tmp/s1-full-migration-reviewed -p no:cacheprovider`。
- 本计划指定的契约与旧安全接线套件 **99 passed**，2.95s，`--basetemp .tmp/s1-plan-migration-reviewed`。
- 迁移、持久化、公开策略与检查点专项 **68 passed**，4.91s，`--basetemp .tmp/s1-migration-concurrent-final`。
- 前端 **36 files / 229 passed**，53.82s；生产构建成功，17.34s。
- S0 六类离线回放 **6/6 passed**，CLI 退出码 0，清理状态全部 `completed`。命令：`& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/baseline.json --output .tmp/task-evaluation/s1-migration-reviewed-20261015`；报告位于该目录的 `report.json` 与 `report.md`。
- `git diff --check` 通过。保留已有 Starlette/httpx 提醒和前端大 chunk 警告，不将其计为业务失败。

运行与边界说明见 `docs/agent-task-contracts.md`。范围判定和身份文本清理均为有界规则；Mock/契约通过不代表真实模型安全率、健康效果或性能提升百分比。S2/S3 的任务持久化、恢复 UI、领域同意与原子确认尚未实施；新保留期限未在本阶段设置。
