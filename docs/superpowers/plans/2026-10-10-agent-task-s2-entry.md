# S2 交互式整餐录入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 交付两轮澄清、按项保存与局部更正，并能恢复同一任务。

**Architecture:** 扩展现有 SmartEntryDraft 与 SQLite 仓储；食品候选增加交互元数据，原有训练录入维持兼容。领域纯函数负责信息缺失与依赖失效，业务服务负责状态、权限和事务。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---

## 执行记录

**当前状态（2026-10-17）：S2 五项任务已完成实现、独立规格/质量复核与离线验收。** 最终后端 **1919 passed，798.10 秒**，前端 **267 passed / 39 files，22.54 秒**，生产构建通过（Vite 7.76 秒，保留既有大包体警告），交互八类及原六类离线回放分别 **8/8、6/6** 通过。来源、训练兼容、失效投影、本地编辑、并发合并及规范化重试等最终审查问题均已关闭。证据见 `docs/evaluation/2026-10-16-s2-entry-acceptance.md`。以下记录按历史检查点保留，旧的“实施中/待审/待验收”不代表当前状态。所有 S2 变更仍未提交或推送，功能默认关闭，未执行真实模型评测或生产操作。

**历史检查点（2026-10-17 最终集成复核中）：** 任务 5 的场景实现及单项规格/质量复核完成，修复前完整后端 **1892 passed，762.69 秒**；整阶段复核发现混合训练补全被锁、目录更换后旧来源残留两项 P2，正在补针对性回归并修复。来源回归已从实际 2 failed 转为 2 passed；训练窄 PATCH 已可写入，但仍需补齐响应提交映射及规范化后重试指纹。最终全量和复核通过前不将 S2 标为完成。详细检查点见验收报告。

2026-10-16 任务 3：新增 records migration 6、原子食品部分确认、条目提交事实与最小幂等回执；确认事务内重查目录签名，按摄入比例只换算一次正式份量，保留未保存食品和训练候选。旧入口对混合任务仅确认训练；历史回执在正文删除/到期后仍可重放，并标明正式记录已编辑/删除。重复 start 遇到变化的目录依赖返回冲突。根代理执行目标套件 **47 passed，7.69 秒**；进一步加固回执形状/大小、指纹和纯训练兼容，先实际复现 **17 failed**，修复后 **63 passed / 1 failed，9.79 秒**，唯一失败为测试准备的 1500 层 JSON 被 SQLite `json_valid` 约束拒绝；测试深度改为可存储的 950 层后，部分确认套件 **27 passed，6.97 秒**。迁移、仓储、预算和领域回归 **157 passed，17.15 秒**；旧 API/服务回归 **21 passed，25.22 秒**。当前规格复核通过，质量复核待完成；任务 4/5 与完整 S2 验收尚未完成，全部改动仍未提交。

2b 进一步串行分解为 2b1 有类型问题组/依赖/运行关联与可信幂等事务，2b2 交互服务及受限模型工作流。事务仅执行已计算的确定性状态变换，不在 SQLite 锁内等待 Provider。业务快照型命令重放记录随草稿正文级联清理，和任务 3 的长期最小提交回执分离。

2b1 实现、规格与质量复核完成：新增可信命令事务、到期区分读取、问题组及目录依赖、records migration 5 级联命令回执。首测缺方法 RED→GREEN 38 passed；新增回执未知字段/布尔版本 RED 2 failed、问题目标及轮数 RED 6 failed 后修正；再经规格审查复现状态/到期字段错误类型，RED 2 failed→修复。最终相关目标 **69 passed，5.40 秒**（`.tmp/s2-command-receipt-final-green`）。扩展旧 API/分析及迁移测试 109 passed / 1 failed 为另一个硬编码旧迁移清单；仅追加明确版本 4、5 预期后，records schema **96 passed，9.48 秒**（`.tmp/s2-command-schema-final`），原数据保留/全文索引断言未削弱。2b2 交互服务与受限工作流实施中。

2b2 服务与受限工作流实现完成，规格与质量复核通过。阶段测试依次 4/17/25 passed；扩展套件 88 passed / 1 failed 为 Infinity 在测试准备阶段已被 SQLite JSON 约束拒绝，改为真实可存储的 0/布尔继承比例负例，并在命令校验测试保留 NaN/Infinity 负例。最终冻结目标（交互服务、原结构化载荷与安全守卫、Runtime 任务预算、命令仓储）**89 passed，7.13 秒**，`.tmp/s2-service-workflow-frozen-green`。比例语义为输入 amount 保留观察份量、`consumed_amount` 仅换算一次供确认事务使用；目录营养已换算为摄入总量，手工营养字段表示用户提供的已摄入总量，不二次缩放。模型审核沿用部署配置，不强制覆盖 off/shadow；确定性审核步骤仍必经。质量复核的非阻塞目录新鲜度提示将在任务 3 接线时处理：重复 start 不得重新发布失效的 ready 候选，正式确认始终重查依赖。

2026-10-15 续作：用户要求持续执行直到 S2 完成。串行实施顺序为 1b 存储兼容 → 2a 原子任务预算与 Runtime → 2b 交互服务/工作流 → 3 部分确认事务 → 4 API/UI → 5 生命周期与离线场景。每个检查点分别进行规格和质量复核；最终执行后端/前端全量、构建与两套离线场景。此授权不包含提交 S2、推送、上线、生产维护或真实 Provider 付费调用。

2026-10-15：用户授权提交 S1 并开始 S2。基线提交 `eff4527`，S1 提交前相关套件 129 passed；本阶段从任务 1 开始，尚未完成阶段验收。沿用已有 30 天录入保留期，不执行生产迁移或真实 Provider 调用。实现与规格审查、质量审查分开执行，完成后再更新下方检查项。

旧智能录入回归基线：使用项目 `.venv\Scripts\python.exe` 执行 `backend/tests/domain/test_smart_entry.py`、`backend/tests/application/test_smart_entry.py`、`backend/tests/application/test_smart_entry_analysis.py`、`backend/tests/infrastructure/test_sqlite_smart_entry_repository.py`、`backend/tests/test_smart_entry_api.py`、`backend/tests/test_smart_entry_confirmation.py`，`--basetemp .tmp/s2-entry-baseline-20261015 -p no:cacheprovider`，39 passed，26.30 秒；存在原有 Starlette/httpx 弃用提示。这是任务 1 实现前的旧流程基线，不代表 S2 验收通过。

任务 1 分为两个串行检查点，完整任务仍未完成：

- 1a：纯领域基础（`entry_interaction.py`），包括稳定身份与修订、保守旧候选投影、未知营养与目录份量/摄入比例换算。初始模块缺失 RED；补充助手缺失 RED 为 2 failed / 5 passed（导入失败，不冒充行为缺陷复现）；实现后新领域与旧解析器共 23 passed，1.27 秒，`.tmp/s2-task1a-green-20261015`。独立规格审查通过；质量审查发现浮点摄入比例在半舍入边界产生偏差，新增行为回归实际复现 1 failed / 13 passed，再以十进制乘法修复。最终新领域加旧录入服务、分析、仓储、API、确认目标套件 **53 passed，25.10 秒**，`--basetemp .tmp/s2-task1a-final-20261015 -p no:cacheprovider`。尚未接入业务入口，也未提交本小步，不代表完整任务 1 或 S2 已完成。
- 1b（实现与两项复核完成）：持久化有类型 interaction、只读旧 payload 不写库、版本条件升级 schema 2、服务与响应兼容性接线及目标测试。新格式默认 inactive，格式升级不自动开启业务交互；客户端不能写入服务端 interaction。规格审查发现候选 values/provenance 错误类型及 BLOB 逸出 AttributeError，三类 RED→GREEN 后显式校验返回受控损坏错误，复核关闭。续作目标回归 **64 passed，24.70 秒**，`.tmp/s2-storage-resume-final`；质量审查新增深层 JSON RecursionError 负例，RED→GREEN 后限定捕获为受控损坏错误，最后仓储与领域 **34 passed，2.84 秒**，`.tmp/s2-storage-depth-final`，质量复核关闭。1a 的保守投影不直接宣告候选 ready；后续服务仍须复核目录、数值和缺失字段。完整任务 1 检查项将在交互服务营养规则接线后核对更新。

当前检查点：2a 原子持久预算及 Runtime 回调实现、规格和质量复核均完成；2b 交互服务实施中，3 部分确认、4 API/UI、5 生命周期与场景待实施。2a 新增 records migration 4，仅追加预算及预留表，账户删除覆盖新表；任务绑定 factory 仅对带 task_ref 的命令调用。实际模型尝试（含重试/审核）预留完整单次 run token 上限，涵盖 Provider 总用量中的输入；未知 usage 保守结算。已知超出预留的用量先如实提交账本，再报额度耗尽并阻止新预留；重复同一结算仍幂等。结算失败不重放 Provider，成功/失败 Provider 两条结算路径均维持取消/超时优先。首轮目标测试 5 passed / 1 failed 为新测试 AgentResult 构造缺字段；规格复核随后新增真实行为负例，复现输入用量漏计、超额记账和结算期间终态覆盖，逐项 RED→GREEN 后最终预算、Runtime、旧超时与审核目标回归 **36 passed，6.72 秒**，`.tmp/s2-budget-all-control-green`；迁移、档案仓储和账户删除 **47 passed，6.21 秒**，`.tmp/s2-budget-migration-account`。所有 S2 改动仍未提交。

前端旧流程基线：`npm --prefix frontend test -- src/services/smartEntryApi.test.ts src/pages/SmartEntry.test.tsx`，2 个文件 / 6 项通过，5.01 秒。首次沙箱运行被临时目录 rename 的 EPERM 阻止、未执行测试；获准沙箱外重跑通过。

2026-10-16 任务 3 独立规格与质量审查均通过，未发现待修复的阻塞项。开始任务 4 API、服务器能力开关、前端逐项交互与隐私安全恢复；任务 5 和完整阶段验收仍待完成。上文“质量复核待完成”为此前检查点状态，不代表当前状态。

## 依赖与文件分工

2026-10-16 任务 4b：逐项交互、当前问题组、来源/估算确认、服务器优先恢复及退出/切用户保护已接入。真实 Hook 目标测试先复现健康正文落入 localStorage 和不读服务器恢复，再改为只存任务 ID、命令键和 SHA-256 摘要；补充退出发生在保存与下一条命令之间的负例 **2 failed**，修复后拒绝后续请求；已保存条目仍被追问的负例 **1 failed** 后仅筛选当前可编辑缺失字段。字段无障碍名称与来源描述分离。最终录入目标 **30 passed，4.33 秒**，前端构建通过（21.91 秒；保留既有大包体警告），独立规格与质量审查均通过。全量前端首次 **248 passed / 3 failed**，均为旧路由测试模拟缺少新增 capabilities 方法；只补默认关闭的模拟响应并保留全部断言，等待全量复验。尚未执行任务 5 验收，不是完整 S2 完成声明。

2026-10-16 阶段中间全量后端回归：**1864 passed / 1 failed，640.68 秒**，`.tmp/s2-backend-full1016`。唯一失败为 `test_database_startup.py` 的迁移版本预期仍固定为 `[1,2,3]`；明确追加预期 4、5、6，未删除数据库初始化、健康检查和 CSV 读取断言。启动目标复验 **4 passed，14.90 秒**（`.tmp/s2-startup-migrations1016`）。这不是任务 5 完成后的最终全量结果，最终仍须重新验收。

2026-10-16 任务 4 拆为 4a 后端接口、4b 前端交互与恢复，串行实施。4a 独立规格与质量复核通过：首测缺接口 RED 为 2 failed，接线后冻结新 API 与服务目标 **53 passed，67.78 秒**（`.tmp/s2-api-frozen1016`）。模型路径处理模式误标的负例 **1 failed** 后修复，模型/确定性两类标识目标 **2 passed，10.16 秒**（`.tmp/s2-api-mode-green1016`）。开关默认关闭、TTL 在创建时快照、恢复只读、账户生命周期保护与预算错误映射已接入；4b 实施中，仍不代表完整任务 4 或 S2 验收完成。

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

- [x] test_entry_interaction.py 新增局部修改测试。EntryItem、replace_fields 在 entry_interaction.py 定义：

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

- [x] RED：`& $taskPython -m pytest backend/tests/domain/test_entry_interaction.py -q`。
- [x] EntryItem与修改函数的最小实现内核如下，缺失字段与数值校验在服务调用前后按领域规则执行，不能把该函数返回直接视为新的ready候选：

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
- [x] 复用候选已有 id，禁止使用数组下标作为条目身份。新增交互状态保存于 payload 的有类型 interaction 字段；不把计数塞进任意 agent_metadata 允许客户端修改。
- [x] 旧 payload 读取投影为 schema_version=1、clarification_rounds=0、条目revision=1，写入时由版本条件升级 schema_version=2；只读不改变数据库。旧候选无估算来源不得自动标实测。
- [x] 按目录单位、输入份量和摄入比例计算营养；范围/比例错误用现有业务校验拒绝。无法匹配目录营养时标 unknown，可手工填正式记录要求字段，不调用模型捏造数字。
- [x] GREEN：补多个同名食品ID不同、候选重新排序ID不变、估算接受后来源仍 estimated、已保存更正拒绝、旧训练草稿兼容测试。

### Task 2：持久化问题组、局部合并与任务预算

- [x] test_interactive_entry.py 写“首次充分不追问”“两组问题后不出现第三组”“问题组重发轮数不增加”“回答只改目标条目”四测试；网关为 scripted fake。
- [x] RED：`& $taskPython -m pytest backend/tests/application/test_interactive_entry.py -q`。
- [x] interactive_entry.py 定义 start(user_id,draft_id,expected_version,key)、answer(...,question_group_id,answers)、correct(...,item_id,revision,updates)、resume(user_id,draft_id)。所有变更输入extra=forbid，rounds仅服务端写。
- [x] 缺失字段表按条目输出 field/item_id/portion_options；每组覆盖本餐多个缺失项。目录能确定则不问。份量选项来自目录单位/规则，不能所有食品强制套用同一碗重量。
- [x] 每轮先事务记录 question_group_id、asked_at、计数、expected_version 后返回问题；同幂等键相同请求返回已存问题。轮数达到2时展示估算假设或手工补充控件，不生成新问题组。
- [x] 答案按 field/item_id 合并；歧义指代不修改多条记录，允许从现有组澄清选择。模型只收到 EntryInput 与受影响项，类型失败不发布 ready 候选。
- [x] task_budget_repository.py 定义 reserve(user_id,task_id,operation_id,calls,tokens)、settle(...,actual_calls,actual_tokens,usage_known)。SQLite新迁移创建共享预算表及操作预留表，以事务更新，唯一(user_id,task_id,operation_id)。所有网关重试/审核从任务剩余额度预留并受单次run预算限制；未知usage按预留上限结算，不能释放所有预算。
- [x] RuntimeContext增加可注入任务预算回调，默认None保持现有调用兼容。每次实际Provider尝试（包括重试/Reviewer）先预留，再启动请求；检查deadline/cancel后才调用Provider，后续结算不能复活已取消run。新工作流通过task_ref绑定仓储，普通无task_ref聊天不读取任务预算库。为预算重复回调、超时后迟到返回补Runtime集成测试到test_task_budget_repository.py。
- [x] 所有快照写回通过 expected_version；用户在模型期间修改则返回冲突，结果不可盖回。相同任务新run仍读已消耗预算。崩溃遗留预留保守计费，不自动无限退还。
- [x] GREEN：并发同组问题只增加一次、模型超时保存原输入、重复回答返回原结果、两个预算并发预留不能超限。测试命令：

```powershell
& $taskPython -m pytest backend/tests/application/test_interactive_entry.py backend/tests/infrastructure/test_task_budget_repository.py -q
```

### Task 3：原子部分确认和条目级防重复

- [x] test_entry_partial_confirm.py 设置2个食品，一个ready一个缺字段；确认第一个后正式记录1条，草稿保留第二个。换幂等键重复确认同一(item_id,revision)，正式记录仍1条。
- [x] RED：`& $taskPython -m pytest backend/tests/infrastructure/test_entry_partial_confirm.py -q`。
- [x] schema.py 追加新迁移（当前records版本3，实施时取下一未使用版本），建立 entry_item_commits，唯一(user_id,draft_id,item_id,item_revision)，保存 meal_id；不以外键草稿级联删除映射，草稿过期后重放不能再次写入。
- [x] 仓储增加 confirm_items(user_id,draft_id,expected_version,selections,idempotency_key,request_fingerprint,timezone_name)，selections为item_id/revision；结果包含item到meal映射、remaining_draft_version、replayed。去重/排序后计算请求指纹。
- [x] 同事务顺序：认证归属 → 查幂等重放 → 检查草稿版本/过期 → 验证所有选项、目录可见性与依赖 → 写入未提交食品 → 写映射 → 更新草稿状态/版本 → 保存幂等结果。任何一步故障回滚全部所选项。
- [x] 已成功请求重放可返回历史结果，即使草稿已完成或过期；新确认则必须拒绝过期。新键全为已提交项返回已有映射、不新写入；混合已提交和新项必须按当前版本验证后事务完成。
- [x] 正式食品记录以后被用户显式编辑/删除时，历史提交映射保留提交事实，重放返回提交回执并标明当前记录已变化/删除，不自动重新建记录。账户删除清除本用户映射；草稿正文删除不清除防重事实。
- [x] 保留原 confirm 为旧接口；schema2交互草稿禁止经旧接口删除未保存项或绕过revision校验，需转换为同一个选择事务。训练确认继续已有幂等规则。
- [x] GREEN：选中集合一项过期目录导致0条新增、写第二项时故障全部回滚、线程竞争只写一次、异用户查不到映射。用户确认估算必须对当前revision生效。
- [x] 在新表上线同任务修改 delete_user_data 删除条目映射/预算；表生命周期与正式记录一致，草稿过期只清理草稿正文。

### Task 4：API与前端完整交互

- [x] test_interactive_entry_api.py 覆盖以下新接口，认证/HTTP映射按S1。SmartEntry.interaction.test.tsx 模拟“保存一项，另一项仍可编辑”和“刷新只GET，不POST确认”。
- [x] API在现有前缀 `/api/v1/smart-entry-drafts` 增加如下契约：

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

- [x] 所有POST携带Idempotency-Key。用户手工字段不能写修订次数、状态、owner或提交映射；服务端重新计算。
- [x] ClarificationPanel只展示当前问题组/份量选项；EntryItemCard展示来源、假设、估算确认、ready/saved。逐项选择保存，服务端成功后才标saved。错误保留输入；409取最新快照并显示冲突，不自动重新确认。
- [x] hook恢复先向服务器读取。现有localStorage pending对象仅保留用户作用域的task ID、命令键及指纹；不把完整健康草稿作为最新真相；退出清理本地引用、切用户隔离。失败确认可以显式重试同键。
- [x] 回归保留训练条目页面和旧整餐提交；新交互开关默认关闭并由配置统一控制，不能只隐藏按钮。
- [x] config.py在本任务增加interactive_entry_enabled=False、entry_task_ttl_days=Field(default=30,gt=0)，任务创建时快照期限。开关关闭仍允许读现有草稿，拒绝start/answers/model execute/confirm-items；原训练确认不受该新业务开关影响。前端读取服务器能力信息，不自行推断环境变量。
- [x] 测试：

```powershell
& $taskPython -m pytest backend/tests/test_interactive_entry_api.py backend/tests/test_smart_entry_api.py backend/tests/test_smart_entry_confirmation.py -q
npm --prefix frontend test -- src/pages/SmartEntry.interaction.test.tsx src/services/smartEntryApi.test.ts
npm --prefix frontend run build
```

### Task 5：恢复、隐私生命周期与场景验收

5a 独立复核补充：规格审查发现导出漏掉已有自定义食品来源、训练参数及来源署名字段。新增回归复现 **1 failed** 后，采用共享的已知业务值类型与来源署名白名单补齐，仍拒绝任意凭据/网关/推理元数据。最终目标 **51 passed，11.21 秒**（`.tmp/s2-lifecycle-fields-green1016`），规格复核关闭 P2，质量复核通过。5b 八类场景与完整验收实施中。

5a 生命周期检查点：新增只读导出/到期清理端口与 SQLite Adapter，账户导出注入配置好的数据库、聚合预算计数并白名单投影业务字段；清理默认 dry-run，只按指定用户和 UTC 截止时刻处理正文，保留正式记录、防重事实及预算。新服务实例恢复、目录依赖失效、偏移时间比较及清理回滚均有目标测试。首轮 45 passed / 5 failed 为过期数据准备和旧 API 测试未初始化数据库；修正隔离时钟/数据库后 49 passed / 1 failed，余下一项是初始化后注册正常生成的迁移备份不再为空。明确检查两个既有迁移备份并保留导出前后 ZIP 列表完全相等，最终 **50 passed，9.93 秒**（`.tmp/s2-lifecycle-verified1016`）。独立审查待完成；5b 场景与最终回归尚未完成。

- [x] tests添加重启创建新Service后恢复相同rounds/version/item映射；目录版本改变仅使相关项失效；cancel不删已保存记录。
- [x] ExportAccountData 注入可只读的草稿/预算导出端口，不从API外自行选择生产数据库。ZIP新增 entry-drafts.json，包含用户业务草稿与来源，不包含凭据、网关正文、隐藏推理。保留现有导出总大小上限。
- [x] 清理功能新增 `backend/application/use_cases/expire_agent_tasks.py`、`backend/tests/application/test_expire_agent_tasks.py`：按服务端clock筛选到期草稿，dry-run默认；apply仅指定用户/期限并用仓储事务删除。立即拒绝到期访问不依赖清理成功。
- [x] S0场景新增 `backend/task_evaluation/scenarios/interactive_entry.json`：充分/模糊/未知份量、两轮上限、部分保存、局部更正、重连、越权8类，确认效果通过API与只读存储双重判分。
- [x] 运行上述目标测试、旧业务/安全测试、总入口全量回归；再离线回放：

```powershell
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s2
```

- [x] 验收报告附一次“整餐→澄清→部分保存→重启恢复→补剩余”的完整轨迹；每步骤明确任务版本、轮数、正式记录数。

2026-10-17 续作检查点：5b 实现及独立规格、质量复核已通过；评估/验收/用户模型准入冻结目标 **111 passed，118.51 秒**，八类交互 CLI **8/8**、原六类基线 CLI **6/6**，前端全量 **251 passed / 37 files，31.08 秒**，构建通过（Vite 9.06 秒，保留既有大包体警告）。发现并修复初始模型接线错误：改为按认证用户连接的 enabled/key 元数据判断是否进入 Runtime，不以旧全局 LLM_ENABLED 误挡；GET 不读取模型连接。完整轨迹及命令见 `docs/evaluation/2026-10-16-s2-entry-acceptance.md`。中断前后端全量结果不可恢复，使用 `.tmp/s2-backend-final1017` 重新执行并保存 JUnit 报告；最终整阶段审查与完整回归仍待返回，S2 暂不标记完成。
