# S5 真实模型验收与受控启用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 确认真实模型的业务效果、安全误拒与任务完成效率，并形成可审计交付证据。

**Architecture:** 沿用独立评估模块和合成业务数据，真实Provider运行有显式预算与授权；人工标注负责语义判断，确定性不变量仍由代码判分。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---


## 执行边界与前提

本计划可先完成离线准入检查、标注模板、报告和运行手册。付费Provider调用、正式数据导入与生产启用分别需要对应明确授权；授权前用Mock验证这些路径。
依赖S0–S4验收记录，明确Provider/model版本、安全模式、单任务/批次调用与token上限。当前默认safety_review_mode=off、grounding_mode=legacy，不能声称已经启用全套保护；实验配置必须显式记录，reference与optimized使用相同值。
采用先小样本探查费用/失败类型，再在已授权总预算内扩大样本。数量由baseline方差与预算决定，不预设足够样本的假象。

## 文件分工

新增 `backend/task_evaluation/acceptance.py`；
新增 `backend/tests/task_evaluation/test_acceptance.py`；
新增 `backend/task_evaluation/scenarios/safety_boundary.json`；
新增 `docs/evaluation/agent-live-acceptance.md`、
`docs/evaluation/agent-annotation-guide.md`、
`docs/evaluation/agent-release-runbook.md`。
修改 `backend/task_evaluation/contracts.py`、`runner.py`、`report.py`、`cli.py`。
新功能配置统一加在 `backend/config.py` 并由相关API服务读取；
配置测试新增 `backend/tests/test_agent_task_feature_flags.py`。设置值保持显式，不通过浏览器开关绕过服务器配置。

PowerShell初始化：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
```

### Task 1：离线准入、真实调用预算和人工标注

- [ ] test_acceptance.py写准入失败测试：缺model标识、配置两组不同、无正预算、含真实用户数据、任务隔离缺失时拒绝；任何Provider构造之前拒绝。
- [ ] RED：`& $taskPython -m pytest backend/tests/task_evaluation/test_acceptance.py -q`。
- [ ] acceptance.py定义AcceptanceManifest：code_sha、diff_digest、suite_digest、provider/model、strategy、review_mode、grounding_mode、max_calls/max_tokens/max_seconds、repeat、synthetic_only、annotation_protocol_version。不能仅以一个--allow-live跳过这些事实检查。
- [ ] CLI批次预算使用S0预留机制，所有worker共享批次账本，开始case前reserve，结束settle，未知usage不记0；批次上限包含重试、Reviewer和两域模块。Provider最大输出token与预留相容，达到上限停止启动新case并保存partial报告。
- [ ] safety_boundary.json覆盖：直接/间接注入、要求泄漏他人信息、健康风险越界、正常否定描述、业务无关、正常业务含“代码”、可分离/不可分离混合任务、跨域未许可、未知事实、数值单位/时间范围错误。案例全为合成，风险预期按既有产品能力边界，不临时添加未经审阅医疗规则。
- [ ] 标注指南逐条定义任务完成、必要追问、非必要变更、恰当拒绝、遗漏限制、范围误拒；盲化strategy，记录标注者/规则版本/分歧与复核。模型辅助标签单列，不作为权威正确答案。
- [ ] 离线通过后在授权上下文执行live。示例调用需要执行者用已批准预算替换变量，不能复制默认数额启动：

```powershell
$approvedCalls = [int](Read-Host '已批准的本批次总调用上限')
$approvedTokens = [int](Read-Host '已批准的本批次总token上限')
$approvedSeconds = [int](Read-Host '已批准的本批次总运行秒数上限')
& $taskPython -m backend.task_evaluation.cli --mode live --allow-live --strategy reference --max-calls $approvedCalls --max-tokens $approvedTokens --max-seconds $approvedSeconds --repeat 1 --suite backend/task_evaluation/scenarios/safety_boundary.json --output .tmp/task-evaluation/s5-probe
```

Read-Host只是提供数值，不等同聊天授权；凭据由已有连接配置读取，不在命令行或报告显示。扩大repeat仍受同一批准总预算，不自动在CLI退出后开启下一批。
- [ ] 用S4方法跑两策略配对，指标按业务/风险类型分组。report注明日期、样本分母、不确定性和Provider服务时延；未通过的case保留，不能删失败样本后计算准确率。
- [ ] 费用以实际usage和经过验证的价格来源计算；无price表则仅报告token，不猜费用。任何拟写简历的“提升X%”必须指向这份配对报告和对应配置。
- [ ] GREEN与离线回放后填入agent-live-acceptance.md模板：已完成验证/未运行live分别列出，未运行时不声明真实效果合格。

### Task 2：配置启用、生命周期演练和最终验收

- [ ] test_agent_task_feature_flags.py测试默认关闭新业务入口；关闭期间GET已有草稿仍可查看，禁止新的模型执行与激活；旧确定性录入/计划路径继续由其原规则处理。生产策略可另行启用，测试明确config。
- [ ] config.py统一新增建议设置名：interactive_entry_enabled、plan_adjustment_tasks_enabled、plan_storage_mode(file/sqlite)、task_execution_strategy(reference/optimized)、entry_task_ttl_days、plan_task_ttl_days、plan_candidate_ttl_minutes。TTL正整数，config读取后快照到任务，恢复不因默认值变化续命；安全限制只允许收紧。
- [ ] 这些配置实际应随S2/S3/S4实现，S5检查收口和文档；不能将默认关功能的必要配置推迟到发布当天。新业务关闭不能绕回旧接口执行同一新任务。
- [ ] 发布手册按顺序：备份/数据清点 → import dry-run → 用户授权正式迁移 → 核对历史与head → 只启用指定测试账户 → 验证录入/单域/联合完整闭环 → 用户授权扩大。配置灰度账户名单服务端验证，不由用户请求参数选择。
- [ ] 演练超时、Provider不可用、断线、确认响应丢失、旧计划冲突、账户删除、导出与到期清理；演练只使用合成环境。每项记录任务状态、正式写入数、重放结果。
- [ ] 同等安全对照不得靠off Reviewer得到性能亮点。若真实效果误拒/漏检超出基线审阅门槛，保留reference或暂停新入口；优化关闭不删除正式历史。
- [ ] 执行总入口完整回归，保存最终SHA/diff与运行证据；再更新设计覆盖表、运行手册、已知限制。明确不具备后台跨进程自动续跑，resume是持久状态恢复与显式新run。
- [ ] 最终项目介绍只写实际交付与实测指标。例如以下模板中的花括号取报告字段，不拿Mock数值填真实提升：

```text
针对整餐描述缺信息、计划调整约束冲突的问题，
设计统一Runtime下的有限澄清与双领域协调流程，
以版本化草稿、条目幂等提交、领域校验及权限控制完成确认闭环；
在{场景数}/{重复次数}/{模型版本}的配对评估中，
候选可确认P50由{baseline}降至{optimized}，
同时保持{字段准确率}/{硬约束满足率}和确定性安全不变量。
```

- [ ] 交付完成的判据是业务闭环+故障演练+真实效果证据（若获授权运行），不是文件数量或测试条数。未获live/上线授权时报告已完成离线交付和待执行步骤，保持状态准确。
