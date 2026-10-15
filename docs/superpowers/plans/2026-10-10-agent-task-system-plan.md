# Agent 任务系统总交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 按六阶段交付可恢复、受约束、可评估的业务 Agent。

**Architecture:** 沿用统一 Runtime，扩展领域任务状态；先测试基础，再安全契约，再业务纵向切片，最后做同等安全前提下的性能对照。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---


## 依据与当前范围

设计：`docs/superpowers/specs/2026-10-10-agent-task-system-design.md`。代码核对基线：`1029a27`。
计划编写时仅生成文档。S0 已完成并以 `e3027f6` 提交、推送到 `codex/agent-runtime-refactor`，未合并到 main。2026-10-15 用户授权并完成 S1：四个任务及最终集成审查通过；最终后端 1719 passed、计划指定套件 99 passed、前端 229 passed 且构建通过，六类离线基线 6/6 通过。S1 变更尚未提交或推送，未合并到 main；S2–S5 尚未启动。详细证据与边界见 S1 计划及 `docs/agent-task-contracts.md`。

用户已确认整任务共享两轮自动修订；生命周期期限和联合确认策略沿用设计建议值，在相关阶段实施前再确认，不把离线实施许可推断为生产迁移、真实模型调用或上线许可。S1 的生命周期验证仅为纯访问/导出契约；新任务存储、账户集成与原子确认属于 S2/S3。

## 六步及依赖

| 顺序 | 计划文件 | 可交付结果 |
| --- | --- | --- |
| 1 / S0 | [评估基线](2026-10-10-agent-task-s0-evaluation.md) | 离线隔离回放与可信基线，不把未实现功能算成功 |
| 2 / S1 | [共享契约与安全](2026-10-10-agent-task-s1-contracts.md) | 持久任务契约、字段最小化、权限与业务范围分离 |
| 3 / S2 | [交互录入](2026-10-10-agent-task-s2-entry.md) | 多项澄清、局部修改、部分确认及恢复完整闭环 |
| 4 / S3 | [统一计划调整](2026-10-10-agent-task-s3-plans.md) | 双领域协调、有限纠错、差异确认及原子激活 |
| 5 / S4 | [性能优化](2026-10-10-agent-task-s4-performance.md) | 局部复用、路径裁剪及配对实验报告 |
| 6 / S5 | [真实模型验收](2026-10-10-agent-task-s5-acceptance.md) | 获授权后开展真实效果验证及受控发布 |

串行主依赖 S0 → S1 → S2 → S3 → S4 → S5。S2/S3 的场景分别随业务补齐，S0 不伪造不存在的多轮 API。
共 23 个任务检查点：S0 4 个、S1 4 个、S2 5 个、S3 5 个、S4 3 个、S5 2 个。阶段不是单个大提交，每任务先写失败测试，再实现，再回归。

## 设计覆盖与验收位置

| 设计要求 | 落地任务 | 主要证据 |
| --- | --- | --- |
| 持久任务与单次run分离 | S1任务1；S2任务2；S3任务2 | run关联、等待释放线程、重启恢复 |
| 两轮录入澄清、估算来源 | S2任务1–2 | 问题组账本、来源字段、两轮后无自动追问 |
| 局部修改、部分保存、防重 | S2任务1、3–5 | 不相关条目不变、事务故障回滚、重放不新增 |
| 双领域许可与有限修订 | S3任务1–2、4–5 | 未授权域零调用、共享两轮、有效差异 |
| 目标保持、旧版本检测、历史保留 | S3任务1、3–5 | SQLite原子激活、head比较、旧计划不变 |
| 业务范围、风险与权限独立 | S1任务2–4；S2/S3公开入口 | 数据读取前拦截、混合任务判定、越权拒绝 |
| 输入最小化、输出安全/证据 | S1任务3–4；S2/S3工作流 | 实际Provider载荷、必要限制保留、守卫接线 |
| 生命周期与账户隐私 | S2任务3、5；S3任务3；S5任务2 | 到期拒绝、导出/删除覆盖、已提交记录不撤销 |
| 可确认耗时、有限调用、缓存失效 | S2预算；S4任务1–3 | 同等安全配对、失败成本、冷暖缓存分组 |
| 独立评估、Mock/live分组 | S0任务1–4；S5任务1 | 场景隔离、预算账本、人工标注与provenance |

文件计划中的方法名和字段均为拟新增契约；实现者先核对当前HEAD与工作区再执行。既有能力通过新增验收即可复用，避免为了匹配文档另建重复组件。

## 修订额度：必须对开发者和用户讲清楚

```text
初次候选：训练失败 + 饮食失败       repair_rounds = 0
第一轮：同时修复训练与饮食         repair_rounds = 1
第二轮：只修仍失败的饮食           repair_rounds = 2
仍失败：等待用户决策，不再自动修复
```

- 两个模块在同一协调轮被修复，只记一轮；不是两个模块各有两轮。
- 首次候选不计入修订；底层网络重试不新增业务修订轮，但照常消耗 Runtime 调用/token/时间预算。
- 每轮开始前持久化 round_id 和计数；相同 round_id 恢复不重复加一。部分成功记录该轮各模块结果，恢复只补未完成模块。
- 模块成功就冻结该候选；除非依赖发生变化，否则另一模块纠错不能重写它。
- 两轮不是“两次模型调用”，也不是“向用户问两次”。录入澄清另有独立上限。
- 同任务预算在刷新、重连和重试后都保留。等待用户的时间不占 run deadline；多次 run 的调用额度需从任务预算原子预留，不能刷新获得无限调用。
- 用户明确提出新目标/范围可创建关联新任务，系统不能偷偷另建任务绕过上限。范围同意发生在首次联合生成前；中途改变范围应展示并确认新任务。
- 单轮调用数按实际失败模块与审核调用计算，因此不能对外承诺“最多三次 LLM 调用”。

## 基线与完整回归

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
git status --short --untracked-files=no
git rev-parse HEAD
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
& $taskPython -m pytest backend/tests -q
npm --prefix frontend test
npm --prefix frontend run build
```

记录命令、环境、提交、工作区差异、耗时、失败类别；不能复用过去“1498 passed”当本次基线。环境故障和真实断言失败分开，修复仅限任务必要范围。
新测试不能访问真实账户和 Provider。前端构建内脚本含 shell 逻辑由 npm 处理，不在 PowerShell 手写 Bash 运算符。

## 阶段结束检查

- [ ] 目标测试及受影响旧测试通过；接口/数据库变化阶段运行全量后端及前端测试、构建。
- [ ] 文档中的已实现范围、配置默认值与运行命令已更新。
- [ ] 新存储覆盖导出、删除、到期访问和清理；数据迁移先 dry-run，禁止删除旧文件。
- [ ] 对安全/效果没有未经测量的提升百分比，Mock/live 不合并统计。
- [ ] 记录风险、待授权事项和下一阶段入口，再决定是否进入下一阶段。

## 回退原则

新业务入口配置默认关闭，先离线测试；关入口只停止新任务，不删除草稿和正式记录。确认接口仍检查版本、权限和过期。
计划存储切换后禁止直接退回旧文件作为当前状态源；先停写并核对导出，避免丢失新激活版本。数据库只做兼容性增加，不安排破坏性 down migration。
