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

### Task 1：任务版本与计数语义

- [ ] test_task_contracts.py 写共享修订计数测试：

```python
import pytest
from backend.agent.tasks.contracts import next_repair_round

def test_repair_round_not_counted_per_module():
    assert next_repair_round(0) == 1
    assert next_repair_round(1) == 2
    with pytest.raises(ValueError, match="REPAIR_LIMIT"):
        next_repair_round(2)
```

- [ ] RED：`& $taskPython -m pytest backend/tests/test_task_contracts.py -q`。
- [ ] contracts.py 新增纯函数及持久数据类型：

```python
def next_repair_round(current: int) -> int:
    if current not in (0, 1):
        raise ValueError("REPAIR_LIMIT")
    return current + 1
```

TaskRef 定义 task_id/version；RepairRound 定义 round_id/index、pending_domains/completed_domains；TaskBudget 定义已消耗及预留 calls/tokens、预算上限。不得把纯函数当原子计数实现，原子预留由 S2/S3 仓储事务落实。
- [ ] AgentCommand新增可选task_ref，普通chat保持None；AgentRunSnapshot新增task_id/task_version。Runtime创建run时复制关联，Memory/SQLite仓储读写一致。SQLite运行表按其现有初始化/迁移方式增加可空列，不能混用records迁移版本；回归旧运行记录与旧checkpoint可读。
- [ ] 明确错误映射：不存在或他人资源404、旧版本409、同幂等键异请求409、过期410、预算耗尽受控终态；响应沿用 ApplicationError，不暴露资源主人。
- [ ] GREEN：补负数计数、version 单调、重复 round_id 语义；取消/超时只改变当前 run，等待用户任务仍可读取。

### Task 2：业务范围与风险分轴

- [ ] test_task_business_scope.py 测“帮我选股票”无档案/工具读取；“写代码久坐怎么安排训练”不因“代码”拒绝；混合有害任务正常部分不可与有害目标相连。
- [ ] RED：`& $taskPython -m pytest backend/tests/test_task_business_scope.py -q`。
- [ ] business_scope.py 定义 ScopeDecision(scope, allowed_subtasks, refusal_code, needs_clarification)，scope 为 in_scope/out_of_scope/mixed/unclear。明确产品帮助和寒暄允许；高置信无关走固定文案，其余交 Planner，不扩大关键词黑名单。
- [ ] Planner 输出仅为建议，经 policy 产生 allowed_subtasks；风险审核继续调用现有 safety 链，不允许 scope=in_scope 覆盖高风险处置。下游只看到被允许子任务文本。
- [ ] GREEN：对 spy repository/tool 断言拒绝路径调用次数为0；加入提示注入要求绕过业务范围的负例。

### Task 3：按阶段输入白名单与能力约束

- [ ] test_task_input_contracts.py 添加自由文本/嵌套值脱敏和字段排除测试；test_task_capabilities.py 添加模型伪造 user_id 与未授权 domain 的拒绝测试。
- [ ] RED：`& $taskPython -m pytest backend/tests/test_task_input_contracts.py backend/tests/test_task_capabilities.py -q`。
- [ ] input_contracts.py 分 EntryInput、TrainingInput、DietInput、CoordinatorInput、ReviewInput 五种业务 DTO，以及当前chat/coach使用的ChatInput，extra=forbid。字段依据总设计8.2；Builder 不接收全量 state 参数，只接收显式必需数据。ChatInput只含当前问题、允许意图、必要分析摘要/目标/限制、来源与校验结论，按意图选择；用户身份和完整记录不默认发出。
- [ ] 能力纯内核：

```python
def require_domain(domain: str, authorized_domains: frozenset[str]) -> None:
    if domain not in authorized_domains:
        raise PermissionError("DOMAIN_NOT_AUTHORIZED")
```

capabilities.py 同时要求认证上下文传入 owner，仓储查询必须含 owner；领域许可来自持久化用户决定，不能从模型字符串构造。
- [ ] Provider spy 断言实际 messages 没有姓名/联系方式/无关历史，必要过敏限制仍存在。自由文本身份信息使用现有清理能力；处理后若语义不够必须澄清，不能静默丢限制。
- [ ] GREEN：覆盖目录/RAG 注入、旧缓存用户切换、Reviewer 只见必要正文；所有新网关调用有输入构建器。

### Task 4：现有入口接线与生命周期契约

- [ ] test_task_policy_wiring.py通过真实Runtime公开入口与spy仓储测试：明显无关请求不调用context_loader/read_profile/retriever；正常健康问题仍执行必需守卫；typed suggestion无法覆盖权限；Chat Writer实际Provider messages符合ChatInput。
- [ ] RED：`& $taskPython -m pytest backend/tests/test_task_policy_wiring.py -q`。
- [ ] 在graph.py的_LazyFitLifeWorkflow.execute加载业务上下文之前进行范围准入。不能只在workflow.py Planner后拦截，因为当前context_loader已经提前读数据。范围判断使用原始用户任务与页面意图分字段，不能让自动生成的Coach模板遮盖无关用户问题。
- [ ] 固定范围回复通过boundary_workflow执行input_guard/context_guard/safety_reviewer，兼容verify_guard_steps顺序并记录run；不读取用户档案。工作流内范围未确定则Planner判定后再决定profile/analysis/retrieval，普通产品帮助不强制load_profile。
- [ ] 将model_payloads构建入口换为任务专用最小字段投影，再经已有sanitize_context，Provider仍发送清理后的同一载荷。structured_workflow只接受通过DTO构造的业务上下文，不能由模型字段决定allowlist；用现有Provider接线测试保证清理结果没有在Adapter层被重建为全量state。
- [ ] lifecycle约定定义：账户删除使新任务不可恢复；用户导出包含业务草稿；到期410不依赖物理清理。此时先测纯状态/访问契约，S2/S3有真实存储后补账户API集成证据，不在S1写无法运行的新表测试。
- [ ] 将“敏感业务草稿”和“诊断事件”分别定义保留字段；诊断只留类别/版本/计数/时间/task与run ID。持久化接线在 S2/S3 与新表一起完成，不能在本阶段报告存储闭环已完成。
- [ ] 运行任务契约测试及旧安全接线回归：

```powershell
& $taskPython -m pytest backend/tests/test_task_contracts.py backend/tests/test_task_input_contracts.py backend/tests/test_task_capabilities.py backend/tests/test_task_business_scope.py backend/tests/test_task_policy_wiring.py backend/tests/test_safety_public_wiring.py backend/tests/test_safety_write_invariant.py backend/tests/test_safety_writer_payload_reaches_provider.py -q
```

- [ ] 形成检查点：范围策略、风险审核、授权、最小数据各自有独立失败证据，不以一个分类结果替代全部控制。
