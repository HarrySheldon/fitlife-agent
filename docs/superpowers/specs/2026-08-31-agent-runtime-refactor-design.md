# FitLife Agent Runtime 重构设计

**状态：** 待用户书面审阅  
**日期：** 2026-08-31  
**基线分支：** `codex/pending-plans-integration`  
**范围：** 显式 Python 工作流、运行状态与控制、错误分层、统一配置解析、医疗安全后置审核、Evaluation 隔离、接口文档

## 1. 背景

当前 Agent 主链路使用 LangGraph 串联 `planner`、数据加载、分析、检索、生成、校验、写作和 Trace 节点。实际流程只有一个简单条件分支，尚未使用 LangGraph Checkpoint、Interrupt、恢复或人工审批能力。与此同时，模型连接解析、工作流执行、错误归一化、Trace 构造和响应格式仍集中在 `backend/agent/graph.py` 中。

这使以下横切能力难以统一实现：

- 整体 deadline、有限重试和取消；
- 节点耗时、Token、重试次数和失败阶段；
- 运行状态持久化与查询；
- 医疗内容输入和输出安全审核；
- 配置优先级、动态策略和不可变运行快照；
- Evaluation Case 级错误隔离；
- 用户可见错误与内部错误严格分离。

完整 pi 源码提供了可借鉴的设计：进程内单 Active Run、`AbortController`、Append-only Session Record、Operation/Step/Tool/Usage 记录、SQLite writer lease、公共错误与内部错误分离、显式 Telemetry Context、配置作用域合并和 last-known-good reload。不过 pi 的下一代 `AgentHarness` 执行和恢复方法仍是脚手架，本项目只借鉴其数据模型和模块接口，不引入 pi 依赖，也不复制其 Coding Agent 的分支树、Lane 和 Fork 功能。

## 2. 核心决策

### 2.1 使用显式 Python 工作流替换 LangGraph 主链路

FitLife 的默认 Agent 执行器改为普通 Python 顺序工作流。流程分支由类型化代码显式表达，所有步骤必须通过 `RuntimeContext.step()` 或 `RuntimeContext.tool()` 执行。

本次完成迁移后，后端主链路不再依赖 LangGraph。若未来出现真正需要长时间挂起、人工审批或复杂图恢复的工作流，应通过新的执行器 Adapter 引入，而不是重新耦合业务工作流。

### 2.2 不开发通用 Agent 框架

只实现 FitLife 需要的能力：

- 固定步骤和条件分支；
- 运行生命周期与事件；
- Retry、deadline、取消和预算；
- 工具调用包装；
- Safety 硬门；
- 状态、Checkpoint 和 Trace 接口；
- 受控错误策略。

不实现通用图 DSL、任意拓扑、会话分支树、分布式调度器或 Prompt 编排语言。

### 2.3 运行状态、Checkpoint 和 Trace 分离

- `AgentRunRepository` 保存权威运行状态和 Append-only 事件。
- `CheckpointStore` 保存工作流恢复所需的节点状态。
- `TelemetryContext` 只记录诊断信息；Telemetry 失败不得改变业务结果。
- 会话消息存储与以上三者分离，本次不新增多轮会话树。

### 2.4 安全规则不可被动态配置降低

输入长度、医疗高风险规则、计划激活校验、Endpoint 安全和 Secret 处理属于代码内硬限制。部署配置、用户配置和请求覆盖只能收紧或在白名单范围内调整，不能关闭硬限制。

## 3. 目标

- 用类型化 Python 工作流完整复现现有 Agent 行为。
- 所有 Agent 入口经过同一个 `AgentRuntime`。
- 为每次请求生成可查询的 `run_id` 和 `request_id`，包括失败请求。
- 自动处理瞬时错误，只有最终不可恢复结果才展示给用户。
- 为所有公共错误提供稳定代码、本地化消息、可操作建议和追踪编号。
- 为运行保存不可变配置快照。
- 对普通聊天增加输入限制和医疗输出后置审核。
- 为 `/chat`、`/coach/action` 和 `/eval/run` 增加统一限流入口。
- Evaluation 单 Case 失败不终止批次，并明确区分 Mock 与 Live。
- 输出一份面向维护者的正式接口文档和迁移说明。

## 4. 非目标

- 不实现后台分布式任务队列。
- 不实现跨机器 Workflow Engine。
- 不实现 Agent 会话 Fork、Branch 或 Lane。
- 不允许模型直接写入正式饮食、训练、计划或档案数据。
- 不把 Trace 作为恢复来源。
- 不在 Trace、错误响应或 Evaluation 报告中保存 API Key、完整 Prompt、完整模型响应或敏感健康原文。
- 不为了重构改变现有业务路由和成功响应的主要字段。

## 5. 模块结构

```text
backend/agent/
├── contracts.py               AgentCommand、AgentResult、Workflow 接口
├── workflow.py                FitLife 显式 Python 工作流
├── runtime.py                 AgentRuntime 和 RuntimeContext
├── policy.py                  RuntimePolicy、RetryPolicy、BudgetPolicy
├── failures.py                RuntimeFailure、Disposition、分类器
├── safety.py                  输入门、输出审核和安全投影
├── telemetry.py               TelemetryContext 接口和内存 Adapter
├── persistence.py             Run/RunEvent/Checkpoint 接口
├── state.py                   类型化工作流状态
├── planner.py                 现有 Planner 模型
├── generator.py               确定性计划生成
└── validator.py               确定性计划校验

backend/infrastructure/agent_runtime/
├── sqlite_run_repository.py   SQLite 运行状态和事件 Adapter
├── memory_run_repository.py   测试 Adapter
├── sqlite_checkpoint_store.py Checkpoint Adapter
└── factory.py                 生产依赖组装

backend/configuration/
├── models.py                  类型化部署配置和动态策略
├── resolver.py                EffectiveRunConfig 解析
├── store.py                   动态策略存储接口
└── diagnostics.py             配置加载诊断
```

`backend/agent/graph.py` 在兼容迁移完成后删除。旧 `run_fitlife_agent()` 名称可短期保留为薄兼容函数，但只允许调用 `AgentRuntime.execute()`，不得继续持有工作流逻辑。

## 6. 外部接口

### 6.1 AgentRuntime

```python
class AgentRuntime(Protocol):
    async def execute(
        self,
        command: AgentCommand,
        workflow: AgentWorkflow,
    ) -> AgentOutcome: ...

    async def get_status(
        self,
        run_id: str,
        user_id: str | None,
    ) -> AgentRunSnapshot: ...

    async def cancel(
        self,
        run_id: str,
        user_id: str | None,
    ) -> CancelResult: ...
```

接口不暴露 Repository、模型 SDK、Retry 实现、Telemetry Span 或数据库对象。

### 6.2 AgentCommand

```python
@dataclass(frozen=True)
class AgentCommand:
    operation: Literal["chat", "coach_action", "plan_review", "weekly_review", "evaluation"]
    question: str
    user_id: str | None
    surface: str | None = None
    context_date: str | None = None
    initial_tool_results: Mapping[str, object] = field(default_factory=dict)
    initial_tool_calls: tuple[str, ...] = ()
```

构造命令前完成 HTTP Schema 校验；Runtime 仍执行字符和 Token 硬限制，防止非 HTTP 调用绕过限制。

### 6.3 AgentWorkflow

```python
class AgentWorkflow(Protocol):
    async def execute(
        self,
        command: AgentCommand,
        context: RuntimeContext,
    ) -> AgentResult: ...
```

### 6.4 RuntimeContext

```python
class RuntimeContext(Protocol):
    async def step(self, name: str, operation: Callable[[], Awaitable[T]]) -> T: ...

    async def tool(
        self,
        name: str,
        replay: Literal["safe", "never"],
        operation: Callable[[], Awaitable[T] | T],
    ) -> T: ...

    def checkpoint(self, name: str, state: Mapping[str, object]) -> None: ...
    def raise_if_cancelled(self) -> None: ...
```

`step()` 负责 deadline、Retry、事件、Trace、失败分类和使用量累计。`tool()` 附加工具名、幂等/重放策略和工具级错误处理。

## 7. 工作流

```text
input_guard
→ planner
→ profile_loader
→ data_analyzer
→ 可选 retriever
→ deterministic_generator
→ deterministic_validator
→ writer
→ safety_reviewer
→ result_projector
```

规则：

- `input_guard` 和 `safety_reviewer` 不允许被 Planner 跳过。
- Writer 不能直接返回公共响应。
- 计划、目标和记录写入仍由确定性用例负责。
- RAG 单路失败可以降级；所有检索失败时由 Safety Policy 决定安全降级或终止。
- 每个模型请求和工具调用都必须位于一个 Runtime Step 内。

## 8. 运行状态与数据模型

### 8.1 agent_runs

```text
id TEXT PRIMARY KEY
request_id TEXT NOT NULL UNIQUE
user_id TEXT NULL
operation TEXT NOT NULL
status TEXT NOT NULL
current_step TEXT NULL
attempt INTEGER NOT NULL DEFAULT 0
created_at TEXT NOT NULL
started_at TEXT NULL
deadline_at TEXT NOT NULL
finished_at TEXT NULL
policy_version TEXT NOT NULL
policy_snapshot_json TEXT NOT NULL
provider TEXT NULL
model TEXT NULL
input_chars INTEGER NOT NULL DEFAULT 0
input_tokens INTEGER NOT NULL DEFAULT 0
output_tokens INTEGER NOT NULL DEFAULT 0
tool_calls INTEGER NOT NULL DEFAULT 0
public_error_code TEXT NULL
internal_error_id TEXT NULL
failure_stage TEXT NULL
version INTEGER NOT NULL DEFAULT 1
```

初期运行仍在请求进程内同步执行，使用 `version` 做乐观并发控制。只有引入多进程后台 Worker 后，才增加 lease owner、fence 和 expiry；本阶段不提前实现租约。

### 8.2 agent_run_events

```text
run_id TEXT NOT NULL
seq INTEGER NOT NULL
event_type TEXT NOT NULL
step TEXT NULL
attempt INTEGER NULL
occurred_at TEXT NOT NULL
payload_json TEXT NOT NULL
PRIMARY KEY (run_id, seq)
```

事件至少包括：

```text
RUN_ACCEPTED, RUN_STARTED, STEP_STARTED, STEP_RETRY_SCHEDULED,
STEP_SUCCEEDED, STEP_FAILED, TOOL_STARTED, TOOL_FINISHED,
SAFETY_DECIDED, RUN_CANCEL_REQUESTED, RUN_SUCCEEDED,
RUN_FAILED, RUN_CANCELLED, RUN_TIMED_OUT
```

事件 Payload 必须先经过字段白名单和脱敏，不能保存任意异常对象。

## 9. Retry、deadline 与取消

- OpenAI SDK 显式设置 `max_retries=0`，由 Runtime 统一控制。
- 默认最大重试次数为 3；初始调用不计入重试次数。
- 只重试连接失败、408、可恢复 409、瞬时 429 和部分 5xx。
- 401、403、模型不存在、输入非法、配额/账单耗尽和安全拒绝不重试。
- 使用指数退避、jitter，并尊重受上限约束的 `Retry-After`。
- 所有尝试共享一个整体 deadline；重试不能重置总超时。
- 取消在退避、模型请求前后和工具调用前后检查。
- 只有 `replay="safe"` 的工具允许自动重放。

## 10. 错误模型

### 10.1 内部错误

```python
@dataclass(frozen=True)
class RuntimeFailure:
    code: str
    category: FailureCategory
    stage: str
    retryable: bool
    attempt: int
    safe_message_key: str
    cause: Exception | None = None
    provider_status: int | None = None
```

内部错误永远不直接序列化。

### 10.2 处理决策

```text
RETRY       在预算内自动重试
FALLBACK    使用受控降级路径继续
ASK_USER    用户修改输入、认证或配置后重试
REFUSE      Safety 安全拒绝
CANCEL      用户或系统取消
FAIL        记录内部事件并返回脱敏公共错误
```

### 10.3 公共错误

```python
class PublicError(BaseModel):
    code: str
    message: str
    action: str | None = None
    retryable: bool = False
    retry_after_ms: int | None = None
    request_id: str
```

只有输入、认证、配置、安全、并发冲突、最终限流/超时和脱敏系统错误允许展示。数据库路径、环境变量名、SQL、堆栈、Provider Body、Prompt、工具参数、密钥状态和内部类名不得展示。

`CREDENTIAL_STORE_UNAVAILABLE` 的公共消息改为通用安全配置不可用；具体 `SETTINGS_ENCRYPTION_KEY` 原因只写内部诊断。

FastAPI 增加未知异常处理器，所有错误保持统一 JSON 结构，并在请求进入时生成 `request_id`。

## 11. 医疗安全

安全处理分为两道不可跳过的硬门：

1. `input_guard`：识别诊断、治疗、急症、自伤、极端节食、危险训练和超出能力范围的请求。
2. `safety_reviewer`：审核最终草稿，输出结构化 `SafetyDecision`。

```python
class SafetyDecision(BaseModel):
    outcome: Literal["allow", "rewrite", "refuse"]
    risk_category: str
    violations: tuple[str, ...]
    required_disclaimer: str | None
```

高风险输入、计划激活和医疗输出审核不可用时 fail-closed。低风险知识问答审核器不可用时返回预置安全说明，不返回未经审核的模型草稿。Safety 事件只记录风险类别、结果和规则版本，不记录敏感原文。

## 12. 配置管理

### 12.1 配置域

```text
DeploymentSettings   启动时静态：数据库、认证、加密、目录、CORS
RuntimePolicy        动态：Retry、Timeout、Budget、RateLimit、Safety、Eval
UserModelSettings    用户模型连接：Provider、协议、模型、Endpoint、加密 Key
RunPolicySnapshot    每次运行解析出的不可变有效配置
```

Secret 继续单独存储和解密，不进入 `RuntimePolicy` 或 Snapshot。

### 12.2 优先级

```text
代码内安全硬限制
> 管理员紧急策略
> 白名单请求覆盖
> 用户允许配置
> 路由策略
> 部署环境
> 安全默认值
```

### 12.3 ConfigurationResolver

```python
class ConfigurationResolver(Protocol):
    def resolve(
        self,
        operation: str,
        user_id: str | None,
        request_overrides: Mapping[str, object] | None = None,
    ) -> EffectiveRunConfig: ...
```

动态配置使用严格 Pydantic 模型和 `extra="forbid"`。更新流程先完整校验新对象，再事务性发布新 revision；失败时继续使用 last-known-good 并记录 Operator Diagnostic。运行中的任务继续使用启动时 Snapshot。

## 13. 限流与预算

本阶段提供进程内、接口统一的限流 Adapter，覆盖 `/chat`、`/coach/action` 和 `/eval/run`：

- 用户级请求速率；
- 用户级并发运行数；
- Evaluation 批次 Case 数；
- 单 Run 字符、Token、模型调用和工具调用预算。

接口预留存储 Adapter，以便未来替换为 Redis；本阶段不引入 Redis。

## 14. Evaluation

Evaluation 在批次启动前验证 Dataset、模型、Policy 和预算。每个 Case 拥有独立子 Run：

```text
Case 成功       → passed/failed checks
Provider 异常   → case_status=error，继续
Case 超时       → case_status=timed_out，继续
预算耗尽        → 停止启动新 Case，剩余 skipped
```

只有 Dataset 损坏、评分器无法初始化或结果存储不可用才终止整个批次。

结果必须包含：

```text
run_id, execution_mode(mock|live), provider, model,
prompt_version, policy_version, dataset_hash,
started_at, finished_at, case status 和归一化错误码
```

测试使用临时结果目录，不允许覆盖正式 `backend/data/eval_results.*`。

## 15. Telemetry

Telemetry 使用显式 Context 接口，不依赖 LangChain 或 LangSmith：

```python
class TelemetryContext(Protocol):
    async def span(self, name: str, attributes: Mapping[str, Scalar]): ...
```

Span 层级：

```text
fitlife.agent.run
├── fitlife.agent.step
│   ├── fitlife.ai.request
│   ├── fitlife.agent.tool
│   └── fitlife.agent.retry_wait
└── fitlife.safety.review
```

记录低基数错误类型、耗时、Token、调用次数、Retry、最终状态和策略版本。默认不记录输入输出正文。提供 No-op 和 In-memory Adapter；生产导出 Adapter 在接口稳定后接入，不作为本阶段完成条件。

## 16. 兼容与迁移

1. 为当前 LangGraph 行为增加合同测试，冻结成功结果和错误行为。
2. 提取类型化命令、状态、结果和纯节点函数。
3. 实现内存 Runtime、错误策略和显式 Python Workflow。
4. 通过兼容函数让现有路由调用新 Runtime。
5. 新旧实现合同测试一致后删除 LangGraph 图和依赖。
6. 增加 SQLite Run Repository、事件和 Checkpoint。
7. 接入配置 Snapshot、Safety、限流和 Evaluation 隔离。
8. 重写正式接口文档并删除过时的 LangGraph 描述。

不改变确定性领域规则、现有用户业务数据格式和前端成功响应的主要字段。错误响应允许新增 `request_id`、`action`、`retryable` 和 `retry_after_ms`。

## 17. 正式文档交付

实现完成后新建或重写 `docs/AGENT_RUNTIME.md`，至少包含：

- 模块图和依赖方向；
- `AgentRuntime`、`AgentWorkflow`、`RuntimeContext` 完整接口；
- 命令、结果、状态和错误类型；
- 工作流节点、顺序和不可跳过约束；
- Run/Event/Checkpoint 数据模型；
- Retry、deadline、取消和幂等规则；
- 公共错误与内部错误映射表；
- 配置优先级和 Snapshot 示例；
- Safety 决策流程；
- Evaluation Mock/Live 运行方式；
- 本地和 Docker 测试命令；
- 从旧 LangGraph 实现迁移说明。

README 只保留用户启动和入口说明，并链接到该文档。

## 18. 测试策略

- `contracts`：类型、序列化和不变量。
- `workflow`：步骤顺序、条件分支和 Safety 必经路径。
- `runtime`：状态机、Retry、deadline、取消、预算和失败决策。
- `persistence`：事务、事件顺序、乐观锁和恢复。
- `configuration`：优先级、硬限制、last-known-good 和 Snapshot 不变性。
- `telemetry`：父子 Span、错误状态、脱敏和 Adapter 失败不影响业务。
- `api`：统一公共错误、Request ID、限流和用户隔离。
- `evaluation`：Case 隔离、超时、预算、Mock/Live 来源和临时输出。
- `regression`：现有 Chat、Coach、Plan、Weekly Report 和 Smart Entry 行为。

测试不得访问真实模型、真实网络或付费 Token。模型和时钟通过 Adapter 注入。

## 19. 验收标准

- 后端 Agent 主链路不再导入 LangGraph。
- 所有 Agent 入口使用同一个 `AgentRuntime`。
- Chat 输入存在字符硬限制和 Token 预算。
- 每个请求在成功和失败时都有 `request_id`；每次 Agent 执行有持久化 `run_id`。
- 运行状态、事件、Checkpoint 和 Trace 职责分离。
- 瞬时 Provider 错误按统一策略有限重试，不发生 SDK 与 Runtime 重试相乘。
- 用户只看到白名单公共错误；内部 Cause 可通过追踪编号定位。
- Safety Reviewer 是 Writer 后不可跳过步骤。
- 动态配置有严格校验、revision、last-known-good 和运行快照。
- `/chat`、`/coach/action`、`/eval/run` 经过统一限流和预算入口。
- Evaluation 单 Case 异常不会中止整个批次，报告明确 Mock/Live。
- 现有 Agent 合同测试和新增 Runtime 测试全部通过。
- `docs/AGENT_RUNTIME.md` 与最终代码接口一致，无过时 LangGraph 描述。

## 20. 实施分段

本规范拆为以下五份顺序执行的实现计划。每份计划都必须产生可测试、可独立审阅的软件；前一份计划通过针对性回归后，才能开始下一份：

1. **工作流重构：** 类型化合同、普通 Python Workflow、兼容入口、移除 LangGraph 主链路。
2. **错误与运行控制：** `RuntimeFailure`、错误策略、Request ID、Retry、deadline、取消、预算。
3. **持久化与 Telemetry：** Run/Event/Checkpoint Repository 和显式 Telemetry Context。
4. **配置与安全：** Configuration Resolver、Snapshot、输入限制、Safety Reviewer、限流。
5. **Evaluation 与文档：** Case 隔离、来源标识、临时输出、正式接口文档和 README 更新。

不得并行引入两套生产 Runtime，也不得保留无法证明用途的抽象层。

## 21. 测试基线前置条件

在隔离工作树上、尚未修改产品代码时，现有测试套件已出现大量失败和错误，且单个账户安全测试在报告失败后未正常退出。因此第一份实现计划的首个任务必须是建立可信基线：

1. 复现并归类现有失败，区分环境、测试夹具、数据库状态和分支代码问题。
2. 记录可稳定通过的 Agent 相关合同测试集合，以及暂未修复的仓库级既有失败。
3. 不得删除、跳过或放宽失败测试来制造绿色结果。
4. 每个实施分段至少运行其针对性测试；最终验收前必须重新运行完整测试套件并如实报告剩余失败。

在可信基线建立前，可以编写实施计划和诊断测试环境，但不能声称重构没有引入回归。
