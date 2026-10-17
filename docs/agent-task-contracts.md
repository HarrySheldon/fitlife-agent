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
