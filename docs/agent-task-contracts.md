# S1：任务与模型输入边界

状态：2026-10-15 S1 实现与离线验收完成，已提交为 `eff4527`，尚未推送。最终后端 1719 项、前端 229 项测试通过，生产构建及六类离线基线通过；提交前相关套件复验 129 项通过。逐项证据见 `docs/superpowers/plans/2026-10-10-agent-task-s1-contracts.md`。

## 任务不是一次模型请求

`TaskRef` 关联业务任务及版本，`AgentCommand` 可携带它；Runtime 将关联写入运行记录。普通聊天仍可没有任务关联。运行库兼容增加可空字段，旧运行及检查点可读；任务关联在同一次 run 中不可改变。

`RepairRound` 表示整次任务的一轮修订：训练和饮食同时修只计一轮，最多两轮，首次候选不计修订。同一轮恢复保留已完成领域，不重复加一。`TaskBudget` 表达已消耗、预留和上限。

这些是纯值和转换契约，不是事务实现。跨请求原子预留、防重、持久化恢复及业务确认事务由 S2/S3 的领域仓储实现，不能把一个 Python 计数函数当作并发保护。

## 范围、风险和权限分别控制

- 明确无关请求在档案、页面上下文和 Provider 加载前返回固定受守卫回复；寒暄和产品帮助不强制读取档案。
- Coach 原始问题与服务端页面意图分开。有原始问题时，自动生成的健康模板不能为它授予准入。
- 范围策略采用受限请求形态与保守澄清；未知请求规划后仍不可因模型声称健康意图而读取私有上下文。明确声明独立且各子句可判定的混合请求只保留原文健康子句，关联或不确定目标澄清。
- 原始输入风险检查先执行。业务范围通过不能覆盖健康风险处置，也不能跳过输出审核。
- `AuthorizedTaskReads` 将查询绑定认证 owner 和可信领域许可快照；模型返回的身份或领域字符串不是许可来源。新交互任务的许可持久化属于 S2/S3。这是应用层接口约束，不等于数据库只读角色或操作系统级权限隔离。

范围规则不是通用语义分类器，也不代表真实模型越界率已经测量。正则采用有界分句和无歧义修饰语匹配，性能回归使用隔离子进程超时保护。

## 模型实际看见什么

六个阶段 DTO（录入、训练、饮食、协调、审核、聊天）通过显式参数 Builder 构建。旧的整计划调整另有兼容投影，只提供必要训练/饮食片段和调整要求；它不是 S3 的双领域协调或授权实现。

输入先做字段投影，再清理身份文本、扫描字符串中的指令操纵内容。嵌套字段也有白名单，不将整个 state、完整档案或原始历史默认发送。必要过敏/动作限制、数值摘要、校验失败原因和字段 patch 有保留正例。文本去标识为有限规则，不承诺识别全部隐式身份信息。

若必需任务指令、安全限制或审核草稿因清理失去含义，返回受控 422 澄清错误，不能把清理标记当成有效指令继续生成。可选目录/RAG 内容可以清理后保留其他证据。审核模型不接收额外完整档案；未经检查的原文不能因已清理副本审核通过而发布。

Provider 调用发送经过投影及清理的载荷；测试检查真实 Chat Completions/Responses 适配器请求，而不只检查中间字典。Writer 每次调用保留本次回答必需的初始事实，不能假设无状态 Provider 记得上一次输入。缓存载荷校验 owner，跨用户或退出登录后不得直接复用。

## 生命周期与诊断

`BusinessDraft`、访问及导出函数是纯契约：不存在、他人或已删除的资源不泄露归属；旧版本冲突；到期访问立即拒绝，不等待物理清理。时钟显式注入，不在 S1 设置新的保留期限。

业务草稿可含敏感输入、待答问题和候选；诊断契约只留有界类别、版本、计数、时间和任务/run 标识，不承载原始健康正文或隐藏推理。标识由可信代码生成，语法校验不能证明标识来源。

账户 API 对新任务状态的真实删除、导出和恢复集成留到 S2/S3；本阶段的纯契约测试不构成存储闭环证据。

## 本地验证

在 PowerShell 中使用项目解释器；每次选新的临时测试目录，避免历史受限目录影响结果：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
$s1TestTemp = '.tmp/s1-' + [guid]::NewGuid().ToString('N')
& $taskPython -m pytest backend/tests -q --basetemp $s1TestTemp -p no:cacheprovider
npm --prefix frontend test
npm --prefix frontend run build
```

测试不需要真实 Provider。Mock 及契约通过只证明这些受测边界，不提供真实模型质量、安全效果或性能提升百分比。

## Entry task lifecycle and recovery

`EntryTaskExportPort` is a read-only, owner-scoped bounded snapshot seam. The account API injects the configured SQLite adapter; application export code never discovers a database. `entry-drafts.json` contains business draft bodies (including expired bodies still present), item progress and typed field sources, aggregate spent/reserved task budget counters, and minimal item commit facts. Provider diagnostics, arbitrary provenance metadata, connection credentials, command replay bodies and idempotency request snapshots are excluded. The new source consumes the existing 5 MiB source and 20 MiB aggregate/entry/archive budgets. Construction without this port preserves the previous archive contract.

`ExpireAgentTasks(repository, clock=..., mutation_scope=...)` requires an explicit owner and an aware cutoff no later than the server clock. `execute(user_id, cutoff=cutoff)` previews IDs/count only; `dry_run=False` applies within the caller's lifecycle mutation scope and one repository transaction. The SQLite adapter compares parsed UTC instants and removes only expired smart-entry draft bodies; command bodies cascade, while formal records, item maps, minimal confirmation receipts and task budget counters survive. Access expiry remains independent of physical cleanup. No production cleanup command is provided or executed. Operators must explicitly inject the configured repository and lifecycle scope when integrating maintenance.

Recreating the repository/service against the same database restores the persisted task version, question rounds, item progress and commit mappings without provider calls on resume. Interactive entry defaults off (`INTERACTIVE_ENTRY_ENABLED=false`), with `ENTRY_TASK_TTL_DAYS=30`; Compose forwards explicit overrides for both settings.

## M：模型连接与任务执行解耦（2026-10-18）

每用户模型配置以 schema 2 JSON envelope 保存 `revision/active/draft`，不是新增业务数据库表。Runtime 和 S2 可用性只读取 active；保存停用草稿不切换运行模型。旧 JSON 无副作用映射为 revision 0，历史已启用连接不被自动停用，但旧工具测试不被伪造成基础生成已通过。

设置页预览使用当前表单和明确的 `new/reuse_active/reuse_draft` 凭据选择。跨 provider_id／地址复用已保存密钥须前后端明确确认。探测最多两次生成、整体 30 秒、单次最多 128 输出 token，失败不自动重试；列表请求 15 秒，最多展示 200 项，可手填。预览共享独立的进程内每用户每分钟 6 次／并发 1 限制，不占用或伪造业务任务预算。

设置探测的 DNS／SDK／网络读取在短生命周期 spawn 子进程中执行，父进程截止后终止进程并有界清理，避免连续慢流绕过读超时。IPC 只携带解析后的必要连接字段和所选凭据，响应是限长 JSON 和脱敏错误；子进程不读取业务数据，禁 SDK 日志及标准输出。该隔离不用于业务 Agent，不提供持久恢复。取消浏览器等待不是上游费用撤销保证。

基础生成和最小业务解析均通过后，后端签发 15 分钟 HMAC 凭证，签名覆盖配置 canonical 摘要、用户、revision、实际凭据的 keyed fingerprint 与探测版本。版本为 `generation-structured-v2`，旧 `generation-tool-v1` 凭证拒绝。部署密钥经不同 HKDF info 分别派生签名／指纹密钥。凭证不含密钥原文、密文、健康信息或完整配置。修改、过期、清密钥、另一个标签页更新、换用户均不能复用；后端 CAS 验证后才更新 active，旧 PUT 同样不能绕过。新 active 记录 generation_status/structured_status=passed，不把未检测的 tool_status 伪造成 passed；tool_status 仅保留旧记录历史。没有读取时迁移或自动停用旧 active。

设置页只提供一个「测试连接」动作和整体结果；分阶段耗时／脱敏错误码放在默认折叠的详情。内部第二次请求提取固定合成输入 `oats 40 g`，本地严格校验字段、类型及值。失败不签发凭证，生成失败不继续解析。没有原生工具调用请求，不发送业务档案、记录、自由提示词或运行历史；通过不代表完整业务质量、安全充分或医疗正确性。

自定义兼容端点的探测与 Planner／parse_structured 共用普通 JSON 文本生成和本地 Pydantic 校验，不要求供应商支持原生 strict JSON Schema，不做猜测修复、额外请求或协议自动回退；官方真实端点保持既有原生解析。DeepSeek 精确 hostname 的 Chat Completions 探测使用 max_tokens。正式业务继续遵循每个模型的类型及业务校验规则、安全审核和 Runtime 配置快照／预算；这不是放宽数据写入门槛。测试 schema 的严格类型规则不代表所有历史业务模型都改成 strict=True。

账户导出继续使用受限快照和字段白名单；有草稿时另输出 `model-connection-draft.json`，不导出密钥 hint、密文、验证凭证或指纹。删除账户清除用户配置目录并撤销认证，迟到激活不能重建目录。本阶段没有运行真实 Provider 验收，也没有修改保留的正式数据。

## C4：教练离线回放接线（2026-10-20）

评估器的 `Step.wait_for_turn` 仅允许GET教练Turn状态，最多100次追加读取，不重发生成POST；未知状态和未结束均不能作为完成。批次父进程仍有整体期限及预算。失败路径也计入实际处理耗时。场景按owner认证，数据库计数来自独立临时业务库，报告只新增允许的非负整数，不承载聊天正文或原始receipt。

当前 manifest 有 16 个场景：中英文确定性边界、幂等/跨 owner 拒绝、缺失保存计划拒绝生成、中文快捷解释、账户语言与显式语言覆盖、超长输出拒绝、同聊天多轮、跨聊天隔离、跨标签页单槽冲突、停止清理、90 天读取窗口、聊天删除、账户删除、来源可见。模型解释类场景会产生 2 或 4 次 Mock 调用；边界与拒绝类场景仍要求零调用。故障注入（慢回答、超长回答、消息回拨）只在评估 worker 内生效，不改部署默认值。

`business_task_ref={kind, task_id}` 已作为只读展示字段投影到消息元数据：仅保留受长度与字符集约束的 kind/task_id，候选、预算与权限不进入聊天；当前没有 S3 生产者，因此不构成聊天内的第二确认入口。范围及未覆盖项见[教练验收记录](evaluation/coach-conversation-acceptance.md)。
