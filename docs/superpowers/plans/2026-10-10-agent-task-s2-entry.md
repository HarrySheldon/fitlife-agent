# S2 交互式整餐录入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 交付两轮澄清、按项保存与局部更正，并能恢复同一任务。

**Architecture:** 扩展现有 SmartEntryDraft 与 SQLite 仓储；食品候选增加交互元数据，原有训练录入维持兼容。领域纯函数负责信息缺失与依赖失效，业务服务负责状态、权限和事务。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---

undefined
## 依赖与文件分工

依赖 S0/S1。录入保留期采用已有30天配置，任何缩短需产品确认。任务等待期间不保留 Runtime 工作线程。
新增：
- `backend/domain/entry_interaction.py`：条目修订、问题组、缺失判定与字段来源；
- `backend/application/use_cases/interactive_entry.py`：交互命令协调；
- `backend/agent/entry_workflow.py`：受限解析/澄清调用；
- `backend/application/ports/task_budget_repository.py`、`backend/infrastructure/repositories/sqlite_task_budget_repository.py`：S2/S3共用预算预留；
- `backend/tests/domain/test_entry_interaction.py`、`backend/tests/application/test_interactive_entry.py`；
- `backend/tests/infrastructure/test_entry_partial_confirm.py`、`test_task_budget_repository.py`；
- `backend/tests/test_interactive_entry_api.py`；
- `frontend/src/components/smart-entry/ClarificationPanel.tsx`、`EntryItemCard.tsx`；
- `frontend/src/pages/SmartEntry.interaction.test.tsx`。

修改：
`backend/application/ports/smart_entry_repository.py`、
`backend/infrastructure/repositories/sqlite_smart_entry_repository.py`、
`backend/infrastructure/sqlite/schema.py`、
`backend/api/smart_entry.py`、`smart_entry_schemas.py`、
`backend/application/use_cases/smart_entry.py`、
`backend/agent/runtime.py`、`backend/config.py`、
`frontend/src/types/smartEntry.ts`、
`frontend/src/services/smartEntryApi.ts`、
`frontend/src/hooks/useSmartEntryDraft.ts`、
`frontend/src/pages/SmartEntry.tsx`。
生命周期修改 `backend/application/use_cases/export_account_data.py`、
`backend/infrastructure/repositories/sqlite_profile_target_repository.py`。
本阶段新增食品交互元数据，不将训练 candidate 转成食品；混合输入沿用原训练确认通路，食品部分保存不会提前提交训练。

### Task 1：稳定条目、字段来源和旧草稿兼容

- [ ] test_entry_interaction.py 新增局部修改测试。EntryItem、replace_fields 在 entry_interaction.py 定义：

```python
from backend.domain.entry_interaction import EntryItem, replace_fields

def test_change_preserves_item_identity_and_marks_estimate():
    original = EntryItem(
        item_id="food-1", revision=1, state="ready",
        values={"amount_g": 100}, sources={"amount_g": "estimated"},
        missing_fields=(), assumptions=("目录中份量为100克",),
    )
    changed = replace_fields(original, {"amount_g": 150},
                             {"amount_g": "user_provided"})
    assert changed.item_id == original.item_id
    assert changed.revision == 2
    assert original.values["amount_g"] == 100
    assert changed.sources["amount_g"] == "user_provided"
```

- [ ] RED：`& $taskPython -m pytest backend/tests/domain/test_entry_interaction.py -q`。
- [ ] EntryItem与修改函数的最小实现内核如下，缺失字段与数值校验在服务调用前后按领域规则执行，不能把该函数返回直接视为新的ready候选：

```python
from dataclasses import dataclass, replace
from typing import Literal

@dataclass(frozen=True)
class EntryItem:
    item_id: str
    revision: int
    state: Literal["needs_clarification", "ready", "saved", "discarded"]
    values: dict[str, object]
    sources: dict[str, str]
    missing_fields: tuple[str, ...]
    assumptions: tuple[str, ...]

def replace_fields(item: EntryItem, updates: dict[str, object],
                   sources: dict[str, str]) -> EntryItem:
    if item.state in ("saved", "discarded"):
        raise ValueError("ITEM_NOT_EDITABLE")
    if set(updates) != set(sources):
        raise ValueError("FIELD_SOURCE_REQUIRED")
    return replace(item, revision=item.revision + 1,
                   state="needs_clarification",
                   values={**item.values, **updates},
                   sources={**item.sources, **sources})
```
- [ ] 复用候选已有 id，禁止使用数组下标作为条目身份。新增交互状态保存于 payload 的有类型 interaction 字段；不把计数塞进任意 agent_metadata 允许客户端修改。
- [ ] 旧 payload 读取投影为 schema_version=1、clarification_rounds=0、条目revision=1，写入时由版本条件升级 schema_version=2；只读不改变数据库。旧候选无估算来源不得自动标实测。
- [ ] 按目录单位、输入份量和摄入比例计算营养；范围/比例错误用现有业务校验拒绝。无法匹配目录营养时标 unknown，可手工填正式记录要求字段，不调用模型捏造数字。
- [ ] GREEN：补多个同名食品ID不同、候选重新排序ID不变、估算接受后来源仍 estimated、已保存更正拒绝、旧训练草稿兼容测试。

### Task 2：持久化问题组、局部合并与任务预算

- [ ] test_interactive_entry.py 写“首次充分不追问”“两组问题后不出现第三组”“问题组重发轮数不增加”“回答只改目标条目”四测试；网关为 scripted fake。
- [ ] RED：`& $taskPython -m pytest backend/tests/application/test_interactive_entry.py -q`。
- [ ] interactive_entry.py 定义 start(user_id,draft_id,expected_version,key)、answer(...,question_group_id,answers)、correct(...,item_id,revision,updates)、resume(user_id,draft_id)。所有变更输入extra=forbid，rounds仅服务端写。
- [ ] 缺失字段表按条目输出 field/item_id/portion_options；每组覆盖本餐多个缺失项。目录能确定则不问。份量选项来自目录单位/规则，不能所有食品强制套用同一碗重量。
- [ ] 每轮先事务记录 question_group_id、asked_at、计数、expected_version 后返回问题；同幂等键相同请求返回已存问题。轮数达到2时展示估算假设或手工补充控件，不生成新问题组。
- [ ] 答案按 field/item_id 合并；歧义指代不修改多条记录，允许从现有组澄清选择。模型只收到 EntryInput 与受影响项，类型失败不发布 ready 候选。
- [ ] task_budget_repository.py 定义 reserve(user_id,task_id,operation_id,calls,tokens)、settle(...,actual_calls,actual_tokens,usage_known)。SQLite新迁移创建共享预算表及操作预留表，以事务更新，唯一(user_id,task_id,operation_id)。所有网关重试/审核从任务剩余额度预留并受单次run预算限制；未知usage按预留上限结算，不能释放所有预算。
- [ ] RuntimeContext增加可注入任务预算回调，默认None保持现有调用兼容。每次实际Provider尝试（包括重试/Reviewer）先预留，再启动请求；检查deadline/cancel后才调用Provider，后续结算不能复活已取消run。新工作流通过task_ref绑定仓储，普通无task_ref聊天不读取任务预算库。为预算重复回调、超时后迟到返回补Runtime集成测试到test_task_budget_repository.py。
- [ ] 所有快照写回通过 expected_version；用户在模型期间修改则返回冲突，结果不可盖回。相同任务新run仍读已消耗预算。崩溃遗留预留保守计费，不自动无限退还。
- [ ] GREEN：并发同组问题只增加一次、模型超时保存原输入、重复回答返回原结果、两个预算并发预留不能超限。测试命令：

```powershell
& $taskPython -m pytest backend/tests/application/test_interactive_entry.py backend/tests/infrastructure/test_task_budget_repository.py -q
```

### Task 3：原子部分确认和条目级防重复

- [ ] test_entry_partial_confirm.py 设置2个食品，一个ready一个缺字段；确认第一个后正式记录1条，草稿保留第二个。换幂等键重复确认同一(item_id,revision)，正式记录仍1条。
- [ ] RED：`& $taskPython -m pytest backend/tests/infrastructure/test_entry_partial_confirm.py -q`。
- [ ] schema.py 追加新迁移（当前records版本3，实施时取下一未使用版本），建立 entry_item_commits，唯一(user_id,draft_id,item_id,item_revision)，保存 meal_id；不以外键草稿级联删除映射，草稿过期后重放不能再次写入。
- [ ] 仓储增加 confirm_items(user_id,draft_id,expected_version,selections,idempotency_key,request_fingerprint,timezone_name)，selections为item_id/revision；结果包含item到meal映射、remaining_draft_version、replayed。去重/排序后计算请求指纹。
- [ ] 同事务顺序：认证归属 → 查幂等重放 → 检查草稿版本/过期 → 验证所有选项、目录可见性与依赖 → 写入未提交食品 → 写映射 → 更新草稿状态/版本 → 保存幂等结果。任何一步故障回滚全部所选项。
- [ ] 已成功请求重放可返回历史结果，即使草稿已完成或过期；新确认则必须拒绝过期。新键全为已提交项返回已有映射、不新写入；混合已提交和新项必须按当前版本验证后事务完成。
- [ ] 正式食品记录以后被用户显式编辑/删除时，历史提交映射保留提交事实，重放返回提交回执并标明当前记录已变化/删除，不自动重新建记录。账户删除清除本用户映射；草稿正文删除不清除防重事实。
- [ ] 保留原 confirm 为旧接口；schema2交互草稿禁止经旧接口删除未保存项或绕过revision校验，需转换为同一个选择事务。训练确认继续已有幂等规则。
- [ ] GREEN：选中集合一项过期目录导致0条新增、写第二项时故障全部回滚、线程竞争只写一次、异用户查不到映射。用户确认估算必须对当前revision生效。
- [ ] 在新表上线同任务修改 delete_user_data 删除条目映射/预算；表生命周期与正式记录一致，草稿过期只清理草稿正文。

### Task 4：API与前端完整交互

- [ ] test_interactive_entry_api.py 覆盖以下新接口，认证/HTTP映射按S1。SmartEntry.interaction.test.tsx 模拟“保存一项，另一项仍可编辑”和“刷新只GET，不POST确认”。
- [ ] API在现有前缀 `/api/v1/smart-entry-drafts` 增加如下契约：

```text
POST /{id}/interaction/start
  {expected_version}; Idempotency-Key
POST /{id}/interaction/answers
  {expected_version, question_group_id, answers:[{item_id,field,value}]}
POST /{id}/interaction/corrections
  {expected_version, item_id, item_revision, updates}
POST /{id}/confirm-items
  {expected_version, selections:[{item_id,item_revision}], accepted_estimates:[{item_id,item_revision}]}
GET /{id}
  原响应新增interaction、item_commit映射、依赖有效性；不自动调用模型
```

- [ ] 所有POST携带Idempotency-Key。用户手工字段不能写修订次数、状态、owner或提交映射；服务端重新计算。
- [ ] ClarificationPanel只展示当前问题组/份量选项；EntryItemCard展示来源、假设、估算确认、ready/saved。逐项选择保存，服务端成功后才标saved。错误保留输入；409取最新快照并显示冲突，不自动重新确认。
- [ ] hook恢复先向服务器读取。现有localStorage pending对象仅保留用户作用域的task ID、命令键及指纹；不把完整健康草稿作为最新真相；退出清理本地引用、切用户隔离。失败确认可以显式重试同键。
- [ ] 回归保留训练条目页面和旧整餐提交；新交互开关默认关闭并由配置统一控制，不能只隐藏按钮。
- [ ] config.py在本任务增加interactive_entry_enabled=False、entry_task_ttl_days=Field(default=30,gt=0)，任务创建时快照期限。开关关闭仍允许读现有草稿，拒绝start/answers/model execute/confirm-items；原训练确认不受该新业务开关影响。前端读取服务器能力信息，不自行推断环境变量。
- [ ] 测试：

```powershell
& $taskPython -m pytest backend/tests/test_interactive_entry_api.py backend/tests/test_smart_entry_api.py backend/tests/test_smart_entry_confirmation.py -q
npm --prefix frontend test -- src/pages/SmartEntry.interaction.test.tsx src/services/smartEntryApi.test.ts
npm --prefix frontend run build
```

### Task 5：恢复、隐私生命周期与场景验收

- [ ] tests添加重启创建新Service后恢复相同rounds/version/item映射；目录版本改变仅使相关项失效；cancel不删已保存记录。
- [ ] ExportAccountData 注入可只读的草稿/预算导出端口，不从API外自行选择生产数据库。ZIP新增 entry-drafts.json，包含用户业务草稿与来源，不包含凭据、网关正文、隐藏推理。保留现有导出总大小上限。
- [ ] 清理功能新增 `backend/application/use_cases/expire_agent_tasks.py`、`backend/tests/application/test_expire_agent_tasks.py`：按服务端clock筛选到期草稿，dry-run默认；apply仅指定用户/期限并用仓储事务删除。立即拒绝到期访问不依赖清理成功。
- [ ] S0场景新增 `backend/task_evaluation/scenarios/interactive_entry.json`：充分/模糊/未知份量、两轮上限、部分保存、局部更正、重连、越权8类，确认效果通过API与只读存储双重判分。
- [ ] 运行上述目标测试、旧业务/安全测试、总入口全量回归；再离线回放：

```powershell
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s2
```

- [ ] 验收报告附一次“整餐→澄清→部分保存→重启恢复→补剩余”的完整轨迹；每步骤明确任务版本、轮数、正式记录数。
