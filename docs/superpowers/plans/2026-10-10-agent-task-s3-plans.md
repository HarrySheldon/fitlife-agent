# S3 统一计划调整 Implementation Plan

## 2026-10-22 与统一 Agent 的衔接修订

先完成 [U0–U6](2026-10-22-unified-coach-agent.md)；下文任务2的 coordinator 是领域任务/修订状态协调，不再自建另一套模型决策循环、Planner/Writer 或授权账本。生成/修复请求通过统一 Agent 及受控领域能力完成；task version、范围许可、整任务共享两轮、候选差异、幂等和原子激活仍由本文领域/应用模块执行。新旧入口不能直接以聊天输出替代正式候选。

本文仍未开始实施。U仅返回建议，不创建本文的会话/候选/plan head，不迁移正式计划。开始S3前根据当前Interface修订任务2的调用名，保留其他数据库事务、导出删除和预算约束。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 用一个协调流程支持饮食/训练调整，受授权和硬约束控制并保留历史版本。

**Architecture:** 协调器调用独立领域模块生成有类型patch，确定性校验与局部修订。新的SQLite计划仓储提供会话、当前指针及幂等激活事务；旧文件只作兼容导入来源。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---

## 与教练体验C阶段的联合依赖

当前统一顺序和状态见 [主计划](2026-10-10-agent-task-system-plan.md)；先完成 [C0–C4离线检查点](2026-10-18-coach-conversation-experience.md)，再开始本文原5个任务。Coach聊天只引用S3任务，范围许可、共享两轮修订、候选、差异和确认均委派本文同一服务，不复制聊天版计划状态机或激活接口。PlanAdjustmentDialog/PlanDiff的内容应可同时用于计划页和教练中的任务卡片。

由教练发起的execute／repair使用C同一账户活动准入；等待范围许可或确认不占模型执行槽。聊天重试／切换不重置任务预算。聊天90天清理不删除正式计划，任务／候选仍使用自己的TTL，不能混为一个期限。旧计划入口不可绕过相同权限、版本与幂等约束。当前本文仍未开始实现。

## 依赖、默认值和文件分工

依赖S0/S1/S2任务预算端口。内部修订整任务共两轮已获确认；会话30天/候选30分钟、联合候选整体确认按总设计建议，实施前在阶段配置中明确采用值。
新增：
`backend/domain/plan_adjustment.py`（patch/约束/差异）；
`backend/agent/plan_adjustment/{__init__,coordinator,training,diet}.py`；
`backend/application/ports/plan_adjustment_repository.py`；
`backend/application/use_cases/plan_adjustment.py`；
`backend/infrastructure/repositories/sqlite_plan_repository.py`；
`backend/infrastructure/repositories/sqlite_plan_adjustment_repository.py`；
`backend/infrastructure/repositories/plan_repository_factory.py`；
`backend/infrastructure/sqlite/import_legacy_plans.py`；
`backend/api/plan_adjustment.py`、`plan_adjustment_schemas.py`；
`frontend/src/components/plan/PlanAdjustmentDialog.tsx`、`PlanDiff.tsx`；
`frontend/src/services/planAdjustmentApi.ts`、`frontend/src/types/planAdjustment.ts`。
修改 `backend/api/plan.py`、`backend/main.py`、`backend/application/ports/plan_repository.py`、
`backend/infrastructure/sqlite/schema.py`、`backend/application/use_cases/plans.py`、
`backend/application/use_cases/export_account_data.py`、
`backend/infrastructure/repositories/sqlite_profile_target_repository.py`、
`backend/config.py`、
`frontend/src/pages/plan/PlanDetail.tsx`。
测试新增 `backend/tests/domain/test_plan_adjustment.py`、
`backend/tests/test_plan_adjustment_coordinator.py`、
`backend/tests/infrastructure/test_sqlite_plan_activation.py`、`test_legacy_plan_import.py`、
`backend/tests/test_plan_adjustment_api.py`、
`frontend/src/components/plan/PlanAdjustmentDialog.test.tsx`。

### Task 1：领域patch、明确约束与差异

- [ ] test_plan_adjustment.py 定义允许路径测试和未授权模块不变测试：

```python
import pytest
from backend.domain.plan_adjustment import Patch, apply_patches

def test_training_cannot_modify_diet():
    base = {"workout_plan": {"days": []}, "diet_plan": {"meals": []}}
    patch = Patch(domain="training", path=("diet_plan", "meals"),
                  old_value=[], new_value=["changed"],
                  reason="测试", evidence_refs=())
    with pytest.raises(ValueError, match="PATCH_SCOPE"):
        apply_patches(base, (patch,), frozenset({"training"}))
    assert base["diet_plan"]["meals"] == []
```

- [ ] RED：`& $taskPython -m pytest backend/tests/domain/test_plan_adjustment.py -q`。
- [ ] Patch定义以下frozen结构；apply_patches先deepcopy，再验证授权和path白名单、old_value相等、字段类型，最后逐字段赋值：

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Patch:
    domain: Literal["training", "diet"]
    path: tuple[str, ...]
    old_value: object
    new_value: object
    reason: str
    evidence_refs: tuple[str, ...]
```
- [ ] 第一版只允许完整领域下有限子树替换（例如训练日/饮食餐次），不执行任意JSON Pointer、负索引、反序列化代码。目标、权限、trace/validation元数据不在白名单；后两者由代码重新生成。
- [ ] Constraints分hard/preference；硬约束含可用时间/器械/禁止动作、过敏/忌口、现有营养目标，保存来源与版本。信息缺失先问用户，不把旧示例档案当现用户事实。
- [ ] 差异由代码比对base与最终candidate生成，包括old/new/reason/evidence；模型reason与实际更改不符标可疑，不能用理由掩盖未授权路径。
- [ ] GREEN：旧值不匹配409、目标被修改拒绝、数值类型失败、无变更返回no_change、训练单改饮食深比较相等。营养数字用目录与工具重算，沿用现有validate_generated_plan，再补明确新约束校验。

### Task 2：双领域协调、许可和共享修订轮

- [ ] test_plan_adjustment_coordinator.py用scripted模块模拟首次两域失败、第一轮两域修、第二轮仅diet修。断言repair_rounds=2、training.repair调用1次、diet.repair调用2次。
- [ ] RED：`& $taskPython -m pytest backend/tests/test_plan_adjustment_coordinator.py -q`。
- [ ] coordinator.py 定义 start、run_initial、repair、grant_scope、resume。两个模块仅实现 generate(input)/repair(input,previous_patch,violations)，依赖注入Gateway；验证由domain函数与工具完成。
- [ ] 用户明确“训练和饮食一起改”可授予两域；训练单改发现饮食关联，只返回awaiting_scope_permission，不能加载饮食明细/调用diet。许可持久记录user/task/version/domains/time；拒绝只做原任务。
- [ ] 状态：collecting、awaiting_scope_permission、generating、repairing、awaiting_confirmation、awaiting_user_decision、activated、cancelled、expired。任务state与runstate分别保存。
- [ ] 轮次由仓储事务reserve_repair_round(owner,task,expected_version,round_id,failed_domains)创建，S1 next_repair_round只验证上限。相同round_id重放不加一；两模块属于同轮。模块结果保存后记录completed_domains，恢复补pending_domains。
- [ ] 类型/领域校验失败计入候选失败，局部修复只提供该域violations与必要上下文；已合格域保留。最终合并再次验证跨领域硬约束。审核若需修订也纳入同一两轮额度，不偷偷循环独立Reviewer重写。
- [ ] 候选可发布前做必需安全审核与证据校验。拒绝型风险不通过“修订”绕过。总run超时/任务预算不足停止执行，任务保存可恢复状态与受控错误。
- [ ] 两轮后仍不合格 → awaiting_user_decision，禁止确认。用户改变目标/范围/限制创建明确关联新任务，模型无create_task权限。
- [ ] GREEN：断电恢复同round不重复、网络重试只消耗调用预算、两域并发reserve仅一成功、不可满足目标不暗改、refuse diet零调用、Reviewer失败遵循现有安全模式。

### Task 3：SQLite原子激活、旧数据导入及统一存储源

- [ ] test_sqlite_plan_activation.py写当前计划p1、候选c1；两次同键激活只生成p2一次，历史p1仍相同。另一候选同时改基准后c1确认返回STALE且不写入。
- [ ] RED：`& $taskPython -m pytest backend/tests/infrastructure/test_sqlite_plan_activation.py backend/tests/infrastructure/test_legacy_plan_import.py -q`。
- [ ] schema.py追加迁移建立plans、plan_heads、plan_adjustment_sessions、plan_activation_receipts：所有key包括user，plans不可变，heads记录active_plan_id/revision，receipt唯一(user,idempotency_key)。共享任务预算使用S2表。
- [ ] SQLitePlanRepository实现原PlanRepository全部方法及current_head；Plans普通生成、list/get、activate统一经过factory选取相同仓储，避免新旧两套“最新计划”。
- [ ] 原子confirm契约：

```text
activate(user_id, task_id, expected_task_version,
         expected_head_revision, idempotency_key, fingerprint)
BEGIN IMMEDIATE
  查询用户幂等回执；同键异请求拒绝
  读task、head、当前SQLite档案/目标版本
  检查owner、授权、expiry、candidate摘要、base版本、约束版本
  使用代码重验候选；不在事务内调用模型
  INSERT新plan；UPDATE head WHERE revision = expected
  标记task activated；INSERT回执
COMMIT
```

- [ ] 健康/目标版本来自同一SQLite权威表，显式用户约束保存在会话。若已有某约束仍由外部文件作权威源，先将该来源写入流程纳入版本化事务或保守停止激活；不能只在事务开始前算文件摘要就声称跨进程原子保证。
- [ ] 不在数据库写事务内持有Provider连接。沿用账户lifecycle guard，删除与activate并发不能复活已删账户；跨进程条件通过SQLite事务版本实现，不依赖threading.Lock。
- [ ] Legacy import读取FilePlanRepository所有历史/草稿，保留id/时间/based_on；验证每个payload和所属用户，无身份绑定文件拒绝导入。当前head按旧页面当前选取规则（最新activated_at）构建，同时间明确稳定排序，报告决定。
- [ ] import为显式CLI `python -m backend.infrastructure.sqlite.import_legacy_plans --data-dir ... --dry-run`；只在合成tmp目录执行。正式数据先备份/清点再授权apply；不自动在请求中迁移，不删旧文件，重复导入结果一致、同ID异内容拒绝。
- [ ] SQLite激活后的文件不再作当前状态源；factory的sqlite开关只在导入完成用户启用，切换时停写校对，不双写。旧文件只读兼容期有明确告知。
- [ ] 修改导出从权威PlanRepository列历史/会话；delete_user_data覆盖新表、receipt、预算，外键删除顺序通过测试。清理会话不删正式历史。
- [ ] GREEN：插plan/更新head/写receipt各步故障均回滚、两个进程竞争旧基准仅一成功、导入断点重试、删除期间确认、导出只见本用户。

### Task 4：计划API、差异确认和恢复UI

- [ ] test_plan_adjustment_api.py实现start→permission→candidate→confirm；前端测禁止未许可diet展示“已修改”、两轮失败显示冲突而无激活按钮、刷新无自动confirm。
- [ ] 新router注册 `/api/v1/plan-adjustment-tasks`：

```text
POST /                      {base_plan_id, requested_domains, instructions}
GET  /{task_id}              持久状态/差异/轮次/依赖有效性
POST /{task_id}/scope        {expected_version, allowed_domains, decision}
POST /{task_id}/answers      {expected_version, answers}
POST /{task_id}/execute      {expected_version}
POST /{task_id}/confirm      {expected_version, expected_head_revision, candidate_digest}
POST /{task_id}/cancel       {expected_version}
```

- [ ] 所有变更POST有Idempotency-Key；initial生成/round恢复通过execute触发，GET仅查看。答案实质改目标/限制时响应requires_new_task并显示关联任务选项，不能原任务自动重置轮数。
- [ ] 已过期candidate只展示不可激活状态。用户显式execute后重新核查依赖，依赖不变且原候选仍有效时可确定性重验并创建新确认版本；若需模型修复仍消耗原任务剩余修订/调用额度。额度耗尽时等待用户改变任务，不能把过期当作系统自动建新任务的理由。
- [ ] 旧 `/plan/{id}/draft` 保留兼容但不能绕过新授权；启用新功能后委派新服务并将状态转换为兼容响应。旧激活接口不接受新会话candidate绕过摘要/版本确认。
- [ ] PlanAdjustmentDialog显示范围许可、明确约束、old/new diff、估算时长/数值来源、有效期。PlanDiff显示两域真正变化字段，健康警示不能被折叠消失。
- [ ] 网络未知结果重试相同键；409加载最新状态请用户重新查看差异；成功跳到新plan_id，历史原plan仍可查看。联合候选一次整体确认。
- [ ] config.py增加plan_adjustment_tasks_enabled=False、plan_storage_mode(file/sqlite，默认file)、plan_task_ttl_days=Field(default=30,gt=0)、plan_candidate_ttl_minutes=Field(default=30,gt=0)。已有任务的保留期使用创建快照；安全模式变化不得使恢复任务获得更宽权限。服务器关闭新功能后禁止新execute/confirm，但GET会话仍可查看。
- [ ] API增加GET /plan/current返回当前head及版本，并在动态/{plan_id}路由前注册；启用SQLite后前端从此读取生效计划，不以“历史列表第一项”代替head。list仍返回所有历史且保持兼容排序。factory迁移状态与开关组合错误时明确CONFIGURATION_INVALID，不能静默回退不同权威源。
- [ ] 测试：

```powershell
& $taskPython -m pytest backend/tests/test_plan_adjustment_api.py backend/tests/application/test_plans.py -q
npm --prefix frontend test -- src/components/plan/PlanAdjustmentDialog.test.tsx
npm --prefix frontend run build
```

### Task 5：多轮验收场景、文案与故障回归

- [ ] 新增 `backend/task_evaluation/scenarios/plan_adjustment.json`：训练单改、饮食单改、许可接受/拒绝、联合两轮修复、两轮失败、目标冲突、旧基准、恢复、确认重试、越权10类。
- [ ] 判分读取最终patch路径、计数、head版本和历史内容，而非只查回答中“成功”。候选first_confirmable时刻仅在类型/约束/安全均通过后记录。
- [ ] 文档与UI文案准确：“首次生成后，全任务最多两轮自动纠错；一轮可修两个模块；仍不满足时请你决定。”不宣传最多三次模型调用。
- [ ] 跑目标测试、计划/录入/安全旧测试及总入口全量回归，再Mock回放：

```powershell
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/plan_adjustment.json --output .tmp/task-evaluation/s3
```

- [ ] 交付两条轨迹：单模块饮食保持不变；联合第一轮两域、第二轮单域的round账本。附正式迁移前清点/dry-run方案，但不直接执行生产迁移。
