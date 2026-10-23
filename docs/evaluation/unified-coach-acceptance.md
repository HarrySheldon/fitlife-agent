# 统一教练 U0–U6 实施与验收记录

日期：2026-10-22。开发分支 `codex/unified-coach-agent`；基准 `a042ed9`，本地未提交工作区。

状态：**U0–U6 本地实施与离线自动化验收完成**。最终单次后端回归2299通过/1跳过，配置6通过，隔离Mock回放28/28；未提交、未集成、未启用新模式。以文末最终记录为准，保留中间失败与修复历史，不把离线通过等同真实模型或临床验收。

设计：[统一教练详细方案](../superpowers/specs/2026-10-22-unified-coach-agent-design.md)。计划：[U0–U6](../superpowers/plans/2026-10-22-unified-coach-agent.md)。基线：[U0](unified-coach-baseline.md)。

## 已实现内容

| 阶段 | 实现与证据 |
| --- | --- |
| U0 | 原始练胸表达行为 RED，修复后业务范围/安全契约 41 项通过；独立合成原版本全量基线 2238 passed |
| U1 | 严格 call/ask/final，复用结构化 JSON；真实 Responses/Chat Completions Adapter fake-client 验证；连接不重新要求原生 function calling |
| U2 | 三个发布 Skill、摘要→正文→参考资料、版本摘要/终态变化检查；任意路径拒绝、超限不截断、扩展资源测试 |
| U3 | 固定五类只读/计算工具，绑定身份，复用 AuthorizedTaskReads，字段/日期/数量限制；撤销和实际读取/模型转发前复验 |
| U4 | 单一 Runtime 预算、最多12次决策、连续两次协议/动作失败停止；数字事实与建议分离；审核与发布检查，完整建议内部契约 |
| U5 | 新模式默认 legacy；HTTP `/chat`、`/coach/action` 及会话回放；正式业务表/计划和草稿文件前后比较；S3 不提前激活 |
| U6 | 现有评估器扩展；28种 scripted mock、网络阻断、独立身份/数据库；事件记录工具拒绝、目录缓存、决策/协议和资源版本 |

本次不开放 Shell/脚本/任意文件/SQL/HTTP/删除工具，不建设执行沙箱，不复制新的计划激活状态机。模型产生数值建议时必须通过固定校验工具；建议中的动作名限定发布词汇，不能借动作名夹带任意数字事实。

## 审查发现与修复

经用户允许，两名只读审查者分别审查安全与计划覆盖，均未修改代码、读取真实数据或调用模型。修复并补测：

- ask 和英文数量不能绕过数字事实检查。
- 空记录查询保留字段，使空饮食/训练分析可以返回零值；字段不足仍受控失败。
- 明确否定的领域不因出现关键词而授予；范围解析限 zh/en 规则，不承诺任意自然语言授权理解完美。
- 读取、实际模型回调、语义审核回调及交付重新检查身份/授权；初始范围撤销后不继续利用旧上下文。
- Skill 版本变化成为终态，每次决策与交付复验，不再允许一次成功工具清零版本错误。
- 完整训练建议采用独立内部契约，与会话发布长度检查一致；输出额度根据契约及剩余预算设置。
- 业务快照扩展到所有非 Coach SQLite 表、plans 与 plan-drafts；不以常量 `formal_write_count=0` 充当证据。
- release 和失败路径进度进入受控报告。账户删除场景改为运行中删除，而非完成后再删除。

## 当前验证记录

- 修复后的阶段性定向组：**81 passed / 1 skipped**；之后审核不可用分支另测 **9 passed**。最终覆盖组结果在文末追加，不把不同批次相加为总覆盖数。
- 独立配置组：**6 passed**。
- 前端：**46 文件、299 测试通过**；生产构建通过。前端源码未修改，与主 checkout 同 HEAD；复用主 checkout 已安装依赖执行，日志在主 checkout `.tmp/unified-frontend-{test,build}.log`。
- 首次回放 **24/24** 是早期检查点。扩展28场景后 **27/28**，失败项真实发现 enforce 依赖不可用时低风险原稿仍可发布；现已修为新 unified 模式下必要审核失败返回代码生成的受控提示，原稿不发布，正在重跑。legacy 的既有审核失败策略没有被偷偷更改。
- Windows symlink 测试因当前账户无创建权限跳过，不称为 junction/symlink 实机安全验证通过；资源 ID、规范路径检查及变更检测另有实际测试。
- `compileall` 与 `git diff --check` 已通过；文末最终记录会再次检查。

## 28场景与补充证据

正常：原练胸、口语、具体追问、英文、显式语言、建议型训练安排、短答、多轮。

权限：owner/user参数注入、未许可饮食、字段越权、路径逃逸、未知执行工具、伪造确认、恶意检索资料。

错误/生命周期：错误决策协议、重复call ID、决策上限、超长输出、取消后再发、删聊天、运行中删账户、90天访问过滤。

新增：缺身份401且零模型调用、可信授权回调运行中撤销、目录重复读取命中、必要语义审核不可用且合成原稿泄露计数为零。

补充单测覆盖模型/工具预算预留、被撤销后的缓存/无证据回答、Skill变更中止、真实provider Adapter假客户端、业务深比较。28个场景不是28种攻击，不把正常案例混进攻击防御分母。

## 可重放命令

在开发 checkout 根目录，使用主 checkout 已验证解释器和独立合成 DATA_DIR：

```powershell
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
$env:DATA_DIR = Join-Path (Get-Location).Path '.tmp\full-seed'
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
& $taskPython -m pytest backend/tests/unified_coach backend/tests/task_evaluation/test_unified_coach.py -q --basetemp=.tmp/pytest-unified-manual
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/unified_coach.json --output .tmp/task-evaluation/unified-coach-manual --max-tokens 1000000 --max-seconds 600
```

完整后端回归另用 `.tmp/pytest-full-u`、`.tmp/unified-full.{log,xml}`；配置独立进程移除覆盖变量后运行。所有目录为开发临时目录，不能换成主 data 目录。不要在原 basetemp 尚被运行中测试使用时重跑同目录。

## 启用方式与未覆盖边界

配置 `COACH_AGENT_MODE=unified`；Docker Compose 已透传该变量，默认仍为 legacy。会话 UI 仍由原 C 阶段的前后端会话开关控制。没有调用真实模型验证本地配置，没有改变设置页保存门槛。

模式切换属于部署操作：先停止新任务并通过现有取消流程排空活动执行，再切换/重启，不在一次失败请求中自动改 legacy 重跑。检测到当前模式改变时新模式执行拒绝继续访问；没有新建热更新管理界面。

- 所有结果是合成 scripted mock，不证明真实模型理解、提示注入稳健性或临床正确性。
- 领域撤销回放通过可信 authorize 回调注入，证明执行约束，不代表新的生产许可管理 UI 或持久授权流程已经实现。
- 慢调用配合删除覆盖并发清理，但没有启动屏障穷尽每个竞态窗口。
- 工具计数来自持久事件；取消/超时打断 handler 时可能没有最终完成事件，不能把它宣称为所有失败路径的精确物理执行总量。
- `context_chars` 是应用上下文峰值，未计供应商包装差异；`cache_hits` 是工具目录复用，不是 KV cache 命中。Mock tokens 是字符估算，不是真实使用量、价格或性能提升。
- S3 正式候选、跨领域许可、共享修订与原子激活，以及 S4/S5 真实性能/模型评估仍属于后续阶段。
- 改动未提交、未推送、未合并或部署；主库保留，开发副本不清理。

## 最终收尾记录

- 完整回归首次结果：**2294 passed、2 failed、1 skipped**（1131.68 秒）。两处失败均为旧范围规则中“我的”重复修饰＋“政治训练”的词义误放行；已收窄显式非健身词义排除，没有删除或修改失败测试。
- 修复后扩展定向回归：**82 passed、1 skipped**（65.12 秒），包含两个原失败用例、统一教练和评估器测试；日志 `.tmp/unified-final-targeted.xml`。最终完整回归仍待下条记录。
- 最终新模式回放：**28/28 达到场景预期**、退出码0；原始记录 `.tmp/task-evaluation/unified-coach-source/report.{json,md}`，见[逐样本指标](unified-coach-mock-results.md)。该次执行在最后的 legacy 词义修复前，新模式路由不受该规则影响；不声称它在另一个源码快照上重跑过。
- 两名只读审查者对定向修复完成复核，未发现新的必修问题；审查不替代完整测试或真实模型验证。
- 第二次全量：**2298 passed、1 failed、1 skipped**（1118.42秒）。唯一失败为原有取消占槽测试；单独执行复现 200≠409。根因是默认模型桩收到 abort 后10ms内可退出，下一次HTTP请求时槽已合法释放，原测试没有保证其“transport尚未关闭”前提。
- 仅修订该测试，用Event屏障明确保持worker仍在退出路径中，随后断言占槽409；释放屏障后仍验证 cancelled。生产取消逻辑不改。修订后整份会话API测试 **14 passed**（64.92秒），该用例另起进程连续 **5轮通过**；只读审查确认保留原契约。第三次全量正在最终快照上运行，日志 `.tmp/unified-full-release.{log,xml}`。
- 最终后端源码见[SHA256 清单](unified-coach-source-manifest.json)：46个改动/新增文件，清单摘要 `9df9340c439dc4bcc5847965e6f578d9dd960a41fbf6c4baf6b622834e83cd36`。哈希定义写于清单；不包含密钥、数据库、测试产物或文档自身。

### 最终门禁结果

- 最终完整后端：**2299 passed、1 skipped、1 warning，984.42秒，退出码0**。命令为前述完整回归范围（`backend/tests --ignore=backend/tests/test_config.py`），最终基准目录 `.tmp/pytest-full-release`；日志及JUnit `.tmp/unified-full-release.{log,xml}`。运行覆盖最终46文件后端快照，没有把不同批次相加为此通过数。
- 独立配置最终复验：**6 passed，1.49秒，退出码0**；清除DATA_DIR、SQLITE_DATABASE_PATH、LLM_ENABLED覆盖后在独立进程运行，JUnit `.tmp/unified-config-release.xml`。
- 隔离Mock：**28/28**；前端：**46文件/299测试通过，生产构建通过**。各自证据及范围见上文。Mock不证明真实供应商性能，未调用真实密钥。
- 唯一skip为当前Windows账户不能创建symlink；唯一warning为现有Starlette/httpx弃用提示，不将它们隐去。
- U0–U6本地代码与离线验收收口；README提供显式启用指引。保留分支、开发数据和主库备份；等待用户决定提交/集成。后续S3/S4/S5与真实模型试用没有在本轮擅自推进。
