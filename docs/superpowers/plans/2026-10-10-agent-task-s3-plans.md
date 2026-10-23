# S3 受约束规划、有限修订与可靠确认 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans（默认顺序）或用户明确选择后的 subagent-driven-development。不得自动委派；每步使用复选框，先RED再GREEN，提交/推送单独授权。

**Goal:** 复用统一Agent，把训练/饮食需求转换为有类型、受授权和约束控制的候选，通过整任务共享两轮修订和用户确认可靠落地。

**Architecture:** 同一call/ask/final循环接入TaskSession策略与封闭工具目录；领域模块只计算/校验，不持有Gateway。持久任务拥有阶段、许可、轮次及候选，SQLite事务拥有正式激活；教练和计划页使用同一Interface。

**Tech Stack:** Python、Pydantic、FastAPI、SQLite、pytest、React/TypeScript/Vitest、现有AgentRuntime与task_evaluation。

---

## 0. 当前状态、依据与执行前置

2026-10-23重写。依据：[路线重组设计](../specs/2026-10-23-agent-roadmap-reorganization-design.md)及[U设计](../specs/2026-10-22-unified-coach-agent-design.md)。本文件为待执行计划；没有开始S3代码、迁移或真实调用。旧版可用 `git show 3519f69:docs/superpowers/plans/2026-10-10-agent-task-s3-plans.md` 查阅，不将旧待办当作已完成。

先完成[S4-A基线](2026-10-10-agent-task-s4-performance.md)，再执行本文。Task 1–8是8个检查点，不是8次模型调用；替代旧5项映射见文末。只改文档无需创建工作树；代码实施先遵循AGENTS.md备份主业务/Runtime数据库、核验完整性和checksum、建立隔离开发数据，检查挂载/路径不指向主库。保留主工作区已有transport修改。

### 公共测试初始化（在隔离开发checkout执行，不在本轮运行）

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
$env:DATA_DIR = Join-Path $taskRoot ".tmp\s3-seed-$taskStamp"
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
$env:OPENAI_API_KEY = ''
New-Item -ItemType Directory -Path $env:DATA_DIR | Out-Null
& $taskPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed' }
$taskBase = ".tmp/pytest-s3-$taskStamp"
```

后续命令依赖以上变量；每次pytest使用不同basetemp后缀。目标数由实际收集决定，不预写固定通过数。配置组另起进程清除覆盖变量。数据库/API变化后运行总计划的完整门禁；所有Mock测试禁止网络与真实密钥。

## 1. 文件责任地图与统一类型

| 新增路径 | 唯一责任 |
| --- | --- |
| `backend/domain/plan_adjustment.py` | 有限Patch、CandidateBundle、硬/偏好约束、类型和差异 |
| `backend/application/ports/plan_adjustment_repository.py` | 持久TaskSnapshot、任务/许可/round/候选CAS契约 |
| `backend/infrastructure/repositories/sqlite_plan_adjustment_repository.py` | 实现任务事务，不调用模型 |
| `backend/agent/task_session.py` | TaskSession、SessionFrame、AdviceSession；通用循环接缝 |
| `backend/agent/tools/spec.py` | ToolSpec：参数、效果、授权与handler |
| `backend/agent/plan_adjustment/session.py` | PlanTaskSession：可信阶段、轮次预留和结果投影 |
| `backend/agent/plan_adjustment/tools.py` | 基准只读、候选提交两个受控handler |
| `backend/agent/plan_adjustment/validation.py` | 确定性逐域及联合校验，不持有Gateway |
| `backend/application/use_cases/plan_adjustment.py` | PlanAdjustmentService：业务入口、等待/执行/确认 |
| `backend/infrastructure/repositories/sqlite_plan_repository.py` | 统一正式历史和head；实现既有PlanRepository |
| `backend/infrastructure/repositories/plan_repository_factory.py` | file/sqlite唯一权威源选择与导入状态检查 |
| `backend/infrastructure/sqlite/import_legacy_plans.py` | 显式清点、dry-run和幂等导入 |
| `backend/api/plan_adjustment.py`、`plan_adjustment_schemas.py` | 认证HTTP输入/响应投影 |
| `frontend/src/components/plan/PlanAdjustmentDialog.tsx`、`PlanDiff.tsx`、`PlanTaskCard.tsx` | 两入口共用许可、差异、确认与冲突 |
| `frontend/src/services/planAdjustmentApi.ts`、`frontend/src/types/planAdjustment.ts` | 有版本和幂等的前端契约 |

已有修改点：`backend/agent/{unified_coach,coach_composition,coach_delivery,contracts,context_builder}.py`、`backend/agent/tools/{registry,executor,contracts}.py`、`backend/agent/tasks/capabilities.py`、`backend/agent/prompts/coach_system.md`、`backend/coach_skills/training-plan/`；`backend/infrastructure/sqlite/schema.py`、`backend/application/ports/plan_repository.py`、`backend/application/use_cases/{plans,export_account_data,delete_account,coach_turns}.py`、`backend/infrastructure/agent_runtime/coach_answer_adapter.py`、`backend/api/{plan,coach_conversations}.py`、`backend/config.py`、`backend/main.py`。现有智能录入不在此阶段重写为统一循环。

### 全任务一致的术语和签名

以下均为拟新增契约，不是当前可调用能力；实现时在指定任务定义，后续不能另起同义字段。

```python
# domain/plan_adjustment.py
from typing import Literal
Domain = Literal['training', 'diet']
# CandidateBundle: strict Pydantic, patches: tuple[Patch, ...], max 14项
# CandidateVerdict: candidate_id,digest,passed,failed_domains,violations,dependency_digest
# TaskSnapshot: ports/plan_adjustment_repository.py 中唯一持久投影
# fields: task_id,version,state,base_plan_id,base_head_revision,read_domains,
# change_domains,constraint_digest,candidate_id,candidate_digest,repair_rounds,
# active_round_id,operation_id,expires_at,candidate_expires_at
```

TaskSnapshot同时保存可信硬约束快照及权威版本引用；owner绑定在仓储查询中，不进入模型输入。所有标识非空；aware UTC时间；版本正整数；状态有限枚举；不接受额外字段或NaN/Inf。CandidateVerdict的violations为有界的 `code/domain/path` 数据，不能把任意仓储异常或私密全文回传模型。

## Task 1：Patch、动作权限与候选领域校验

**Create:** `backend/domain/plan_adjustment.py`、`backend/tests/domain/test_plan_adjustment.py`。
**Modify:** `backend/agent/tasks/capabilities.py`、`backend/agent/validator.py`（仅复用所需验证，不改既有医学阈值）。

- [ ] **RED：** 在新测试文件放入以下最小行为回归，然后运行：
```python
from copy import deepcopy
import pytest
from backend.domain.plan_adjustment import Patch, apply_patches

def test_training_grant_does_not_authorize_diet_change():
    base = {'workout_plan': {'days': []}, 'diet_plan': {'meals': ['original']}}
    before = deepcopy(base)
    patch = Patch(domain='training', path=('diet_plan', 'meals'),
                  old_value=['original'], new_value=['changed'],
                  reason='wrong domain', evidence_refs=())
    with pytest.raises(ValueError, match='PATCH_SCOPE'):
        apply_patches(base, (patch,), frozenset({'training'}))
    assert base == before
```
```powershell
& $taskPython -m pytest backend/tests/domain/test_plan_adjustment.py -q --basetemp="$taskBase-t1-red"
```
预期最初因生产模块缺失或正确行为断言失败；导入失败不是最终有效RED，最小接口落下后必须再次看到越权行为断言失败，再实现拒绝。

- [ ] **实现最小纯函数：** `Patch`为extra=forbid、frozen模型，包含domain/path/old_value/new_value/reason/evidence_refs。`apply_patches(base, patches, change_domains) -> dict`先deepcopy、校验全部patch再应用，不部分提交。path第一版只允许 `workout_plan.days[index]` 和 `diet_plan.meals[index]` 的现存非负索引替换；不增删数组、不替换目标/validation/trace，不接受JSON Pointer字符串。old_value不相等报 `PATCH_STALE`；域不匹配报 `PATCH_SCOPE`；同一path重复报 `PATCH_DUPLICATE`。
- [ ] **实现与当前计划相容的类型：** 训练日新值闭合字段 `day/type/focus/intensity/exercises`，枚举及动作词汇从已发布模板/动作目录验证；饮食餐次新值为有界纯文本，不作为营养数字事实。禁HTML、外链、指令性元数据。兼容当前GeneratedPlan的string meals与dict training days；未知历史结构保留可读，但拒绝自动调整并返回 `PLAN_FORMAT_UNSUPPORTED`。不擅自迁移成全新业务schema。
- [ ] **实现约束与差异：** `validate_bundle(base, bundle, constraints) -> CandidateVerdict`调用逐域检查、既有 `validate_generated_plan` 和明确跨域检查；硬约束含目标保持、过敏/限制、时间/器械及禁止动作，缺失必要限制返回待追问，不编造默认事实。代码重算差异和数值，不信模型reason/validation。类型/结构校验不等于临床正确性。
- [ ] **补测：** 未改领域深相等、数值/单位不合法、负索引、目标修改、重复path、old_value过时、无变更、当前模板可读。加入“read diet但change仅training”的拒写断言。GREEN命令：
```powershell
& $taskPython -m pytest backend/tests/domain/test_plan_adjustment.py backend/tests/test_task_capabilities.py backend/tests/test_safety_write_invariant.py -q --basetemp="$taskBase-t1-green"
```
预期所有越权patch拒绝且原输入不变；不通过改测试为允许来收口。检查点建议 `feat(plan): define typed scoped candidate patches`，用户授权才提交。

## Task 2：持久任务、许可和修订轮次CAS

**Create:** `backend/application/ports/plan_adjustment_repository.py`、`backend/infrastructure/repositories/sqlite_plan_adjustment_repository.py`、`backend/tests/infrastructure/test_plan_task_repository.py`。
**Modify:** `backend/infrastructure/sqlite/schema.py`；复用 `sqlite_task_budget_repository.py`，不新建预算表。

- [ ] **RED：** 用 `SQLiteDatabase(tmp_path / 'plan.sqlite3')` + `run_migrations(db, RECORDS_MIGRATIONS)`，创建新仓储。测试下列契约：
```python
def test_same_create_operation_returns_same_task(tmp_path):
    from backend.infrastructure.sqlite.database import SQLiteDatabase
    from backend.infrastructure.sqlite.migrations import run_migrations
    from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
    from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import SQLitePlanAdjustmentRepository
    db = SQLiteDatabase(tmp_path / 'plan.sqlite3')
    run_migrations(db, RECORDS_MIGRATIONS)
    repo = SQLitePlanAdjustmentRepository(db)
    task = repo.create_task('alice', base_plan_id='p1', base_head_revision=1,
        read_domains=frozenset({'training'}), change_domains=frozenset({'training'}),
        constraints={}, key='create-1')
    replay = repo.create_task('alice', base_plan_id='p1', base_head_revision=1,
        read_domains=frozenset({'training'}), change_domains=frozenset({'training'}),
        constraints={}, key='create-1')
    assert task.task_id == replay.task_id
    assert task.version == replay.version
    assert replay.repair_rounds == 0
```
测试用create_task必须显式允许空constraints用于仓储层，应用层不得以它绕过Task 1的必要字段验证。
```powershell
& $taskPython -m pytest backend/tests/infrastructure/test_plan_task_repository.py -q --basetemp="$taskBase-t2-red"
```

- [ ] **实现仓储Interface：** `create_task(owner, *, base_plan_id, base_head_revision, read_domains, change_domains, constraints, key) -> TaskSnapshot`；`get(owner, task_id)`；`grant(owner, task_id, expected_version, read_domains, change_domains, key)`；`reserve_repair_round(owner, task_id, expected_version, operation_id, failed_domains)`；`submit_bundle(owner, task_id, expected_version, operation_id, bundle, verdict)`；`transition(owner, task_id, expected_version, state, key)`；`delete_user_data(owner)`。仓储不创建模型或解释用户文本。create的ID/clock由可注入生成器提供；默认期限从Settings快照：任务30天、候选30分钟，确认时仍以快照校验。
- [ ] **追加迁移：** `plan_adjustment_sessions`、`plan_task_permissions`、`plan_repair_rounds`、`plan_candidate_submissions`、`plan_task_receipts`。所有唯一约束包含owner/task；round的operation_id与index分别唯一；记录已提交bundle digest、逐域结果和依赖指纹。修改既有迁移会破坏历史checksum，只允许追加迁移。
- [ ] **实现事务顺序：** 幂等回执匹配在expected_version检查前；同键异指纹 `IDEMPOTENCY_CONFLICT`；相同预留不重复计数。首次候选round=0，repair只能1/2，未结束轮不能预留下轮；每轮只接纳一个不同bundle，校验失败也消耗本轮。reserve发生在下一次修订模型调用前，不在模型生成后才计数。相同操作可恢复pending工作，不能重新接纳另一候选。
- [ ] **补状态与并发：** collecting、awaiting_scope_permission、generating、repairing、awaiting_confirmation、awaiting_user_decision、activated、cancelled、expired。读权限不隐含写草稿权限；生成后改目标/范围返回 `REQUIRES_NEW_TASK`，只有用户能明确发起关联新任务。未知/他人task同404。两进程争最后一轮只一成功；Windows用spawn+屏障，不靠sleep确定先后。
- [ ] **GREEN：** 再测删除、过期访问、并发预留、同round恢复、换run不重置、旧version冲突；TaskBudgetBinding复用已有task_id做持久预算，unknown usage保守收费。
```powershell
& $taskPython -m pytest backend/tests/infrastructure/test_plan_task_repository.py backend/tests/infrastructure/test_task_budget_repository.py backend/tests/test_task_contracts.py -q --basetemp="$taskBase-t2-green"
```
建议检查点 `feat(plan): persist scoped tasks and shared repair rounds`。

## Task 3：封闭工具目录和通用TaskSession接缝

**Create:** `backend/agent/task_session.py`、`backend/agent/tools/spec.py`、`backend/tests/unified_coach/test_task_session.py`、`backend/tests/unified_coach/test_tool_registry.py`。
**Modify:** `backend/agent/tools/{registry,executor}.py`、`backend/agent/unified_coach.py`。

- [ ] **RED：** 注册测试专用ToolSpec，驱动现有统一循环执行它；断言不需修改循环或按工具名新增if。另测把draft_write标为read_only时注册失败。AdviceSession返回空任务状态，原U行为不变。
- [ ] **定义最小接口：**
```python
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol
from backend.agent.decision import AgentDecision

@dataclass(frozen=True)
class SessionFrame:
    revision: int
    phase: str
    state: Mapping[str, object]

class TaskSession(Protocol):
    def before_decision(self) -> SessionFrame: ...
    def after_decision(self, decision: AgentDecision) -> None: ...
    def before_delivery(self, decision: AgentDecision) -> Mapping[str, object]: ...

Effect = Literal['public_read', 'private_read', 'calculate', 'draft_write']
```
`before_decision`在实际Gateway回调前重验，也在每轮进入时调用；轮次只由持久CAS改变，重复检查无副作用。`after_decision`只观察已校验的决策，不按模型文字授予权限。`before_delivery`返回可信receipt投影，模型不能构造它。AdviceSession三方法均不产生任务副作用。

- [ ] **定义ToolSpec：** 固定 `name/args_model/effect/authorize/handler/replay`；authorize使用principal、已解析args和可信session检查读/写草稿动作。handler只拿绑定的最小依赖，不拿完整仓储或可选择owner的接口。registry为进程内审核发布集合，无注册/安装工具。旧五工具迁移后授权与结果限额保持不变。
- [ ] **接线：** executor只作通用解析→取消/预算→授权→已声明handler→受控observation；工具计费仍过Runtime。draft_write声明replay='never'，业务幂等由Task 2的可信operation_id保证；不得沿用所有工具 `context.tool(..., 'safe', ...)` 自动重放。描述中的read_only从effect生成，不能由模型参数控制。
- [ ] **错误分类：** typed候选校验失败用status=ok且data.validation.passed=false；越权status=denied；非法协议按现有连续失败上限。Skill版本改变、账户删除、撤销为终态访问失败。最终文本不再作为候选内容。
- [ ] **GREEN：** 原五工具、缓存前复验、重复call_id、未知工具拒绝、两次非法协议、预算预留、取消均通过；模拟draft_write handler提交后断线，Runtime不能自动重放。
```powershell
& $taskPython -m pytest backend/tests/unified_coach backend/tests/test_runtime_task_budget.py backend/tests/test_agent_runtime_controls.py -q --basetemp="$taskBase-t3-green"
```
建议 `refactor(agent): add closed tool specs and task session seam`。

## Task 4：PlanTaskSession、受控候选能力与渐进Skill

**Create:** `backend/agent/plan_adjustment/{__init__,session,tools}.py`、`backend/coach_skills/plan-adjustment/{skill.json,SKILL.md}`、`backend/tests/test_plan_adjustment_session.py`。
**Modify:** `backend/agent/{coach_composition,context_builder,contracts,coach_delivery}.py`、`backend/agent/tools/registry.py`。

- [ ] **RED：** 复用现有ScriptedDecisionGateway测试手法，脚本按 `plan.read_base → plan.submit_candidate → final`；未绑任务执行两个新工具均拒绝且仓储spy零访问。正文写“已激活”无可信回执必须拒绝。
- [ ] **定义两个封闭工具：** `plan.read_base(fields: list[str])`只读绑定任务的基准，fields白名单为需要的领域子树和约束引用；`plan.submit_candidate(patches: list[Patch])`最多14项，不接受owner/task/round/confirmed/validation/trace。read所返回的领域按read_domains过滤；submit按change_domains检查。operation_id、task/round/version由PlanTaskSession绑定，不取call_id作业务幂等键。
- [ ] **实现会话策略：** `PlanTaskSession(repository, owner, task_id, validation, reviewer)`中repository为Task 2仓储；validation为Task 5的确定性校验接口。`before_decision`读最新task并检查账户/模式/lease/expiry；见failed candidate且可修订时先CAS预留round，再返回待修域与必要violations；无预算/两轮耗尽时停止模型执行并投影awaiting_user_decision。
- [ ] **分离候选与交付：** 候选submit必须完成Task 1/5验证和配置要求的审核后才成为可确认候选。`before_delivery`只能投影仓储中已审候选的ID/digest/version/有效期；FinalDecision只解释，不能用evidence_refs伪造candidate。若无候选，正常ask可等待用户，final不能标成计划成功。AgentResult新增可选typed `task_receipt`字段，默认None；公共API只返回经认证投影，不能塞任意trace对象充当收据。
- [ ] **上下文接线：** AgentCommand.task_ref保持已有TaskRef；SessionFrame追加为带来源的后置状态，不修改稳定系统前缀，不默认加载两域。Skill说明读取/候选/两轮/停机，不能激活。自愿跨域请求只产生许可等待，模型无grant/create_task/activate工具。模型实际转发前复验授权，不靠旧快照。
- [ ] **GREEN与扩展证明：** 成功读取/submit后正式计划不变；他人/旧task/伪round注入失败；训练单改看不到饮食明细；新增Skill不改循环；普通U聊天与S2入口不因未持有session失败。
```powershell
& $taskPython -m pytest backend/tests/test_plan_adjustment_session.py backend/tests/unified_coach backend/tests/test_structured_runtime.py -q --basetemp="$taskBase-t4-green"
```
建议 `feat(agent): bind plan candidates to trusted task sessions`。Task 4生产接线在Task 5验证实现前保持关闭，不能把临时总是通过的validator发布为功能。

## Task 5：确定性联合验证与有限修订闭环

**Create:** `backend/agent/plan_adjustment/validation.py`、`backend/application/use_cases/plan_adjustment.py`、`backend/tests/test_plan_adjustment_service.py`。
**Modify:** Task 4 session、`backend/agent/semantic_review.py`（必要时复用schema与预算，不新建Reviewer循环）。

- [ ] **RED：** 一个真实Task 2仓储任务配ScriptedDecisionGateway，初始两域失败、R1两域提交后训练通过、R2仅饮食提交后通过；断言仓储repair_rounds=2、训练候选digest在R2不变、最终候选尚未激活。具体script用Task 4两个工具和合法Patch，不模拟不存在的training.generate/diet.repair方法。
- [ ] **实现纯验证接口：** `PlanValidation.evaluate(base, bundle, constraints) -> CandidateVerdict`，从旧基准按Task 1规则合并、重算营养/训练派生数据、逐域及联合验证。校验目标版本、可用时间/器械/禁止动作及过敏；必要限制缺失输出具体待问字段。训练/饮食模块不含parse_structured/decide。
- [ ] **实现应用接口：** `PlanAdjustmentService.start(owner, base_plan_id, read_domains, change_domains, instructions, key)`、`get(owner, task_id)`、`grant(owner, task_id, expected_version, read_domains, change_domains, decision, key)`、`answer(owner, task_id, expected_version, answers, key)`、`execute(owner, task_id, expected_version, key)`、`confirm(owner, task_id, expected_version, expected_head_revision, candidate_digest, key)`、`cancel(owner, task_id, expected_version, key)`。confirm在Task 6之前明确返回未启用，不提供文件绕行。execute构建同一Runtime+TaskBudgetBinding，不循环创建新Runtime/新任务。
- [ ] **实现冻结与反馈：** 依赖未变的合格域只确定性重验；跨域冲突需要修已合格域时明确把它标为失败依赖，修订前记录原因，不静默改写。无解→awaiting_user_decision；必要审核失败不发布未经审候选；拒绝型风险不进入自动修复。物理调用与业务轮分开记，max12决策等run预算仍生效。
- [ ] **补故障测试：** 二次错误协议结束run但不清任务额度；网络重试不加轮；round已预留/submit前断开可恢复同轮；submit后响应丢失重放同候选；额度耗尽、不可满足、拒diet零读取/调用、reviewer不可用、等待释放槽、晚到结果不发布。
- [ ] **GREEN：**
```powershell
& $taskPython -m pytest backend/tests/test_plan_adjustment_service.py backend/tests/test_plan_adjustment_session.py backend/tests/test_safety_review_failure_disposition.py backend/tests/test_runtime_task_budget.py -q --basetemp="$taskBase-t5-green"
```
建议 `feat(plan): validate and repair only failing candidate domains`。

## Task 6：正式计划单一权威源、原子确认及兼容导入

**Create:** 文件地图中的SQLitePlanRepository、factory、import模块；`backend/tests/infrastructure/test_sqlite_plan_activation.py`、`test_legacy_plan_import.py`、`test_plan_repository_factory.py`。
**Modify:** `schema.py`、`ports/plan_repository.py`、`use_cases/plans.py`、`sqlite_profile_target_repository.py`、`use_cases/{delete_account,export_account_data}.py`、`backend/api/plan.py`、`backend/infrastructure/agent_runtime/coach_answer_adapter.py`。

- [ ] **RED：** 创建p1与候选c1，两个spawn进程使用屏障同时确认同一head；断言只有一个新head版本且p1深相等。另测同键重放不增plan数量、不同候选使用旧head返回 `PLAN_BASE_STALE`。断点故障注入在INSERT plan/UPDATE head/INSERT receipt各处验证事务全回滚。
- [ ] **追加迁移与完整仓储：** plans、plan_heads、plan_activation_receipts；PlanRepository保留save/list/get/save_draft/get_draft/take_draft并增加 `current_head(owner)`。SQLitePlanRepository仅读写确定性存储；保存历史不可覆盖同ID异内容；新旧生成/list/get/激活及Coach的plan解释均从factory取得同一仓储，不残留硬编码FilePlanRepository权威读取。
- [ ] **实现确认事务：**
```text
BEGIN IMMEDIATE
  owner/key查回执；同key异指纹冲突
  读task、候选、head、SQLite档案/目标版本
  检查owner、read/change许可、期限、候选digest、task/head/constraint版本
  代码重验候选及当前安全策略；不构造或调用Provider
  INSERT不可变新plan；UPDATE head WHERE revision = expected_head_revision
  UPDATE task activated；INSERT幂等回执
COMMIT
```
安全策略收紧到必须额外模型审核时，本次confirm不在事务内调用模型：返回 `CANDIDATE_REVIEW_REQUIRED`、禁用确认，用户显式execute在原任务剩余预算中再审。外部文件仍是某硬约束权威源时，先将该写流程版本化纳入SQLite，否则 `CONSTRAINT_SOURCE_UNVERSIONED` 拒绝激活。
- [ ] **实现唯一源选择：** plan_storage_mode=file默认，sqlite仅对import完成且校验一致用户启用；配置组合错误报 `CONFIGURATION_INVALID`。导入保留id/时间/based_on和draft，head按旧规则latest activated_at、同时间plan_id稳定排序生成并报告；无owner绑定文件拒绝导入。命令 `python -m backend.infrastructure.sqlite.import_legacy_plans --data-dir <isolated-path> --dry-run` 只读清点；`--apply`显式事务导入，不自动在请求中迁移、不删文件、同ID异内容冲突。
- [ ] **生命周期：** 删除覆盖任务/轮次/候选/receipt/正式计划及预算且只本用户；导出从权威仓储取历史和任务。与账户lifecycle guard共同验证确认/删除竞争，不依赖threading.Lock代替跨进程CAS；过期任务访问先拒绝，后台清理延后不改变权限。关闭入口不删除正式历史。
- [ ] **GREEN和副本验证：**
```powershell
& $taskPython -m pytest backend/tests/infrastructure/test_sqlite_plan_activation.py backend/tests/infrastructure/test_legacy_plan_import.py backend/tests/infrastructure/test_plan_repository_factory.py backend/tests/application/test_plans.py backend/tests/test_account_delete_api.py -q --basetemp="$taskBase-t6-green"
```
在合成目录执行dry-run/apply/重复apply并比较历史/head/owner计数；正式迁移另行授权且再次备份。建议 `feat(plan): confirm versioned candidates atomically`。

## Task 7：同源HTTP入口、任务卡片和单槽执行

**Create:** 地图所列API/前端文件、`backend/tests/test_plan_adjustment_api.py`、`backend/tests/test_plan_adjustment_coach_handoff.py`、前端 `PlanAdjustmentDialog.test.tsx`、`PlanTaskCard.test.tsx`。
**Modify:** `main.py`、`config.py`、`api/plan.py`、`api/coach_conversations.py`、`use_cases/coach_turns.py`、`frontend/src/pages/plan/PlanDetail.tsx`、现有Coach消息展示入口（先rg定位，不猜文件）。

- [ ] **RED：** HTTP层start→只读许可→尝试diet修改拒绝→显式修改许可→execute→候选→confirm；两入口读取相同task/version。前端用合成API响应测试未许可域不显示“已修改”、未通过/过期无confirm、刷新不触发execute/confirm。
- [ ] **实现路由：**
```text
POST /api/v1/plan-adjustment-tasks
GET  /api/v1/plan-adjustment-tasks/{task_id}
POST /api/v1/plan-adjustment-tasks/{task_id}/scope
POST /api/v1/plan-adjustment-tasks/{task_id}/answers
POST /api/v1/plan-adjustment-tasks/{task_id}/execute
POST /api/v1/plan-adjustment-tasks/{task_id}/confirm
POST /api/v1/plan-adjustment-tasks/{task_id}/cancel
GET  /plan/current
```
POST统一Idempotency-Key/expected_version；confirm另带expected_head_revision和candidate_digest。owner从认证取；body多余字段拒绝。/plan/current注册在动态/{plan_id}之前。GET永不启动Provider，未知/他人同404，409后显示最新差异要求重新确认。
- [ ] **补齐准入与取消：** PlanAdjustmentService.execute由现有账户单槽准入保护；从已有Coach执行中进入时传可信同账户执行lease而非用户控制的already_admitted布尔，避免二次争槽死锁。不创建并列后台池；等待许可/确认无执行槽。cancel传播同一AbortRegistry，传输清理后才释放；晚到答复不得发布候选。
- [ ] **兼容与开关：** Settings新增 `plan_adjustment_tasks_enabled=False`、`plan_storage_mode: file|sqlite='file'`、`plan_task_ttl_days=30`、`plan_candidate_ttl_minutes=30`，正数、创建时快照。任务execute须显式使用unified能力，模式不符报配置错误，不能回退另一模型链；普通旧计划路径保持兼容。启用S3后旧调整draft入口委派同一应用服务，旧activate不得绕过新candidate版本确认。禁用后GET可读，execute/confirm拒绝。
- [ ] **实现共用交互：** PlanTaskCard/PlanDiff共用许可、硬约束、真实old/new、数字来源、过期和两轮额度文案；模型解释与代码差异分栏。警示不因折叠消失。未知网络结果重试同key；改目标/范围展示新关联任务由用户决定；删聊天不删任务/正式计划。
- [ ] **GREEN：**
```powershell
& $taskPython -m pytest backend/tests/test_plan_adjustment_api.py backend/tests/test_plan_adjustment_coach_handoff.py backend/tests/test_coach_conversation_api.py backend/tests/test_chat_api.py -q --basetemp="$taskBase-t7-green"
npm --prefix frontend test -- src/components/plan/PlanAdjustmentDialog.test.tsx src/components/plan/PlanTaskCard.test.tsx
npm --prefix frontend run build
```
建议 `feat(plan): share constrained tasks across coach and plan page`。

## Task 8：独立回放、对抗与交付证据

**Create:** `backend/task_evaluation/scenarios/plan_adjustment.json`、`backend/tests/task_evaluation/test_plan_adjustment.py`、`docs/evaluation/plan-adjustment-acceptance.md`。
**Modify:** `backend/task_evaluation/{contracts,seeding,worker,runner,scorers,report}.py`、`docs/agent-task-contracts.md`。

- [ ] **RED：** suite声明 `requires=['plan_adjustment']`，旧worker应unsupported而非passed；新观察只允许有界task state/round/head/count/digest，拒绝读取私密正文和任意JSON路径。加入同域未改深比较与对授权spy计数的精确断言。
- [ ] **实现12个声明式场景：** 训练单改、饮食单改、跨域许可拒绝、只读不授权修改、首次联合合格、R1两域/R2单域、两轮仍失败、目标冲突追问、旧head拒确认、相同key确认重放、同round恢复、越权/伪confirmed。取消、删账户、过期、模式关闭、Reviewer故障和并发另有目标测试；报告明确哪些来自API回放、哪些来自单测。
- [ ] **接线同一应用：** worker在独立合成SQLite开新能力，使用Task 4同一循环+scripted决策，网络仍阻断。候选成功以候选/约束/审核状态确定，激活以head/历史/receipt确定；不能据一段“已完成”文本判分。计入初次合格、两轮收敛、非必要变更与恰当停止。
- [ ] **GREEN与完整门禁：**
```powershell
& $taskPython -m pytest backend/tests/task_evaluation/test_plan_adjustment.py backend/tests/domain/test_plan_adjustment.py backend/tests/test_plan_adjustment_service.py -q --basetemp="$taskBase-t8-green"
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/plan_adjustment.json --output ".tmp/task-evaluation/s3-$taskStamp" --max-calls 400 --max-tokens 1000000 --max-seconds 900
```
这些新suite/能力在Task 8实现后才可执行，不是假称当前已支持。随后运行总计划完整后端/独立配置/前端及构建；记录平台skip，不编写预期固定通过数。
- [ ] **交付：** 保存输入版本、代码SHA/diff、12场景结果、两条round轨迹、正式写入深比较、失败样本与所有配置。只写实际交付/实测；代码合并前再次备份保留主库，未授权不迁移/启用/提交/推送。建议 `test(plan): record constrained task and activation evidence`。

## 2. 旧任务映射与停止条件

| 旧S3 | 新检查点 |
| --- | --- |
| Task 1 patch/约束/差异 | 1、5 |
| Task 2双领域生成/修复 | 2、3、4、5；删除各自Gateway，不是新增双Agent |
| Task 3激活与存储 | 6 |
| Task 4接口/UI | 7 |
| Task 5评估 | 8 |

缺身份/许可、预算耗尽、不可满足、依赖失效、必要审核不可用及模式改变均必须受控停止；不能通过新增自由工具、再造任务、降级审核或重置run规避。用户未授权生产迁移和真实模型评测时，收口范围仅为隔离离线交付。
