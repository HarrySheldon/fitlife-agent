# 真实评估入口与引用交付接线

基线 `main/0df22e2`；实现分支 `codex/live-evidence-integration`，工作树 `D:\code\vibe-coding\fitlife-agent\.worktrees\live-evidence-integration`。本记录仅覆盖两项已授权接入；未提交、合并、推送、迁移、部署或调用真实模型。

## 数据隔离

创建工作树前使用主解释器及配置备份主库至 `.local-backups/before-live-evidence-20261104-224252.sqlite3`，integrity=ok；SHA256 `dbbdc129158d7bbaadeb335fddcd4f414bbb5a66bed4037df8e6a940f355ebce`。隔离副本 `.dev-data/fitlife.sqlite3` 经SQLite backup API初始化并校验ok，与主库路径不同；未启动该副本上的应用。测试使用工作树 `.tmp` 内的合成数据，未读取账户加密配置或保留正式run历史。

## 已实现

1. CLI增加显式连接、manifest、独立授权、prepare/dry-run/执行路径。实际代码/suite/连接/策略/预算重新计算，与manifest逐项绑定；每次Provider构造重新检查授权期限。
2. Gateway RPC封闭schema与操作，绑定request_id、通道和case，限制大小并拒绝重放。父进程独占凭据/网络与批次预算，子进程保留网络拒绝及合成数据隔离。
3. 输出上限、固定指令/schema输入预留、重试物理计费、unknown用量保守保留；配对两策略交替运行且共用总预算。
4. Runtime取消经IPC触达父进程传输；等待取消完成再清理worker。中断保留当前case及未知费用，逐case保存partial报告。
5. 每个run内知识证据编号唯一，并冻结call_id、chunk、release、hash和展示文本的绑定。最终回答前与审核后均校验；未知编号、无证据却声称来源支持、误用call引用均不直接发布。
6. 引用错误允许同run一次纠正，消耗原模型调用/时间/token预算；第二次失败返回脱敏的 `KNOWLEDGE_CITATION_INVALID`。权限撤销、快照变更不降格为可修正引用错误。
7. 稳定系统指令明确区分工具call_id与正文E编号；数值检查仅豁免已验证引用编号，其余数值约束继续生效。

操作步骤见[受控评估入口](../task-evaluation-live.md)。引用合法性不能证明主张忠实性或医学正确性；本次没有新增真实语义质量或性能结论。U7和正式迁移仍待后续阶段。

## 验证记录

- pytest 9.1.1，主checkout现有解释器；先确认隔离路径再执行测试。
- 初始基线因pytest临时目录父目录未创建产生63个setup error，修正目录后定向基线63 passed；未把setup失败写成产品缺陷。
- 首批引用回归6 passed；首批live端到端4 passed；扩大边界后19 passed，含首次审查三项修补。
- 中间相关回归519 passed、1 skipped，273.15秒；这是后续Planner上限修补前的记录。
- 扩大回归首次602 passed、1 skipped、3 failed，366.98秒。3项均为handoff准备阶段重复档案主键：本次命令固定了SQLITE_DATABASE_PATH，使仅覆盖DATA_DIR的fixture共用合成库。修正命令为移除SQLITE_DATABASE_PATH、由各fixture独立解析数据库，再重跑；未改产品代码规避失败。
- 最终定向复验48 passed，74.46秒，覆盖CLI、引用交付及Planner输出额度；之后加入catalog摘要绑定，再复验live全部12项，12 passed，68.75秒。
- 移除固定SQLite环境变量后的最终相关回归 **605 passed、1 skipped、1 warning，448.57秒，exit 0**。范围为统一教练、RAG、评估器、计划任务与教练会话API；未声称执行全项目/前端回归。既有Starlette TestClient弃用提示保留。
- 文档本地链接、CLI帮助及 `git diff --check` 通过。最终backend源码摘要：`4de147199c41c8e65b8497534da6e6e61a51fef7134ec6a3a09a4ae088b3337e`。

最终相关回归命令（在本工作树，先建立 `.tmp` 父目录；复跑需换basetemp后缀）：

```powershell
$env:DATA_DIR = Join-Path (Get-Location).Path ('.tmp/final-default-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
Remove-Item -LiteralPath 'Env:SQLITE_DATABASE_PATH' -ErrorAction SilentlyContinue
$env:LLM_ENABLED = 'false'
& 'D:/code/vibe-coding/fitlife-agent/.venv/Scripts/python.exe' -m pytest backend/tests/unified_coach backend/tests/rag backend/tests/task_evaluation backend/tests/test_plan_adjustment_api.py backend/tests/test_plan_adjustment_service.py backend/tests/test_plan_adjustment_coach_handoff.py backend/tests/test_plan_adjustment_session.py backend/tests/test_plan_closeout_regressions.py backend/tests/test_coach_conversation_api.py -q --basetemp=.tmp/integration-final-isolated --tb=short --maxfail=5
```

只读独立审查发现并关闭：旧writer接口缺失、错误call引用无纠正机会、中断丢当前case，以及native Planner输出额度未应用。审查者未运行测试，不替代运行证据。
