# 通用模型连接与显式验证 Implementation Plan

> **后续修订：** 首版已完成后，用户批准 [2026-10-18 连接测试业务化方案](2026-10-18-connection-business-check.md)。本文中的工具探测／双项展示是历史实施计划，不再是当前准入要求。当前为一个连接测试、内部生成＋业务 JSON 校验、v2 凭证；保持原有安全与工作区约束。首版测试成绩不能充当修订后的回归成绩。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 用户选择委派后才改用 subagent-driven-development。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现通用五步模型配置流程，只有当前配置的基础生成、工具调用双通过后才允许保存启用，并保留可继续使用的旧连接。

**Architecture:** 后端服务商预设与协议 Adapter 分离；现有业务网关不重写。编辑／探测无持久化副作用，单 active + 单 draft envelope 原子更新，后端签名测试凭证绑定配置及 revision。

**Tech Stack:** Python、FastAPI、Pydantic、cryptography、pytest；React、TypeScript、Vitest、Testing Library。

---

## 依据、位置与执行约束

设计：`docs/superpowers/specs/2026-10-17-model-connection-workflow-design.md`。计划编写基线 `aa63c77`。顺序：S0/S1/S2 → **M（本阶段）** → S3 → S4 → S5；原 23 个检查点不重编号，本阶段另有 7 个检查点。

### 2026-10-18 执行状态

在原目录开发分支实施，不创建工作树、不调用真实密钥、不提交／合并／推送。Task 0–6 本地实现与离线验收完成：复审修正后后端全量业务 2012 项、配置独立分组 6 项、前端 276 项及生产构建通过；只读复审无遗留发现，差异检查通过。真实 SDK／供应商验收及生产发布未执行。实际证据见 `docs/evaluation/2026-10-17-model-connection-workflow.md`。

以下检查点汇总是执行状态事实源；后文细项和示例保留原计划形态，不表示每个示例命令、辅助函数名及建议提交都被原样执行。没有执行建议提交。测试先行实际 RED/GREEN 证据、环境纠偏及最终数量记录于 evaluation 文档，不能用计划中的预期结果替代。

- [x] Task 0：隔离合成基线与现状记录。
- [x] Task 1：服务商注册、工作区兼容与 CAS／原子失败测试。
- [x] Task 2：双协议有界探测、严格工具参数及可终止慢流边界。
- [x] Task 3：当前表单预览、复用确认、共享限流与绑定验证凭证。
- [x] Task 4：草稿／启用／撤销闭环、旧入口门槛、导出及删除。
- [x] Task 5：五步页面、迟到结果保护、POP 离页确认与 AbortSignal；最新前端 276 项及构建通过。
- [x] Task 6：离线验收、修正后后端完整回归、独立复审及最终文档核对通过；不含真实 Provider 验收或 Git 集成。

首次全量因命令显式固定 SQLite 路径使部分只覆写 DATA_DIR 的旧 fixture 共享数据库，结果 1983 passed / 9 failed；清空 SQLite 全局覆盖后四个相关套件 39 passed。最终全量必须使用下述空覆盖命令，不修改业务断言来掩盖环境污染。

计划编写时用户只要求计划。后续用户已授权开始落地，采用当前会话逐项实施，并明确选择本次不备份、只创建开发分支；已在原目录创建 `codex/model-connection-workflow`，不新增工作树、不写正式数据库。此例外不取消 AGENTS.md 对未来分支的默认备份规则。真实模型请求、正式数据写入和自动提交／推送仍未获授权。起点 main 有 3 个未推送提交以及用户无关文件，不能将未跟踪文件打包提交。

不为文档编写创建 worktree。之后若创建开发分支／工作树，必须先遵循根 AGENTS.md 备份、校验主库，再设置隔离 DATA_DIR 和 SQLite 路径；配置密钥、账户文件不得打印或提交。所有代码路径相对实施 checkout，以下 PowerShell 均从该 checkout 根目录执行。

## 文件分工

| 文件 | 责任 |
| --- | --- |
| `backend/domain/model_connection.py` | 连接、工作区 envelope、预览输入和探测结果契约；schema 1 兼容 |
| `backend/domain/model_provider.py`（新） | ProviderPreset 与注册／查找；预设不含可执行配置 |
| `backend/application/ports/model_verification.py`（新） | issue/verify 的可注入 Interface |
| `backend/application/ports/model_gateway.py` | 增加基础生成探测，不改现有业务方法 |
| `backend/application/ports/model_connection_repository.py` | 工作区读取／CAS，保留 active 兼容读 |
| `backend/application/use_cases/model_connection_preview.py`（新） | 当前输入解析、凭据复用确认、限流、探测、签发 |
| `backend/application/use_cases/model_connection_workspace.py`（新） | 保存草稿、验证启用、停用、清密钥 |
| `backend/application/use_cases/model_settings.py` | 既有用例委派，删除宽松启用路径 |
| `backend/infrastructure/model_gateway/protocol_registry.py`（新） | 显式协议 → Adapter 工厂，不容忍未知协议 |
| `backend/infrastructure/model_gateway/factory.py` | 统一地址解析、端点校验、客户端生命周期 |
| `backend/infrastructure/model_gateway/preview_process.py`（新） | 设置探测 spawn 隔离、总期限强制终止、限长脱敏 IPC；不用于业务 Runtime |
| `backend/domain/model_endpoint_policy.py` | 纯 URL 规范化与实际请求 DNS 校验分离，DNS 在探测子进程内受总期限约束 |
| `backend/infrastructure/model_gateway/openai_responses.py`、`openai_chat_completions.py` | 两种协议各自的探测实现 |
| `backend/infrastructure/settings/model_verification.py`（新） | HKDF 派生、HMAC token、时间验证 |
| `backend/infrastructure/settings/file_model_connection_repository.py` | envelope 兼容、进程内 CAS、原子替换 |
| `backend/api/settings.py`、`backend/schemas.py`、`backend/domain/errors.py`、`backend/i18n.py` | HTTP 契约、严格验证及脱敏错误 |
| `backend/application/use_cases/export_account_data.py` | active/draft 白名单投影 |
| `frontend/src/types/index.ts`、`frontend/src/services/api.ts` | 新类型及预览／保存请求 |
| `frontend/src/hooks/useModelSettings.ts` | active/draft/editing 状态和迟到结果保护 |
| `frontend/src/pages/settings/ModelSettings.tsx` | 五步表单和明确生效状态 |
| `frontend/src/pages/settings/UnsavedModelChanges.tsx`、`frontend/src/App.tsx` | DataRouter 离页／历史后退保护，保持既有路由表 |
| `frontend/src/i18n/resources/zh-CN.ts`、`en-US.ts` | 双语提示、费用和目标确认文案 |
| `frontend/src/styles/index.css` | 仅当现有样式无法表达分步、状态时局部补充 |

新增测试文件在各任务明确列出。既有业务、安全、导出测试按失败原因更新，不靠删除断言过关。

## Task 0：建立安全、可重放的基线

**Files:** Create `docs/evaluation/2026-10-17-model-connection-workflow.md`；其余只读。

- [x] 核对分支、HEAD、变更和解释器；不沿用旧通过数作为本阶段成绩。main / aa63c77；pytest 9.1.1，详细记录见本阶段 evaluation 文档。

```powershell
git status --short --branch
git rev-parse HEAD
git worktree list
$modelPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $modelPython -m pytest --version
```

- [ ] 建立忽略的合成数据目录；必须覆盖生成器常量，禁止直接运行会写 backend/data 的脚本。

```powershell
$modelTestData = Join-Path (Get-Location).Path '.tmp\model-connection-test-data'
New-Item -ItemType Directory -Path $modelTestData -Force | Out-Null
$env:DATA_DIR = $modelTestData
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
& $modelPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
& $modelPython -m pytest backend/tests/test_model_settings_api.py backend/tests/application/test_model_settings.py backend/tests/test_model_protocol_adapters.py backend/tests/infrastructure/test_model_endpoint_policy.py backend/tests/infrastructure/test_model_connection_storage.py backend/tests/test_s2_model_availability.py -q -p no:cacheprovider
npm --prefix frontend test
npm --prefix frontend run build
```

- [x] 记录退出码、数量、耗时、环境问题。新用例显式隔离临时 DATA_DIR／数据库并注入 Fake SDK；全局 LLM_ENABLED=false 不是阻断设置探测外网的充分措施。全局 SQLITE_DATABASE_PATH 为空让旧 fixture 的 DATA_DIR 继续控制路径，新 API fixture 显式固定其自己的临时数据库。
- [x] 在验收文档登记改造前行为：先保存才能加载、工具探测无基础探测、未测试可启用。未执行真实请求；本轮不自动提交。

## Task 1：连接工作区、服务商预设与版本契约

**Files:** Create `backend/domain/model_provider.py`、`backend/tests/domain/test_model_provider.py`、`backend/tests/infrastructure/test_model_connection_workspace_storage.py`；Modify 两个连接契约文件及文件仓储。

- [ ] 写失败测试：旧 JSON 无写入映射 active；draft 与 active 独立；CAS 冲突；原子替换失败旧文件不变；保存草稿不改变 Runtime get() 的返回值；清 active 密钥禁用 active。

```python
def test_saving_disabled_draft_preserves_active(tmp_path):
    from backend.domain.model_connection import ModelConnection, ModelConnectionWorkspace
    from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository

    repo = FileModelConnectionRepository(tmp_path)
    active = ModelConnection(provider="custom", protocol="chat_completions", model="old", enabled=True)
    repo.save("user-a", active)
    before = repo.get_workspace("user-a")
    draft = active.model_copy(update={"model": "candidate", "enabled": False})
    after = repo.compare_and_set("user-a", expected_revision=before.revision,
        workspace=ModelConnectionWorkspace(revision=before.revision + 1, active=active, draft=draft))
    assert after.draft.model == "candidate"
    assert repo.get("user-a").model == "old"
```

- [ ] RED：`& $modelPython -m pytest backend/tests/domain/test_model_provider.py backend/tests/infrastructure/test_model_connection_workspace_storage.py -q`；预期新契约尚不存在导致失败。
- [ ] 定义 schema 2 和预设契约。连接新增 provider_id，legacy provider 保留为兼容字段，canonical provider_id 才参与新流程匹配；legacy openai 映射官方预设，custom 映射 custom。缺省预设选择仅为前端空状态，旧记录默认值不当作用户选择。

```python
class ModelConnectionWorkspace(BaseModel):
    schema_version: Literal[2] = 2
    revision: int = Field(default=0, ge=0)
    active: ModelConnection | None = None
    draft: ModelConnection | None = None

class ProviderPreset(BaseModel):
    id: str
    display_name: str
    default_base_url: str | None
    protocols: tuple[Literal["responses", "chat_completions"], ...]
    recommended_protocol: Literal["responses", "chat_completions"]
```

- [ ] 实现 `get_workspace(user_id)`、`compare_and_set(user_id, *, expected_revision, workspace)`；在 user_lifecycle_guard + 同一文件锁内读、比对、原子替换，返回落盘快照。create revision=0，写入必须精确 +1。兼容 `save` 不允许写出破坏 envelope 的旧格式；明确只有进程内 CAS 保证。
- [ ] 预设注册允许注入合成 ProviderPreset；custom 地址必填，未知 provider_id/protocol 拒绝。provider_id 仅允许稳定短 ID，不接受动态导入。
- [ ] GREEN：重跑两组新增测试及 `test_model_connection_storage.py`、`test_s2_model_availability.py`。建议提交：`feat(models): add provider presets and versioned connection workspace`。

## Task 2：复用协议 Adapter，添加有界双项探测

**Files:** Create `backend/infrastructure/model_gateway/protocol_registry.py`、`backend/tests/test_model_connection_probes.py`；Modify 网关 port、factory 及两 Adapter。

- [ ] 使用 Fake SDK 参数化两个协议，写生成非空／空白、工具参数正确／错误／无调用、usage 缺失、timeout/output limit、未知协议拒绝、客户端关闭测试。新增 probe_generation；probe_tool_call 返回标准结果，不允许只验函数名。

```python
@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_tool_probe_rejects_false_arguments(protocol):
    # 此文件内 make_probe_adapter 用 SimpleNamespace 构造相应 SDK 响应，绝不创建真实 SDK。
    adapter = make_probe_adapter(protocol, tool_name="connection_probe", arguments='{"ok": false}')
    with pytest.raises(ValueError):
        adapter.probe_tool_call()
```

- [ ] `make_probe_adapter` 在测试文件定义：responses.create 返回 output 中 function_call 的 name/arguments；chat.completions.create 返回 choices[0].message.tool_calls 中 function.name/arguments；generation 分别返回 output_text/message.content；Fake 记录 kwargs，Fake close 只增加计数。
- [ ] RED：`& $modelPython -m pytest backend/tests/test_model_connection_probes.py -q`；确认不是外网／环境失败。
- [ ] 定义共同结果：`ProbeResult(status, latency_ms, error_code, usage)`；status 仅 passed/failed/not_run，usage 缺失为 None。Adapter 抛出的外部异常在用例层标准化，不把供应商正文放进结果。
- [ ] 工具验证使用 `json.loads(arguments)` + 严格布尔类型校验（`value.get("ok") is True`，禁止字符串 true 和数字 1）；仅合成工具，不调业务工具。
- [ ] 探测输出上限 128、单次取剩余 timeout、SDK max_retries=0；注册表显式按协议创建 Adapter；base_url 由连接解析给所有服务商统一使用；清理客户端包括失败路径。Factory 的业务兼容不改变现有 payload 安全投影。
- [ ] GREEN：新增测试、`test_model_protocol_adapters.py`、`test_model_endpoint_policy.py`、`test_agent_boundary.py`。建议提交：`feat(models): add bounded generation and tool probes`。

## Task 3：当前表单预览、目标确认与后端验证凭证

**Files:** Create verification port/implementation、preview 用例、`backend/tests/application/test_model_connection_preview.py`、`backend/tests/infrastructure/test_model_verification.py`；Modify schemas、errors、i18n、settings router。

- [ ] 先定义严格输入，`extra="forbid"`；preview models 不要求 model，其余要求非空 model。凭据互斥验证在构造 SDK 前完成。

```python
class ModelPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=64)
    protocol: Literal["responses", "chat_completions"]
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    credential_mode: Literal["new", "reuse_active", "reuse_draft"]
    api_key: SecretStr | None = None
    confirm_credential_reuse: bool = False
```

- [ ] 写失败测试：表单候选与 active 不同，Fake 只收到候选；所有成功／失败探测前后文件字节相同；调用最多两次；基础失败工具 not_run；两项通过才发 token。跨地址复用无确认必须零调用拒绝，确认后才可发送；其他用户不能引用凭据。
- [ ] 写 token 测试：注入固定时钟，15 分钟过期、未来签发超出 30 秒拒绝、篡改、换用户、换 revision、换字段、换 key、不同 probe_version 拒绝。token 中不含原文/密文，Fernet 随机加密同一 key 不影响 keyed fingerprint。
- [ ] RED：`& $modelPython -m pytest backend/tests/application/test_model_connection_preview.py backend/tests/infrastructure/test_model_verification.py -q`。
- [ ] 实现 `VerificationBinding(user_id, expected_revision, provider_id, base_url, protocol, model, credential_fingerprint, probe_version)`；`ModelVerification.issue(binding)`、`verify(token,binding)`，canonical JSON 编码 HMAC、constant-time compare、限制 token 长度 4096。仅双通过路径调用 issue。实现 HKDF info 与 TTL 使用设计值，不新增秘密文件。
- [ ] 实现 preview 用例：认证→校验字段→解析 canonical 目标→校验 revision/凭据选择→获取共用预览限流 lease→构造 Fake 可注入 gateway→执行探测→关闭客户端并释放 lease。模型列表返回 `{models, truncated}`，异常区分不支持列表与认证/网络错误，手填不被阻断。
- [ ] 复用 ProcessRateLimiter，app 级设置预览实例按用户共用 6 次/分钟与并发 1；测试 7 次返回 429、并发第二次拒绝、失败释放 lease、用户隔离。传入的策略对象必须提供该现有算法读取的四个属性；预览仍仅允许认证用户，不因此开放匿名。声明进程重启计数重置，不提供跨进程配额承诺。

```python
@dataclass(frozen=True)
class PreviewRatePolicy:
    requests_per_minute: int = 6
    concurrent_runs: int = 1
    anonymous_requests_per_minute: int = 0
    anonymous_concurrent_runs: int = 0
```
- [ ] 接线 providers、workspace、preview/models、preview/test 路由；禁止日志记录请求 body/SecretStr 解包值。新增 API 未授权全部 401。
- [ ] GREEN：上述新增测试 + `test_model_settings_api.py`。建议提交：`feat(models): preview draft connections with bound verification receipts`。

## Task 4：保存草稿与启用闭环，封住旧接口绕过

**Files:** Create workspace 用例、`backend/tests/application/test_model_connection_workspace.py`、`backend/tests/test_model_connection_workflow_api.py`；Modify model_settings、settings router、schemas、导出用例、相关导出及账户删除测试。

- [ ] 写失败测试：无 token 启用拒绝；仅工具通过旧 success 拒绝；两项通过匹配 token 可以启用；换字段／换用户／过期／CAS 冲突拒绝且原文件不变；草稿保存不改 active；重复 activate 不重复 revision；删除账户后不能保存。

```python
def test_old_put_cannot_enable_without_verification(client, auth_headers):
    response = client.put("/settings/model", headers=auth_headers, json={
        "provider": "custom", "protocol": "chat_completions",
        "base_url": "https://models.example.com/v1", "model": "candidate",
        "api_key": "synthetic-key", "enabled": True,
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODEL_VERIFICATION_REQUIRED"
```

- [ ] API 测试 `client/auth_headers` 在本文件定义 fixture：复用既有 build_client/register 逻辑，新临时 DATA_DIR、合成加密 key、Fake SDK factory，使用注入 resolver 避免真实 DNS。不得改生产 .env。
- [ ] RED：`& $modelPython -m pytest backend/tests/application/test_model_connection_workspace.py backend/tests/test_model_connection_workflow_api.py -q`。
- [ ] 实现 draft/activate/disable：先读取 workspace、解析实际凭据、验证 token（activate），构造 revision+1，再仓储 CAS。任何外部请求不得放在仓储锁内；activate 不触发模型请求。revision/绑定不一致用 409，禁止服务端自行刷新重试。
- [ ] 兼容旧 routes：所有 enabled=true 路径委派同一个 activate；enabled=false 的旧 PUT 只存 draft，旧 GET 仍只读 active。旧无 body list/test 对 active 进行有界探测但不改文件；双通过可带新增 verification_token，保留旧 success/model/protocol/tested_at 字段。
- [ ] 导出 envelope 的 active 和 draft，各投影必要字段，不导出 hint/密文/token/指纹。public workspace 可以显示 hint；账户删除后整个用户目录清理，预览 limiter 增加按用户清桶方法并由删除流程调用，无敏感缓存。
- [ ] 更新旧用例中“无测试直接 enabled”的 fixture：通过 Fake 双探测或构造合成历史记录验证兼容，不删除认证、加密、用户隔离断言。旧 active 继续可用但重启用需新凭证；关入口不自动删草稿。
- [ ] GREEN：新增测试 + 旧 settings、account export、delete account、S2 model availability、agent boundary 套件。建议提交：`feat(models): enforce verified activation and preserve active connections`。

## Task 5：五步页面、编辑态与迟到结果隔离

**Files:** Modify ModelSettings 页面、useModelSettings hook、types、api、双语资源；Create `frontend/src/pages/settings/ModelSettings.test.tsx`、`frontend/src/hooks/useModelSettings.test.tsx`。

- [ ] 测试使用 Testing Library + vi.mock(api)，不访问真实 backend；先测试 provider 未选、获取失败可手填、测试调用包含当前表单、双通过前启用 disabled、保存草稿仍显示旧 active。

```tsx
it('invalidates verification when the selected model changes', async () => {
  render(<MemoryRouter><ModelSettings /></MemoryRouter>)
  await completeModelFormAndPassProbe()
  expect(screen.getByRole('button', { name: '保存并启用' })).toBeEnabled()
  fireEvent.change(screen.getByLabelText('模型名称'), { target: { value: 'another-model' } })
  expect(screen.getByRole('button', { name: '保存并启用' })).toBeDisabled()
})
```

- [ ] 本文件定义 `completeModelFormAndPassProbe`：用合成 preset、填 HTTPS 地址和 synthetic key、填 model、点击测试并 await 双 passed；i18n 使用项目现有初始化机制固定中文。测试 deferred Promise 返回 A 请求后先改 B 表单，A 的成功 token 不能赋给 B。
- [ ] RED：`npm --prefix frontend test -- src/pages/settings/ModelSettings.test.tsx src/hooks/useModelSettings.test.tsx`。
- [ ] hook 区分 workspace、editing、models、probeResult、verificationToken 和 editGeneration；active 刷新不重置未保存表单。每次关键编辑 +1 generation 并清 token；请求成功只在 generation 匹配时生效。离页清明文 key、不落浏览器存储。
- [ ] 页面实现五步：服务商动态选项→地址／凭据选择→获取或手填→费用提示和分项测试→停用草稿／保存启用。高级协议选择必须为预设支持集；custom 明确选择现有协议。展示当前 active 和 draft 独立加载入口。
- [ ] 跨地址复用弹出来源／目标确认，取消不得请求；默认切换为 new。测试／列表按钮不提交整个 form；拒绝隐式回车触发真实探测。未保存离页确认、409 保留编辑、重复点击 busy、防止密码显示到反馈。
- [ ] 对 active 的“停用”和“清密钥”独立按钮须确认；清除 draft 不影响 active。测试基础通过、工具失败时解释“能生成，但不满足本项目 Agent 能力”。不显示“测试通过=业务安全”。
- [ ] GREEN：目标前端测试、`npm --prefix frontend test`、`npm --prefix frontend run build`。建议提交：`feat(settings): guide provider setup through draft verification and activation`。

## Task 6：集成验收、隐私与交付

**Files:** Create `backend/tests/test_model_connection_workflow_acceptance.py`；Modify README.md、`docs/agent-task-contracts.md`、本阶段 evaluation 文档和总计划状态。

- [ ] 写端到端失败测试：注册→读 active→新表单模型列表→双探测→保存草稿→刷新→重新测试草稿→激活→业务请求读新 active。每次断言 Fake 调用数、目标、payload 无档案；前后旧配置保留或变更符合设计。
- [ ] 参数化回归：旧 enabled 记录继续执行、草稿不会进入 S2、清密钥撤销、测试失败 active 不变、并发两个标签页只有一项 CAS 生效、加载大模型列表截断、无 usage 不伪造零。
- [ ] RED/GREEN：`& $modelPython -m pytest backend/tests/test_model_connection_workflow_acceptance.py -q`；全部外网访问在测试中使用 monkeypatch connect/create_connection 的禁止桩，TestClient 不需要真实监听端口。
- [ ] 全量后端业务测试与配置优先级测试分组运行，避免全局 DATA_DIR 覆盖 config 断言。先使用 Task 0 合成数据环境：

```powershell
$env:SQLITE_DATABASE_PATH = ''
& $modelPython -m pytest backend/tests --ignore=backend/tests/test_config.py -q -p no:cacheprovider --junitxml=.tmp/model-connection-business.xml
npm --prefix frontend test
npm --prefix frontend run build
```

- [ ] 保存本轮测试环境值，临时移除 DATA_DIR/SQLITE_DATABASE_PATH 后单独跑 config；必须在 finally 恢复，不把后续测试指向主库。

```powershell
$modelSavedData = $env:DATA_DIR
$modelSavedDb = $env:SQLITE_DATABASE_PATH
try {
    Remove-Item Env:DATA_DIR -ErrorAction SilentlyContinue
    Remove-Item Env:SQLITE_DATABASE_PATH -ErrorAction SilentlyContinue
    & $modelPython -m pytest backend/tests/test_config.py -q -p no:cacheprovider --junitxml=.tmp/model-connection-config.xml
    if ($LASTEXITCODE -ne 0) { throw 'Configuration tests failed.' }
}
finally {
    $env:DATA_DIR = $modelSavedData
    $env:SQLITE_DATABASE_PATH = $modelSavedDb
}
```

- [ ] 每个 native 测试命令执行后立即确认 LASTEXITCODE，不靠最后一个命令掩盖前面失败。记录实际分组 case 数与耗时；不沿用 1956，不将 mock token 估算当真实性能数据。
- [ ] 文档说明五步流程、失败处理、历史配置兼容、单进程限制、输出限制不兼容时失败、无真实模型验收。README 启动命令保持原脚本；工作树自动隔离脚本不在本阶段。
- [ ] 独立核查所有外网入口共用 endpoint policy、认证、限流；旧 PUT 无绕过。`git diff --check`、人工检查 staged 文件清单，禁止加入 .env、用户 JSON、数据库或备份。代码审查按 requesting-code-review 技能；未获用户委派选择时不自动启动子代理。
- [ ] 只有自动化和审查通过才标记 M 完成。真实模型冒烟须另取明确许可和预算，不能因用户确认设计就消费其密钥。建议提交：`test(models): verify connection workflow privacy and compatibility`。

## 验收矩阵与不宣称范围

### 独立复审修正（2026-10-18）

用户已允许一个只读独立审查者。首轮指出同步请求无法保证慢流总超时，以及历史后退保护、AbortSignal、导出验证字段缺失。已分别补充可强制终止的设置探测子进程、DataRouter blocker、预览取消等待及导出白名单，并添加慢流无遗留进程／历史后退／卸载取消／导出字段回归。原审查者复核确认四项关闭，未发现新问题。修正后的全量回归另行记录；此前 2007 项后端通过不当作修正后最终成绩。

| 需求 | 实施与证据 |
| --- | --- |
| 服务商／协议分离、新模型手填 | Task 1、2、5：合成预设无需修改页面或业务 |
| 测当前表单，探测不保存 | Task 3、6：捕获输入及文件字节比较 |
| 双通过才能启用 | Task 2–4：真实解析 Fake 响应、签名验证、旧入口拒绝 |
| 草稿不替换当前连接 | Task 1、4–6：仓储、API、页面三层验证 |
| 换字段／用户／密钥／版本失效 | Task 3–5：token 绑定和迟到结果测试 |
| 费用有限、无自动请求 | Task 2、3、5：调用计数、timeout、输出限制、限流 |
| 目标变更不泄露旧 key | Task 3、5：前后端确认、未确认零调用 |
| 旧配置与 S2 可用性 | Task 1、4、6：兼容读取、active-only、业务回归 |
| 导出／删除隐私 | Task 4、6：两槽投影、密钥／指纹不出现、删除撤销 |

本阶段不承诺所有供应商兼容、全部结构化能力已验证、生产多进程一致性、DNS rebinding 消除、医疗正确性或性能提升百分比。S3 仍需业务约束测试，S4 仍需同等安全性能对照，S5 仍需获授权后的真实模型验收。

## 完成后的交接

交付实际提交、测试报告、默认行为和剩余风险；先检查远端连接再决定发布，不将本地 ahead 当远端同步。执行方式由用户选择：当前会话逐项执行，或授权后按独立任务委派审查；本计划本身不授权实现或新增分支。
