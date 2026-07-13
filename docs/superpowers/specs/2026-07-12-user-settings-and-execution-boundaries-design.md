# FitLife 用户设置与双执行链设计

**状态：** 待用户最终审阅  
**日期：** 2026-07-12  
**范围：** 用户设置、确定性核心与 Agent 增强层解耦、页面任务解耦、账号安全和数据自主权

## 1. 背景与问题

FitLife Agent 已经完成可运行的 MVP，但当前实现仍有三个结构性问题：

1. 模型配置来自全局环境变量，无法按用户隔离，也没有安全的用户设置入口。
2. `backend/agent/graph.py` 同时负责固定程序、模型调用和失败降级。模型失败后会返回模板结果，使用户无法判断结果来自规则还是 Agent。
3. 前端页面倾向于把同一业务域中的多个任务放在一个页面组件内。即使使用标签切换，表单状态、请求状态和危险操作仍容易耦合。

本设计将系统定位为一个可运行、可交付的本地优先产品，而不再把所有能力组织成演示页面。

## 2. 核心决策

采用以下总原则：

> 事实、计算、校验和持久化归确定性核心；理解、解释、个性化建议和自然语言交互归 Agent 增强层。Agent 只能提出草案，确定性核心负责校验和写入。

同时采用以下产品规则：

- 复杂编辑使用独立子路由。
- 短确认使用模态框。
- 上下文辅助使用抽屉。
- 不打开新的浏览器窗口。
- 页面入口只负责导航和必要摘要，不承载其他任务的表单。
- 设置页、固定程序和 Agent 都不发起未经用户动作触发的模型请求。

## 3. 目标与非目标

### 3.1 目标

- 为每个用户保存一套独立模型连接。
- 服务端加密保存 API Key，前端永远拿不到明文。
- 支持 OpenAI 官方服务和自定义 OpenAI-compatible 服务。
- 支持 Responses API 和 Chat Completions API。
- 支持中文和英文全站界面。
- 支持公制和英制显示、账号时区、密码修改、会话撤销、数据导出和账号删除。
- 在代码、API、响应元数据、错误处理和测试中解耦固定程序与 Agent。
- 将设置及其他复杂页面拆成面向任务的子路由。

### 3.2 本次不做

- 保存多个模型连接。
- 为不同 Agent 功能分配不同模型。
- 自动测试、自动探测协议或自动获取模型列表。
- 非 OpenAI-compatible 服务的专用 Provider SDK。
- 后台 Agent 定时任务。
- 强制 Agent 使用界面语言回答。
- 真实邮箱或短信验证码。
- 主题、通知和饮食偏好设置。
- 全量迁移到关系型数据库。

## 4. 参考实践

本设计参考但不直接复制以下开源实践：

- [Open WebUI Connections](https://github.com/open-webui/open-webui/blob/main/src/lib/components/chat/Settings/Connections.svelte) 将模型服务建模为独立连接，并区分连接配置与启用状态。本项目采用“连接对象 + 显式启用”的思路，但不采用浏览器 Direct Connection，因为 API Key 必须留在服务端。
- [LiteLLM OpenAI-compatible endpoints](https://docs.litellm.ai/docs/providers/openai_compatible) 使用统一输入隐藏模型地址、模型名称和 Provider 差异。本项目采用 Adapter 思路，不引入完整 LiteLLM 网关。
- [OpenAI Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses) 和 Chat Completions 是两个独立协议。本项目为它们建立两个 Adapter，不假设更换 URL 即可完全兼容。

## 5. 架构方案

采用分层单体，不新增独立 Agent 服务。

```text
backend/
├── api/                    HTTP、鉴权、请求和响应转换
├── application/            业务用例编排
│   ├── settings/
│   ├── account/
│   ├── records/
│   ├── analysis/
│   └── agent/
├── domain/                 纯业务规则，不依赖 FastAPI 和模型 SDK
│   ├── nutrition/
│   ├── workout/
│   ├── targets/
│   ├── planning/
│   └── users/
├── agent/                  Agent Graph、提示词、工具协议
├── model_gateway/          统一模型接口
│   ├── responses_adapter.py
│   └── chat_completions_adapter.py
└── infrastructure/         文件存储、加密和外部 API 实现
```

依赖方向固定为：

```text
API -> Application -> Domain
Agent -> Application 暴露的工具接口
Application -> ModelGateway 接口
Infrastructure -> Repository 和 ModelGateway 实现
```

禁止以下依赖：

- Agent 直接读取或修改 CSV、JSON。
- Agent 直接解密 API Key。
- 模型 Adapter 修改用户业务数据。
- 确定性核心依赖 LangGraph 或 OpenAI SDK。
- API 路由直接包含统计公式、目标公式或安全规则。

## 6. 功能职责边界

| 功能 | 确定性核心 | Agent 增强层 |
| --- | --- | --- |
| 注册、登录、用户隔离 | 完整负责 | 不参与 |
| 语言、单位、时区、模型设置 | 保存、校验、加密、同步 | 不参与 |
| 用户档案 | 表单校验和持久化 | 只读上下文 |
| 饮食记录 | 表单、CSV、字段校验、计算和持久化 | 将自然语言解析成待确认草案 |
| 力量和有氧记录 | 表单、CSV、容量计算和持久化 | 将自然语言解析成待确认草案 |
| 今日、日历和看板 | 生成权威事实和趋势 | 解释事实、回答原因、提出建议 |
| 热量和蛋白质目标 | 公式生成基准值和合理范围 | 提出个性化调整草案 |
| 周报 | 生成客观统计和规则摘要 | 生成重点解读和行为建议 |
| 下周计划 | 生成基础计划并执行硬性校验 | 生成个性化计划草案 |
| Coach 自由问答 | 提供经过校验的数据工具 | 理解问题、选择工具、组织回答 |
| RAG | 检索并返回来源 | 基于检索结果生成回答 |
| 评估 | 计算正确性和接口测试 | 工具调用、引用和回答质量评估 |

确定性结果是权威事实。Agent 输出是解释或草案，不能覆盖原始事实。

## 7. 用户设置数据模型

### 7.1 UserPreferences

```text
language: zh-CN | en-US
unit_system: metric | imperial
timezone: IANA timezone
updated_at: UTC timestamp
```

默认值在注册或首次偏好初始化时确定：

- 支持的浏览器语言，否则使用 `zh-CN`；
- `metric`；
- 浏览器 IANA 时区，否则使用 `Asia/Shanghai`。

### 7.2 ModelConnection

每个用户只保存一个当前连接：

```text
provider: openai | custom
protocol: responses | chat_completions
base_url: string | null
model: string
encrypted_api_key: string | null
enabled: boolean
test_status: untested | success | failed
tested_at: UTC timestamp | null
updated_at: UTC timestamp
```

模型配置更新规则：

- 请求未提供 API Key 时保留旧 Key。
- 只有显式“清除密钥”才删除旧 Key。
- 地址、协议、模型或 Key 变化后，`test_status` 重置为 `untested`。
- 未测试配置允许启用。
- 保存、测试和获取模型列表互不自动触发。

## 8. 持久化与密钥安全

本阶段保持现有用户文件结构，通过 Repository 隔离文件实现：

```text
backend/data/users/<user_id>/
├── preferences.json
├── model_connection.json
├── user_profile.json
├── meals.csv
└── workouts.csv
```

要求：

- JSON 更新采用临时文件和原子替换。
- 用户身份文件写入必须有进程内锁，避免并发覆盖。
- `SETTINGS_ENCRYPTION_KEY` 由部署环境提供，不进入仓库或用户目录。
- API Key 使用认证加密，只有发起模型请求时短暂解密。
- 前端只获得 `api_key_configured` 和掩码提示。
- API 响应、日志、Trace 和数据导出都不能包含 Key 明文、密文或完整第三方错误响应。

未配置 `SETTINGS_ENCRYPTION_KEY` 时：

- 确定性功能和普通偏好继续运行。
- 禁止保存新 API Key。
- Agent 返回 `CREDENTIAL_STORE_UNAVAILABLE`。
- 系统不生成默认加密密钥，也不降级为明文保存。

## 9. 模型连接生命周期

### 9.1 保存与启用

- 用户可以保存并启用未经测试的配置。
- 系统不在保存、启动或后台定时任务中自动测试。
- 配置状态包括未配置、未测试、测试成功、测试失败和已禁用。

### 9.2 获取模型列表

- 只有用户点击“获取模型”时才请求模型服务。
- 获取失败不阻止手动输入模型名称。
- 不支持模型列表接口的服务仍可配置。

### 9.3 测试连接

- 只有用户点击“测试连接”时才执行。
- 测试使用当前选择的协议。
- 测试发送最小工具调用，验证模型满足 Agent 的最低能力，而不只验证 URL 可达。
- 测试结果显示成功状态、协议、模型和响应延迟。
- 测试错误只保存归一化错误类别，不保存原始响应正文。

### 9.4 协议

- OpenAI 官方预设默认使用 Responses API。
- 自定义服务由用户明确选择 Responses API 或 Chat Completions API。
- 系统不自动探测或切换协议。
- 两个 Adapter 都转换成统一的 `ModelRequest` 和 `ModelResult`。

## 10. 自定义地址安全

因为自定义模型请求由后端发起，必须防止 SSRF：

- URL 不允许包含用户名、密码、查询参数或片段。
- 默认只允许 HTTPS。
- 私有地址和 HTTP 只能由部署级配置显式允许，用于本地模型。
- 默认阻止云元数据、回环、链路本地和私有网段。
- 禁止重定向，或对每次重定向重新执行地址校验。
- 限制连接超时、总请求超时和响应体大小。

## 11. 双执行链

### 11.1 确定性执行链

```text
UI -> Analysis API -> Application Use Case
-> Domain 计算或校验 -> Repository -> 结构化结果
```

响应必须包含：

```json
{
  "processing_mode": "deterministic",
  "data": {}
}
```

### 11.2 Agent 执行链

```text
UI 主动请求 AI 解读 -> Agent Use Case
-> 工具接口读取确定性数据 -> Model Gateway
-> Agent 输出校验 -> AI 解读结果
```

响应必须包含：

```json
{
  "processing_mode": "agent",
  "model": "configured-model",
  "answer": "...",
  "sources": [],
  "request_id": "..."
}
```

页面先展示确定性结果，再独立加载 AI 解读。Agent 失败不能影响确定性结果，也不能静默返回模板答案冒充模型成功。

### 11.3 智能记录

```text
自然语言 -> Agent 结构化草案
-> 确定性字段校验 -> 前端确认
-> Records API 持久化
```

Agent 不能直接保存记录。解析失败时保留原始输入，并允许用户切换表单。

### 11.4 计划和目标

- 确定性核心生成基础目标、基础计划和硬性校验。
- Agent 生成个性化调整草案。
- 草案必须经过确定性校验。
- 用户确认后才成为正式计划。
- 校验失败的草案不能激活。

## 12. 错误模型

模型错误归一化为稳定错误码：

- `AI_NOT_CONFIGURED`
- `AI_DISABLED`
- `CREDENTIAL_STORE_UNAVAILABLE`
- `MODEL_AUTH_FAILED`
- `MODEL_NOT_FOUND`
- `MODEL_RATE_LIMITED`
- `MODEL_TIMEOUT`
- `MODEL_PROTOCOL_ERROR`

前端根据语言设置翻译错误码。后端固定消息根据账号语言或 `Accept-Language` 返回，但客户端逻辑不能依赖翻译后的文本。

## 13. API 边界

```text
GET    /settings/preferences
PATCH  /settings/preferences

GET    /settings/model-connection
PUT    /settings/model-connection
DELETE /settings/model-connection/key
POST   /settings/model-connection/test
POST   /settings/model-connection/models

POST   /account/password/change
POST   /account/sessions/revoke-others
GET    /account/export
DELETE /account

/analysis/...  确定性结果
/agent/...     Agent 解读和建议
```

模型测试、模型列表、模型保存、密码修改、会话撤销、数据导出和账号删除必须使用独立应用用例，不能共享一个大而全的设置保存接口。

## 14. 会话、导出与账号删除

用户身份增加 `token_version`：

- Token 包含签发时版本号。
- 修改密码或退出其他设备时递增版本号。
- 旧 Token 随即失效。
- 当前设备获得新 Token。

数据导出为 ZIP，包含档案、偏好、脱敏模型配置、饮食记录、训练记录以及已有计划和报告。导出不包含 Key 明文或密文。

账号删除要求再次输入密码并二次确认。删除流程使会话失效，删除模型连接和业务数据，再删除身份记录。操作必须可安全重试。

## 15. 前端信息架构

设置中心拆成独立任务路由：

```text
/settings
/settings/general
/settings/model
/settings/security
/settings/security/password
/settings/privacy
/settings/privacy/delete
```

页面职责：

- `/settings` 只展示设置入口和说明，右侧只保留统一进入箭头，不展示“中文、公制、未测试、2 项、管理”等附加文字。
- `/settings/general` 只管理语言、单位和时区。
- `/settings/model` 只管理当前模型连接。
- `/settings/security` 只展示安全任务入口。
- `/settings/security/password` 是独立修改密码任务页。
- `/settings/privacy` 管理导出和危险操作入口。
- `/settings/privacy/delete` 是独立账号删除任务页。

实际浏览器新窗口不用于业务编辑。独立路由提供完整返回路径、移动端兼容和可测试状态隔离。

## 16. 通用设置交互

### 16.1 语言

- 登录前从浏览器缓存读取。
- 登录后以账号设置为准并回写浏览器缓存。
- 切换后立即更新前端并同步后端。
- 静态界面、表单、状态、校验和固定后端消息都参与 i18n。
- Agent 回答跟随用户提问语言，不强制跟随界面语言。

### 16.2 单位

采用说明型单选列表：

```text
(*) 公制
    kg · cm · km

( ) 英制
    lb · ft/in · mi
```

后端和领域层统一保存、计算 `kg/cm` 等标准公制值。前端负责输入和展示转换。切换单位不能修改历史记录的真实值。传给 Agent 的展示上下文包含用户单位。

### 16.3 时区

- 使用账号级 IANA 时区。
- 注册或首次初始化时使用浏览器时区。
- 后端按账号时区计算“今天”和周报范围。
- 修改时区不改写历史记录日期，只改变未来日期边界和展示解释。

## 17. 全站页面解耦规则

设置页的任务拆分规则扩展到全站：

- Today 只展示当日概况和记录列表；饮食、训练、智能输入进入独立录入流程。
- Logbook 负责日期浏览；记录详情和编辑使用日期子路由。
- Review 展示周趋势；周报详情与 AI 解读分别加载。
- Plan 展示当前计划；生成、查看和调整使用独立任务路由。
- Profile 展示档案摘要；编辑档案使用独立任务路由。
- Coach 使用上下文抽屉，不与主页面业务表单共享状态。

建议路由：

```text
/today
/today/meal/new
/today/workout/new
/today/smart-entry
/logbook/:date
/review/week/:week
/plan/:plan_id
/plan/new
/profile/edit
```

该规则不要求本次设置实现同时重写所有页面，但后续页面改造必须遵守同一边界。

## 18. 实施任务拆分

本规范是跨模块总设计，不允许作为一个大任务一次实现。后续计划必须拆成五个可独立验收的阶段：

1. **架构基础：** 提取 Repository 和 ModelGateway 接口，建立稳定错误码与 `processing_mode`，保持现有用户行为可用。
2. **模型设置闭环：** 完成每用户加密模型连接、两个协议 Adapter、模型设置子路由，并让 Agent 使用当前用户连接。
3. **通用偏好闭环：** 完成全站 i18n、说明型单位单选、单位转换和账号时区日期边界。
4. **账号与数据闭环：** 完成密码修改、会话撤销、数据导出和账号删除独立路由。
5. **全站任务解耦：** 按第 17 节规则逐页拆分 Today、Logbook、Review、Plan 和 Profile。

每个阶段必须有自己的实现计划、测试和验收记录。前一阶段通过后再开始下一阶段，不能把五个阶段合并为一次提交。

## 19. 迁移顺序

1. 从现有 `tools` 中提取确定性领域服务。
2. 为文件持久化建立 Repository 接口。
3. 建立用户偏好、加密模型连接和会话版本。
4. 建立 Responses 和 Chat Completions Adapter。
5. 将 Agent 改成只通过工具接口读取数据。
6. 删除 `graph.py` 的静默模型降级和模型回答覆盖逻辑。
7. 增加设置中心和独立子路由。
8. 全站接入 i18n、单位和时区。
9. 接入账号安全、导出和删除。
10. 按独立任务路由逐步拆分其他页面。

旧用户数据不改变格式。缺失偏好时在首次初始化创建 `preferences.json`。旧环境变量中的 OpenAI Key 不自动复制给用户，也不用于已登录用户的 Agent 请求。

## 20. 测试策略

测试按边界拆分：

```text
tests/
├── domain/          公式、统计、校验、单位和时区
├── application/     用例、确认和权限边界
├── infrastructure/  文件、加密、原子写入
├── model_gateway/   两种协议的模拟响应
├── agent/           工具选择、结构化输出和失败行为
├── api/             鉴权、用户隔离和错误码
└── frontend/        路由、设置交互、i18n 和响应式布局
```

重点验证：

- 没有模型配置时，确定性功能完整可用。
- 确定性测试不发起网络请求。
- 文件、API、日志、Trace 和导出中没有 API Key。
- 用户不能访问其他用户设置和数据。
- 修改密码后旧 Token 失效。
- 保存、测试和获取模型列表互不触发。
- 未测试模型可以启用，但不能标记为可用。
- 两种协议产生统一内部结果。
- Agent 失败不返回伪 AI 模板答案。
- 智能记录未经确认不能写入。
- 语言、单位和时区跨设备持久化。
- 设置子路由的表单和请求状态相互隔离。

## 21. 验收标准

- 设置中心和六个设置子路由可用。
- 设置中心右侧只有统一进入箭头。
- 单位使用带示例的单选列表。
- 中文和英文覆盖全部产品页面与固定消息。
- 公制和英制输入展示正确，后端标准值不改变。
- 今日和周报按用户时区计算。
- 每用户模型连接独立并加密。
- Agent 与固定程序在代码、API、响应标识和测试中解耦。
- 模型调用只由用户触发的 Agent 操作、测试或模型列表操作发起。
- Docker 和本地开发文档包含 `SETTINGS_ENCRYPTION_KEY`。
- 密码修改、退出其他设备、导出和删除账号具备完整流程。
- 原有档案、饮食、训练、日历和看板数据保持可用。
