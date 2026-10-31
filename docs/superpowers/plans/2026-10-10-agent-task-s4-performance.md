# S4 统一执行观测、增量计算与质量约束性能对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans（默认顺序）或用户明确选择后的 subagent-driven-development。不得自动派子代理；复选框按RED/GREEN推进，提交/推送单独授权。

**Goal:** 在相同业务完成标准、授权和安全策略下，验证并减少统一Agent的模型往返、上下文和重复计算成本。

**Architecture:** S4-A先在已有教练/S2上补可审计基线；S3完成后加入计划任务。S4-B优化按需上下文与可信预取，S4-C按权威依赖做局部重算和有界复用，S4-D以同引擎reference/optimized配对报告收口。

**Tech Stack:** 现有Python AgentRuntime、Pydantic、SQLite、task_evaluation、pytest；不用新的通用工作流/缓存平台。

---

## 0. 依据、依赖与状态

**2026-10-31 状态覆盖：** A1/A2/B1/C1/C2/D1 对应实现及后续审查修补已进入 `main/f9e70fc`。旧“没有开始”为历史；原始 RED/GREEN 复选框不作为当前待办。C2 缓存继续默认关闭，尚无真实提速、token 或费用节省结论；后续按[当前验收清单](2026-10-31-agent-delivery-status.md)完成修补后的回归与配对回放，再进入 S5 授权评估。不以提前约定的提升数字决定是否保留优化。

2026-10-23重写，依据[路线重组设计](../specs/2026-10-23-agent-roadmap-reorganization-design.md)。没有开始本阶段代码或测得提速。旧版 `git show 3519f69:docs/superpowers/plans/2026-10-10-agent-task-s4-performance.md` 为历史，不是当前执行顺序。

检查点共6个：A1、A2、B1、C1、C2、D1。A1/A2可在S3前执行；B1可用已有教练开发但与C/D最终收口在S3之后；C的计划分支依赖新S3。S2继续使用原结构化录入流程，不能把它伪装成已迁移统一循环。

S5离线准入/标注可同时准备；真实探查只有另获明确授权且S5受控live链路实现后才可运行。Mock字符估算不是真实token/cost，不用合成sleep模拟供应商提速。

### 在隔离checkout初始化测试

```powershell
$taskRoot = (git rev-parse --show-toplevel).Trim()
Set-Location -LiteralPath $taskRoot
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath '.venv\Scripts\python.exe') {
    $taskPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
}
& $taskPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$env:DATA_DIR = Join-Path $taskRoot ".tmp\s4-seed-$taskStamp"
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
$env:OPENAI_API_KEY = ''
New-Item -ItemType Directory -Path $env:DATA_DIR | Out-Null
& $taskPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed' }
$taskBase = ".tmp/pytest-s4-$taskStamp"
```

以上只生成合成回归数据，不是主库备份。代码实施/分支建立前仍按AGENTS.md备份并隔离；此文档改写不执行命令。各pytest用不同basetemp，配置组另进程清变量。

## 1. 文件责任地图

| 新增文件 | 责任 |
| --- | --- |
| `backend/agent/tasks/execution_policy.py` | ExecutionStrategy/TaskFacts，确定性预取和可选短路径选择 |
| `backend/agent/context_policy.py` | 后置状态整理、受控Skill预取；不负责授权 |
| `backend/domain/task_dependencies.py` | 带版本的依赖键及受影响节点计算 |
| `backend/infrastructure/agent_runtime/task_cache.py` | 有界、按owner/scope隔离的确定性结果缓存 |
| `backend/task_evaluation/measurements.py` | 使用量/阶段时刻/中断的闭合数据模型 |
| `backend/task_evaluation/comparison.py` | 指纹配对、差值、分组P50/P95、质量门槛与失败成本 |
| `docs/evaluation/agent-performance-baseline.md` | 可复查的基线、优化、无收益及局限 |

已有修改：`backend/agent/{runtime,persistence,unified_coach,context_builder}.py`、`backend/agent/tools/executor.py`、`backend/agent/entry_workflow.py`、`backend/application/use_cases/interactive_entry.py`、S3新增 `plan_adjustment/session.py` 和 `use_cases/plan_adjustment.py`、`backend/task_evaluation/{contracts,runner,worker,budget,metrics,provenance,report,cli}.py`、`backend/config.py`。不因文件多而分拆无实际变化的模块，不重复建设身份/任务/预算真相。

## S4-A1：闭合计量与来源指纹（S3前）

**Create:** measurements.py、`backend/tests/task_evaluation/test_measurements.py`、`backend/tests/test_agent_attempt_metrics.py`。
**Modify:** runtime.py、persistence.py、tools/executor.py、task_evaluation的worker/metrics/provenance/report。

- [ ] **RED：** handler开始后被取消，不写TOOL_FINISHED，报告仍能区分已开始、未完成及usage未知；缓存命中不新增实际handler开始。现有“最终事件缺失等于未调用”的逻辑应失败。先用纯计量测试建立最小反馈：
```python
from backend.task_evaluation.measurements import UsageMeasurement

def test_unknown_usage_is_not_zero_or_mock_estimate():
    measured = UsageMeasurement(source='unknown', input_tokens=None,
        output_tokens=None, cached_input_tokens=None)
    assert measured.total_tokens is None
    assert measured.source != 'mock_estimate'
```
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_measurements.py backend/tests/test_agent_attempt_metrics.py -q --basetemp="$taskBase-a1-red"
```

- [ ] **定义计量类型：**
```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class UsageMeasurement:
    source: Literal['provider', 'mock_estimate', 'unknown']
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens
```
各数值非负strict int，未知必须None；cached_input为input的子集，不再加到total。实际provider total与本地估算分别保存，不能相互替代结算凭证。

- [ ] **记录实际边界：** 每次真实模型/handler尝试分配可信attempt_id，在操作实际开始前记录STARTED，结束记录COMPLETED/FAILED，取消清理后记录CANCELLED或标INCOMPLETE。仅进入队列不算真实handler开始；中断原生线程仍运行时不能提前标已清理。账本预留/settle继续复用Runtime和BatchBudget，不新计费。单独记录logical tool proposal、cache hit、transport retry、physical handler/model attempt，禁止相加成为一个含糊calls。
- [ ] **事件脱敏：** persistence白名单只接受已注册tool、阶段、受控ID、计数、版本hash、usage；不记query、record、prompt或key全文。进程崩溃导致缺终态时根据STARTED显示incomplete，不编造实际usage。
- [ ] **补指纹：** worker.safe_config_fingerprint必须加入coach_agent_mode、后续plan flags/存储模式/策略、语言/回答契约、安全配置。分离invariant（任务、输入、模型参数、权限、安全/回答要求、Skill/工具/算法版本、代码SHA）与treatment（策略、预取/压缩/复用配置）。prompt实际渲染hash保留为观测，不把预取改变的上下文误判成不同任务。
- [ ] **GREEN：** 使用同一FakeClock测量阶段；实际调用失败/重试/取消也进入计数；unknown与provider=0可区分；老事件无新payload字段仍可读但标覆盖不足。
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_measurements.py backend/tests/test_agent_attempt_metrics.py backend/tests/test_runtime_telemetry.py backend/tests/test_runtime_task_budget.py backend/tests/unified_coach -q --basetemp="$taskBase-a1-green"
```
建议检查点 `feat(eval): measure physical attempts and explicit token provenance`。

## S4-A2：同引擎参考策略、用例和配对基础（S3前）

**Create:** comparison.py、execution_policy.py、`backend/tests/task_evaluation/test_comparison.py`、`backend/tests/test_task_execution_policy.py`、`backend/task_evaluation/scenarios/performance_coach.json`。
**Modify:** config.py、CLI/worker/runner/contracts/report；更新baseline文档初始实测记录。

- [ ] **RED：** 不同engine mode、数据/Skill版本、授权或review配置拒配；空/0基线不输出提升；失败样本计成本但不进入成功延迟分布。纯算式测试：
```python
from backend.task_evaluation.comparison import reduction_percent

def test_reduction_requires_positive_baseline():
    assert reduction_percent(100.0, 75.0) == 25.0
    assert reduction_percent(0.0, 1.0) is None
```
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_comparison.py backend/tests/test_task_execution_policy.py -q --basetemp="$taskBase-a2-red"
```

- [ ] **实现策略模型：** ExecutionStrategy为reference/optimized；Settings `task_execution_strategy` 默认reference，固定到run/任务执行快照。TaskFacts包含task_kind、trusted_action、fields_complete、catalog_unambiguous、scope_verified、constraints_complete；事实由应用/校验器生成，不信模型说“简单”。A阶段optimized仍可与reference完全等价，不伪造优化收益。**该默认值不随2026-10-23"新引擎默认开启"决定改动**：它是对照实验的基线选择，翻成optimized会让S4失去可比对象；可见性开关与实验变量必须分开。
- [ ] **实现配对接口：** `pair_records(reference, optimized)`按 `case_id/version/repeat_index/invariant_fingerprint/cache_state`配对；不匹配返回有原因的拒配结果。`reduction_percent(baseline, optimized)`按正基线计算，可为负数表示退化。冷/热应用缓存分别配对，不以冷reference对热optimized宣传算法收益；Provider缓存不能由cold标志声称清空。
- [ ] **定义12个Coach场景：** 可信快捷动作、开放任务、首次训练建议、当前聊天追问、zh/en、必要追问、长但有效历史、过期历史过滤、权限不足、必要审核故障、取消/重试。Task 1 metrics能观察实际阶段，语义质量用S5标注，不按回答关键词打成功。S2复用interactive_entry suite，标task_kind=entry，不能合并引擎成功率。
- [ ] **扩展CLI（本步实现后才可用）：** `--strategy reference|optimized`、`--repeat`正整数、`--cache-state cold|warm`、`--compare REF OPT`只读。compare模式不要求suite、不构造Provider，输出matched/rejected/quality_gate和原始配对；执行模式仍需suite与显式预算。一次配对运行按case内交替两策略顺序，不先跑完全reference再完全optimized作为正式live结论。
- [ ] **GREEN与基线：** 模式/权限/安全相同；mock两策略使用同一场景内按策略声明的决策脚本，完整suite hash一致，但脚本只证明流程，不代替真实模型效果。已有CLI尚未支持这些选项，不能在实现前把help通过当能力存在。
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_comparison.py backend/tests/test_task_execution_policy.py backend/tests/task_evaluation/test_contracts.py backend/tests/task_evaluation/test_network.py -q --basetemp="$taskBase-a2-green"
& $taskPython -m backend.task_evaluation.cli --mode mock --strategy reference --repeat 3 --cache-state cold --suite backend/task_evaluation/scenarios/performance_coach.json --output ".tmp/task-evaluation/s4-coach-ref-$taskStamp" --max-calls 600 --max-tokens 2000000 --max-seconds 1200
```
建议 `feat(eval): establish matched unified agent performance baselines`。这一门禁完成即可进入S3，不以“还没有计划场景”阻塞已有Coach/S2基线。

## S4-B1：保持契约的上下文预取与有界状态

**Create:** context_policy.py、`backend/tests/unified_coach/test_context_policy.py`。
**Modify:** context_builder/unified_coach/coach_composition/skills目录读取；不能变更动作权限。

- [ ] **RED：** 同一可信快捷动作的optimized请求减少一次无价值发现，但当前问题、硬约束、授权、安全模式和输出篇幅相同；非可信用户写action名称不触发预取。测试脚本请求数、前缀及实际Provider输入，不仅测本地组装字符串。
- [ ] **定义纯策略接口：**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ContextPlan:
    resource_ids: tuple[str, ...] = ()
    include_verified_page_context: bool = False

def choose_context_plan(strategy, facts):
    if strategy == 'optimized' and facts.trusted_action and facts.scope_verified:
        return ContextPlan(resource_ids=('skill:today-explanation',),
                           include_verified_page_context=True)
    return ContextPlan()
```
此例仅对应已注册today explanation；真实实现用闭合trusted_action→resource表，不把任意action都映射today。facts.trusted_action在Task A2定义为已验证注册动作名或None，不接受前端自由字符串。预取目录仍验证release/digest，context只放必要授权投影，不因标识可信而信任页面任意正文。
- [ ] **整理上下文：** 稳定系统指令和工具schema顺序不变，动态SessionFrame在后部追加；不把时间改写到前缀。丢弃过期/跨聊天/撤销内容及其摘要；只对后部已完成observation做有来源、保留依赖与硬限制的有界整理。当前问题和必要约束放不下时受控失败，不静默删除安全要求。
- [ ] **算法与配置：** context_policy_version进入treatment及报告；reference禁用新增预取/整理但保留原U安全裁剪，optimized不能少提供业务所需证据。常用动作可预取，开放任务仍渐进发现；不增加复杂工具搜索平台，不只为cache稳定而保留隐私数据。
- [ ] **GREEN：** 原请求不因表达被挡；缺许可零读取；zh/en与brief/detailed不变；对长历史/快捷解释配对记录模型调用、实际input/output、峰值字符和回答质量。供应商cache usage缺失标unknown。
```powershell
& $taskPython -m pytest backend/tests/unified_coach/test_context_policy.py backend/tests/unified_coach/test_context_builder.py backend/tests/unified_coach/test_agent_loop.py backend/tests/test_safety_guard_contract.py -q --basetemp="$taskBase-b1-green"
```
若token减少但安全答案延迟增加，应如实报告并按场景保留reference；建议 `perf(agent): prefetch minimal trusted context without relaxing guards`。

## S4-C1：权威依赖与局部重算（计划分支依赖S3）

**Create:** task_dependencies.py、`backend/tests/domain/test_task_dependencies.py`。
**Modify:** `use_cases/interactive_entry.py`、`agent/entry_workflow.py`、S3 validation/session。

- [ ] **RED：** “面改粉”影响item-match→portion→nutrition→meal-total，但不影响奶茶；饮食候选修订不重生成仍有效的训练候选；同一约束版本改变后两个依赖域都重验。
- [ ] **实现最小数据与遍历：**
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DependencyKey:
    scope: str
    resource_id: str
    resource_revision: str
    constraints_revision: str
    catalog_revision: str
    processor_revision: str

def affected_nodes(changed, edges):
    affected = set(changed)
    pending = list(changed)
    while pending:
        for child in edges.get(pending.pop(), ()):
            if child not in affected:
                affected.add(child)
                pending.append(child)
    return frozenset(affected)
```
scope为public或绑定owner/task的内部命名，不让模型提供cache scope。图仅包含实际领域链，环存在时遍历仍结束，未知节点不扩大授权。
- [ ] **接线版本：** 食物/动作目录版本、条目revision、当前目标/限制版本及算法版本取权威仓储；没有权威版本的可变依赖一律重算。对计划，base/head/constraints变动先使候选不可确认，模型修复仍消耗原任务剩余轮次；不能以自动重建任务绕过。
- [ ] **减少的是重算而非验证：** unchanged域可复用已验证内容，但发布前联合硬约束、安全与确认时版本检查不省略。重用候选需已授权、未过期且依赖相同。记录invalidated/recomputed/reused节点数量与原因码，不记录节点私密正文。
- [ ] **GREEN：** 用相同数据的reference全重算与optimized局部重算，结果、数据库副作用、候选差异和正式确认完全一致；spy证明无关节点未调用。S2余额/两轮及S3冻结规则不变。
```powershell
& $taskPython -m pytest backend/tests/domain/test_task_dependencies.py backend/tests/test_plan_adjustment_service.py backend/tests/test_plan_adjustment_session.py backend/tests/test_smart_entry_confirmation.py -q --basetemp="$taskBase-c1-green"
```
建议 `perf(tasks): invalidate and recompute only affected dependencies`。

## S4-C2：有界确定性复用（有测量收益才启用）

**Create:** task_cache.py、`backend/tests/infrastructure/test_task_cache.py`。
**Modify:** composition、S2目录/换算接缝、S3已验证候选读取；不缓存最终确认或权限。

- [ ] **RED：** 相同查询不同owner不命中；版本变更miss；授权撤销即使数据已缓存也拒绝；取消中handler不把半成品入缓存。使用注入clock确定到期，不sleep。
- [ ] **定义接口：**
```python
class TaskResultCache:
    def __init__(self, *, max_entries=128, ttl_seconds=300, clock):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.entries = {}

    def get(self, key, *, authorize):
        authorize()  # 任何命中前都调用可信检查
        record = self.entries.get(key)
        if record is None or record[0] <= self.clock():
            self.entries.pop(key, None)
            return None
        from copy import deepcopy
        return deepcopy(record[1])
```
实现同一类的 `put(key, value)`、`invalidate_scope(scope)`、`clear()`：put完整成功后才写入、deepcopy、到期清理、容量满按最旧写入淘汰；clock用monotonic。key使用C1的全部DependencyKey，不只query字符串。明确None为miss，不能缓存None作为成功数据。
- [ ] **接线范围：** 公共目录匹配/确定性换算可public；私有任务候选仅owner+task+version。复用前检查lease、expiry、身份及scope；禁止跨用户缓存模型正文、缓存授权或将确认回执当成跳过事务的依据。进程内cache只是性能，进程重启和miss不改变正式真相。
- [ ] **生命周期：** delete_account及任务到期清理对应scope；不在导出/日志中写cache正文；候选被取消不得继续命中。无版本Adapter禁用该层。持久跨进程缓存不是本阶段默认范围。
- [ ] **GREEN与决策：**
```powershell
& $taskPython -m pytest backend/tests/infrastructure/test_task_cache.py backend/tests/domain/test_task_dependencies.py backend/tests/test_account_delete_api.py backend/tests/test_plan_adjustment_service.py -q --basetemp="$taskBase-c2-green"
```
先看冷/热实际收益；若无收益，保留代码的无缓存实现及局部重算，默认不启用。不得为了简历硬加Redis或并行读。建议 `perf(tasks): reuse versioned deterministic results within authorized scopes`。

## S4-D1：同质量、安全配对与报告

**Create:** `backend/tests/task_evaluation/test_performance_acceptance.py`、`backend/task_evaluation/scenarios/performance_plans.json`。
**Modify:** comparison/report/CLI、`docs/evaluation/agent-performance-baseline.md`。

- [ ] **RED：** 更快但硬约束/审核配置不一致不能通过；只有成功样本的成本不能代表每成功任务成本；未知usage不可生成真实费用。相同case缺一侧结果保留unmatched，不删除。
- [ ] **实现比较字段：** paired_count/unmatched_count/rejected_pairs、各业务成功/失败/恰当停止、P50/P95（最近秩并声明定义）、调用/token、成功任务成本含全部失败/重试；无成功时cost_per_success=None。提供样本范围和bootstrap区间或明确“样本不足、无区间”，不把预设固定样本量当统计充分证明。
- [ ] **实现质量门禁：** 确定性集合越权实际访问、重复写入、无效激活必须0；完整性/硬约束/未授权变更不能退化。真实语义质量/误拒由S5盲化标注，未运行live时只给流程结论。未知测量率和取消清理分开报告，不把未审核delta/loading算安全答案。
- [ ] **加入S3计划场景：** 单域、联合、局部修订、目标冲突、无解与过期/撤销；candidate_ms仅在类型、硬约束和必要审核通过后记。12个Coach、原S2、S3各分组，不混成总体平均速度。
- [ ] **GREEN与可重放对照（新增选项实现后执行）：**
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_performance_acceptance.py backend/tests/task_evaluation/test_comparison.py -q --basetemp="$taskBase-d1-green"
& $taskPython -m backend.task_evaluation.cli --mode mock --strategy optimized --repeat 3 --cache-state cold --suite backend/task_evaluation/scenarios/performance_coach.json --output ".tmp/task-evaluation/s4-coach-opt-$taskStamp" --max-calls 600 --max-tokens 2000000 --max-seconds 1200
& $taskPython -m backend.task_evaluation.cli --compare ".tmp/task-evaluation/s4-coach-ref-$taskStamp" ".tmp/task-evaluation/s4-coach-opt-$taskStamp" --output ".tmp/task-evaluation/s4-coach-compare-$taskStamp"
```
mock两目录用于命令/计数验证。正式live使用S5同一授权批次中的交替策略执行，不能据这两次顺序mock命令声称控制了供应商抖动。
- [ ] **完整收口：** 总计划的后端/独立配置/前端/构建和S3回放全部通过；报告原始pair、指纹、失败样本、未知成本、收益来源和无收益策略。真实模型探查未获授权时，明确待S5验证，不填写提速百分比。建议 `test(perf): enforce matched quality and safety performance evidence`。

## 2. 旧任务映射与完成边界

| 旧S4 | 新检查点 |
| --- | --- |
| Task 1路径与安全基线 | A1、A2、B1；录入短路径仅在确定性事实足够且实际收益成立时纳入B1，安全检查相同 |
| Task 2依赖/缓存 | C1、C2 |
| Task 3配对报告 | A2配对基础、D1最终门禁 |

S4离线完成意味着计量、策略与可复查对照成立，不等于真实Provider提速已成立；S5负责有授权的真实效果证据。关闭optimized策略不删除业务任务或计划，缓存miss不改变业务真相，任何优化都不能重置任务/轮次/预算。
