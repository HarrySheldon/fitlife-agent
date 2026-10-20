# 通用模型连接与显式验证设计

> **2026-10-18 修订说明：** 用户在真实接入后确认取消原生工具调用准入，改为单一「测试连接」交互，内部验证生成＋最小业务 JSON 解析。当前规则以 [连接测试业务化方案](../plans/2026-10-18-connection-business-check.md) 和 `docs/agent-task-contracts.md` 为准。下文是首版设计存档，其中 generation/tool 双通过、页面分能力展示及 generation-tool-v1 已被取代；active/draft、CAS、隐私、期限和限流规则仍有效。新凭证为 generation-structured-v2，tool_status 不再被新启用路径标为通过，新增 structured_status。自定义服务探测与实际结构化业务共用 JSON＋本地校验，不要求原生严格格式能力；官方端点原生解析保持。

日期：2026-10-17。核对代码：`aa63c77`。状态：用户已确认五步流程、基础生成与工具调用双通过门槛、先于 S3 实施，并授权落地；2026-10-18 在 codex/model-connection-workflow 本地实现、离线完整回归及独立复审完成，未提交、未合并、未部署，未进行真实 Provider 验收。

## 目标与范围

用户路径：选择服务商 → 填地址和密钥 → 获取／手填模型 → 显式测试 → 保存并启用。

本阶段命名为 M（Model Connection），插入 S2 与 S3 之间，不改变原 S0–S5 编号。只管理每用户一份生效配置及一份停用草稿，不建设多连接管理中心、路由、负载均衡、自动故障切换，也不重写 Planner/Writer。

当前代码已有 `ConfigurableModelGateway`、两个协议 Adapter、加密配置仓储及端点检查。当前问题是预览操作只读已保存配置、只有工具探测、启用无双测试门槛、服务商 Literal 固定为 openai/custom。设计复用这些能力，不另起模型执行框架。

## 模块与扩展方式

- 服务商预设：稳定 ID、显示名称、默认地址、支持的协议及建议协议。后端是唯一事实源，前端动态获取。初始只迁移已有官方预设并提供“自定义兼容服务”；不硬编码未经核实的外部地址，不默认选中任何服务商。
- 连接：provider_id、明确的 base_url、protocol、model、加密凭据、验证信息。OpenAI 也使用显式解析出的地址，不再在工厂中分叉为“官方地址为空”。旧记录通过兼容读取映射，不在读取时写文件。
- 协议注册表：`responses` 与 `chat_completions` 对应现有 Adapter。新增兼容服务商不改调用代码；新增原生协议才增加 Adapter 和契约测试。预设不能注入 SDK 类路径、任意请求头、脚本或可执行模板。
- 模型探测 Interface：`list_models()`、`probe_generation()`、`probe_tool_call()`。模型业务 Interface 继续保留 `plan_route/write_answer/parse_structured`，本阶段不强制所有业务迁到新的通用 generate Interface。
- Runtime 继续拥有业务调用的超时、预算和重试。设置预览使用独立有界探测，不引入业务任务及健康数据；SDK 重试为零，不自动换协议／模型／服务商。

扩展验收：增加一个合成服务商预设后，不改前端组件和业务工作流即可完成配置；未知 protocol 必须拒绝，不回落到 responses。模型 ID 不需登记到枚举即可使用。

## 存储与状态

同一 `users/<user_id>/model_connection.json` 使用 schema 2 envelope：`schema_version/revision/active/draft`。active/draft 均为单个连接或 null；draft 永远停用。任何读取 Runtime 只取 active。

- 浏览器编辑态不持久化。获取模型、测试均不改 active/draft。
- “保存为停用草稿”只写 draft，不停用／替换 active；页面明确显示旧连接继续生效。
- “保存并启用”原子替换 active 并清空 draft，revision + 1；新请求取新配置，已有 run 使用原快照。
- “停用当前连接”是单独操作，不需要新探测；不删除凭据或草稿。
- 修改关键字段立即失效的是编辑态测试凭证，不追溯修改已有运行快照。
- 所有保存、启用、停用、清密钥采用 expected_revision，比对和替换必须处于同一个仓储临界区。冲突返回 409，不能无声覆盖另一标签页。
- 当前 Docker 单 Uvicorn 进程。沿用生命周期锁并增加仓储原子 compare-and-set；不声称该文件仓储支持多进程 CAS 或跨进程账户删除。若改变为多 worker/多副本，必须先把连接状态迁到事务仓储或补跨进程锁与生命周期一致性测试。

旧 schema 1 记录只读映射为 active（保留原 enabled、密文及字段）；revision 视为 0。历史 success 仅证明旧工具探测，不伪造 generation=passed；既有启用连接继续可用，显示“历史配置，未完成双项验证”。再次显式启用或修改后启用必须新测试。首次写入转换为 schema 2；转换前异常不覆盖旧文件。

保留 `get/save/project_public` 兼容 Interface 以维持业务和旧测试的调用形状，但所有公网写入入口委派新的规则，不允许通过旧 PUT 绕过门槛。项目内旧保存用例迁为受约束委派而非保留第二条宽松实现。

## 凭据语义

请求使用互斥的 `credential_mode=new|reuse_active|reuse_draft`。new 必须提供非空 api_key；reuse 必须禁止同时传 api_key，并绑定 expected_revision。原文只存在于当前请求和短生命周期内存，不进入日志、浏览器持久化、探测响应或验证凭证。

同服务商、同规范化地址可按用户选择保留密钥。切换 provider_id 或 base_url 后，前端清除默认复用状态；后端也要求 `confirm_credential_reuse=true` 才能把已保存密钥发送到新目标。确认 UI 必须显示来源和目标地址。不能只在前端防护。

新预览接口与既有 Adapter 工厂共用端点策略：HTTPS、公网目的地址、禁用户信息/fragment/基址 query、禁自动重定向；预设不豁免策略。不放宽 localhost/内网限制，因此本阶段不支持本地 Ollama。现有 DNS 校验不等于连接 IP 钉扎；不宣称消除 DNS rebinding，这项传输加固不混入本计划。

用户公开读接口最多返回 configured/hint，不返回密文；预设接口不含密钥。清密钥按 active/draft 明确选择，清 active 时同步禁用 active，增加 revision，使旧凭证失效。

## 预览与测试

所有端点沿用 `/settings` 前缀和 require_current_user：

| 请求 | 行为 |
| --- | --- |
| GET `/model/providers` | 后端注册的预设和协议选择，不触发外网 |
| GET `/model/workspace` | revision、active/draft 的脱敏投影 |
| POST `/model/preview/models` | 使用当前表单及显式凭据选择获取模型，无文件写入 |
| POST `/model/preview/test` | 使用当前表单串行执行基础生成与工具探测，无配置写入 |
| PUT `/model/draft` | CAS 保存为停用草稿 |
| POST `/model/activate` | 校验后端测试凭证并 CAS 保存启用，原子清草稿 |
| POST `/model/disable` | CAS 停用 active，无外网调用 |
| DELETE `/model/api-key?slot=active|draft` | CAS 清指定凭据，无外网调用 |

旧 GET `/model` 保留 active 形状。旧 PUT `/model` 的 enabled=true 必须携带同样的有效凭证；enabled=false 委派停用草稿保存（响应仍为该停用记录的公开形状）。旧 `/model/models` 和 `/model/test` 无 body 时明确测试 active，测试结果不自动持久化；其返回形状暂兼容，内部同样遵循新限额，不能凭旧 success 绕过 activate。

基础探测使用固定合成提示“Reply with OK.”，收到非空文本即通过，不要求精确字面匹配。工具探测强制 `connection_probe`，严格解析 JSON 参数，验证 `ok` 为布尔 true，不执行任何业务工具。格式或能力不满足时记失败，不回落纯文本成功。

测试总体至多 2 次模型生成调用，整体 30 秒，单次 timeout 使用剩余时间，单次输出上限 128 token（分别映射 max_output_tokens/max_completion_tokens）。基础探测失败则工具项为 not_run；无自动重试，不发送档案、历史、自由用户提示词。模型不兼容此输出限制时明确失败，不偷偷去掉限制重试。模型列表最多 1 次请求、15 秒，结果最多 200 条、每 ID 200 字符，显示截断提示；不在页面初始化、保存或启动时自动请求。

设置探测使用复用的 ProcessRateLimiter 算法、独立 app 级实例：每用户每分钟 6 次预览请求、并发 1，两个预览端点共享桶；不每次请求新建 limiter。限流进程内有效，不宣称分布式配额。上游 usage 缺失记未知，不记零。测试可能计费，点击前展示费用提示。

实施复审补充：同步 SDK 的读超时不能阻止持续慢流，因此每次设置列表／生成／工具探测在短生命周期 spawn 子进程内执行。父进程按同一剩余期限等待，截止时 terminate，必要时 kill，关闭 IPC，并做有界清理（允许短暂清理开销，不宣称硬实时）。URL 结构规范化不查 DNS；DNS 校验、SDK 建连及读取均在子进程期限内，实际请求仍须通过公网端点策略。仅解析后的连接字段及所选凭据经私有 IPC 传入，结果为限长 JSON，不传业务状态／用户目录；子进程禁用 SDK 日志并丢弃标准输出／错误。此机制只用于设置探测，不是持久任务队列，不改变业务 Runtime。

分项结果有 passed/failed/not_run、latency_ms、脱敏 error_code；外部网络失败以统一错误返回，不能包含 URL query、Authorization、密钥或供应商原始响应正文。双通过才返回 verification_token；失败不返回凭证。未授权、无加密配置、无凭据、目标不安全等准入失败发生在外网调用之前。

## 后端测试凭证

新增 `ModelVerification` Interface：issue/verify；实现为有版本的 HMAC 签名 token，有效期 15 分钟。HMAC 密钥从部署加密密钥通过 HKDF-SHA256 派生，info=`fitlife:model-verification:v1`；凭据指纹用独立 info=`fitlife:model-credential-fingerprint:v1` 派生的 HMAC 密钥计算。不把密钥原文、明文哈希或密文放入 token，不持久化 token，不允许客户端自报 success。

凭证绑定 user_id、expected_revision、provider_id、规范化 base_url、protocol、model、实际凭据的 keyed fingerprint、probe_version、双项 passed 及签发时间。实现将 canonical 绑定计算为 SHA-256 摘要再签名，不在 token 内嵌完整配置，避免长地址／中文模型名超过长度上限。TTL 到期、被篡改、换用户、换模型／地址／协议／密钥、配置 revision 变化或 probe_version 变化均拒绝。保存重新计算绑定，不调用真实模型。部署密钥变化自然使 token 失效。

新密钥测试后仍在表单内，activate 再次通过 HTTPS 请求提交同一密钥，后端校验后加密持久化；不通过 token 携带密钥。CAS + revision 使同凭证重复激活不会重复更新，返回 409 后前端刷新工作区确认状态。不自动重发外网探测，不以刷新获取“免费通过”。

## 页面交互

单页五步表单，顶部展示 active 的服务商、地址、模型和状态；单独入口加载 draft。协议折叠到高级设置。获取列表失败可手填；列表不自动选择／切换模型。两个保存按钮文案不同：保存为停用草稿／保存并启用；另有明确的停用当前连接操作。

选择服务商或编辑关键字段后，立即清 token/双项结果；provider/base_url/credential 变化同时清模型候选列表；模型变化保留列表但清验证。每次预览绑定表单 generation ID，迟到结果不得把新表单标为成功；AbortController 取消前端等待不能宣称已经取消供应商计费。busy 状态禁止重复探测，但后端仍限流。

保存冲突保留本地编辑并提示重新加载，不静默覆盖。载入其他配置、离页时提示未保存修改；不保存密钥到 localStorage/sessionStorage/URL。显式加载 draft 不能因 active 刷新或测试结果更新被 useEffect 重置。基础与工具均通过才允许点击启用；后端仍再次验证凭证。

生产入口使用 DataRouter 的 blocker 处理链接、程序导航和历史后退，既有 AppRoutes 路由表保持不变；beforeunload 处理关闭／刷新。编辑失效和卸载会 AbortController 取消前端预览等待，但不代表供应商已经停止计费；后端独立执行截止时间与资源清理。

## 隐私、兼容与验证

账户导出包含 active/draft 的必要配置投影，但不含密文、密钥 hint、token、凭据指纹；账户删除清整个配置文件和用户限流桶，不新增外部秘密存储。导出大小限制和快照读取规则继续适用。

既有运行不会因新页面保存草稿改变配置；旧模型接口、S2 可用性判断及配置快照回归必须通过。不把两项探测通过宣传成医疗正确、安全充分、结构化输出全兼容或真实业务质量达标。

对应实施计划：`../plans/2026-10-17-model-connection-workflow.md`。全部自动化使用 Fake 客户端、合成密钥和隔离 DATA_DIR；本阶段不调用用户密钥、不执行 live 验收、不修改正式数据、不自动创建分支／工作树。
