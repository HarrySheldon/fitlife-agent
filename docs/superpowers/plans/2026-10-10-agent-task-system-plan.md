# Agent 任务系统总交付 Implementation Plan

## 2026-10-31 当前执行入口（覆盖下方历史状态）

核查基线：本地 `main/f9e70fc`，工作区干净，HEAD 与本地缓存 `origin/main` 相同；本次没有 fetch，因此不据此保证服务端没有新提交。S3、S4及审查修补已进入 main，不再是待提交的开发分支改动。代码集成不等于最终验收、部署或正式数据迁移完成。

后续执行以[当前交付与验收清单](2026-10-31-agent-delivery-status.md)为唯一进度入口；下方日期章节和未勾选的原始 RED/GREEN 步骤只保留设计及执行历史，不能用于计算剩余数量。取消旧“剩余19项”等实时统计口径。

三条 Agent 主线保持不变：可信执行、受约束规划与可靠落地、质量约束下的性能。先完成 S3/S4 最终验证，再推进 S5 工程交付、授权效果验证及 U7；不为简历新增无收益的平台或强行启用缓存。暂不要求提升百分比，但保留真实计量和可比对照能力。

RAG 作为独立工作线，按[知识治理、检索与证据升级计划](2026-10-31-rag-quality-upgrade.md)推进，不复建统一 Runtime，不把现有 hashing 向量描述成语义模型。

## 2026-10-30 审查修补进度（优先于下方历史快照）

S4-A与S3已有提交，S4-B/C/D及审查修补仍在当前开发分支工作区。上次审查的9组问题及复审发现已修补，两路只读复审确认各自发现关闭；不等于全部阶段验收完成。

当前仍需最终完整回归、离线回放及交付证据同步，不能把下文“尚未开始”或旧待办数量当成实时进度。详见[本次修补与验证记录](../../evaluation/2026-10-30-s3-s4-review-closeout.md)。S5、U7和RAG详细升级仍不在本次交付内；未提交、合并、推送、迁移正式数据或调用真实模型。

## 2026-10-23 当前路线与状态（优先于下方历史快照）

已按用户确认的[路线重组设计](../specs/2026-10-23-agent-roadmap-reorganization-design.md)重写S3/S4/S5。三条主线为：

1. **可信执行：** 把业务理解、安全审核与实际执行权限分开，控制隐私读取、提示注入影响及正常请求误拒。
2. **受约束规划与可靠落地：** 同一Agent借助Skill和确定性工具提交有类型候选，约束失败有限修订，用户确认后原子激活。
3. **质量约束下的性能：** 先测模型往返、上下文和实际耗时，再做可信预取、依赖失效与局部复用；质量/安全一致才比较收益。

统一Runtime、Skill和供应商Adapter是共用底座，不单独包装为原创算法。RAG仍为独立知识工程工作线；当前小型知识库及hashing向量检索不能冒充语义检索提升，本轮不包含完整RAG升级计划。

核对基线`main/3519f69`，统一教练实现`93e09a4`已集成；证据见[本次集成记录](../../evaluation/2026-10-23-unified-coach-integration.md)。默认模式和安全配置以实际代码为准，集成不等于生产开关已启用。主目录已有两项transport修改继续保留。**本次只落地计划，S3/S4/S5代码尚未开始，不新增实测指标。**

| 当前顺序 | 详细计划/检查点 | 验收目标 |
| --- | --- | --- |
| 已有基础 | S0/S1/S2、M、C、U历史见下文与各验收记录 | 复用已交付能力，不因新路线重做另一套Agent |
| 首先执行 | [S4-A1/A2](2026-10-10-agent-task-s4-performance.md)（2项） | 闭合attempt计量、来源指纹、同引擎reference与配对基础 |
| 其次执行 | [S3 Task 1–8](2026-10-10-agent-task-s3-plans.md)（8项） | 类型Patch、持久任务、TaskSession/ToolSpec、候选工具、有限修订、原子确认、同源UI、评估 |
| 再做优化 | [S4-B1/C1/C2/D1](2026-10-10-agent-task-s4-performance.md)（4项） | 有收益证据的上下文/依赖/缓存优化及同等质量报告 |
| 最后验收 | [S5 Task 1–4](2026-10-10-agent-task-s5-acceptance.md)（4项） | 离线准入、live Adapter、授权实测、受控发布与生命周期 |
| 收尾 | U7 默认启用与教练legacy退役（1项，见§13） | 新引擎成为默认路径，旧教练分支移除，四处开关同步 |

S5 Task 1可提前离线准备；Task 2用假Provider接通，真正probe另获授权后可辅助profiling。最终acceptance依赖S3及S4-D，不能为了测性能跳过质量验收。S4-C2若基线不支持缓存收益，记录不实施优化的结论并以禁用路径验收，不为亮点硬加缓存。

**剩余19个计划检查点：S3 8 + S4 6 + S5 4 + U7 1。** 它们是任务拆分，不是工作量百分比或模型调用次数。原23项及“余12/15项”只保留作历史记录；已完成S0/S1/S2的13项不重编号。旧S3/S4/S5映射在各新计划中列出。

**默认值决定（2026-10-23用户确认）：** 统一Agent不再长期挂在默认关闭的开关后面。`coach_agent_mode`、`coach_conversations_enabled`、`VITE_COACH_CONVERSATIONS_ENABLED` 与 S3 的 `plan_adjustment_tasks_enabled` 均按默认开启实现；`plan_storage_mode` 与 `task_execution_strategy` **不跟着改**（前者属数据迁移授权，后者属对照实验基线）。退役顺序与精确范围见[路线图设计§13](../specs/2026-10-23-agent-roadmap-reorganization-design.md)：**先 S5 验收、后删 legacy**，且只退役教练的模式分叉，不删 `business_scope`、`BoundaryWorkflow`、`structured_workflow`（S2智能录入与计划页仍依赖它们）。

### 当前设计覆盖表

| 设计要求 | 新检查点 | 验证证据 |
| --- | --- | --- |
| 封闭工具效果、可信TaskSession与模型权限分离 | S3-3/4；S5-1 | 不可信内容不授权、越权handler零触达、草稿写入非read-only |
| 有类型候选、硬约束与差异 | S3-1/4/5 | 不解析final Markdown为候选、不改未授权领域、不信模型校验标志 |
| 整任务两轮修订、跨run预算、业务失败分类 | S3-2/5/8 | CAS并发、幂等恢复、初次round0、两域共享额度 |
| 原子确认、旧版本冲突、权威约束与唯一存储源 | S3-6 | 同事务重验、head/digest检查、响应丢失重放不重复激活 |
| 教练/计划同源、等待释放槽、账户生命周期 | S3-7/8；S5-4 | 同任务卡片、无双槽死锁、到期/导出/删除、聊天不删正式历史 |
| 真实计量、来源指纹、对照可比性 | S4-A1/A2/D1；S5-2/3 | 物理attempt闭合、unknown不作0、Mock/live分开 |
| 稳定前缀、最小上下文、增量依赖与有界复用 | S4-B1/C1/C2 | 授权先于缓存、撤销/版本变更失效、不伪称KV cache命中 |
| 正常业务误拒、隐私/攻击和健康边界 | U既有保护；S3-8；S5-1/3 | 合成对抗/正常案例、人工盲标、确定性不变量和语义质量分列 |
| 受控启用及可用于简历的证据 | S5-3/4 | SHA/配置/样本/失败明细、实际usage、授权与发布状态分开 |

下文历史中的“成功模块冻结”在新实现中指：仅在其权威依赖指纹未变化时复用；联合约束变化必须重新验证。每轮接纳一个typed bundle，业务校验失败占本轮；协议错误不冒充正常约束反馈。正式激活不是模型工具，Provider不进入写事务。

### 代码实施前门禁

只改文档不创建分支或操作数据。开始代码时先读工作区差异，不覆盖用户修改；新分支/工作树之前按AGENTS.md使用主解释器和配置运行`scripts/backup_sqlite.py --output <绝对备份路径>`，在主checkout的忽略目录`.local-backups/`保存备份，核验integrity=ok并记录SHA256；需保留run历史时同时备份Runtime库。隔离数据副本及账户配置/加密密钥，核对实际数据库和Docker挂载不指主库。测试只用合成数据，真实连接密钥不打印、不进Git。

集成或正式迁移前再次备份保留的主库；迁移先副本/dry-run，正式应用独立授权。提交/推送、删除工作树及开发数据也不由“计划写好”推断授权。

---

## 历史阶段记录（以下日期状态不得覆盖上述当前路线）

## 2026-10-22 新增 U 前置阶段

用户确认在 S3 前实施 [U0–U6 统一教练计划](2026-10-22-unified-coach-agent.md)，采用同一个 Agent、渐进式 Skill、确定性工具与统一执行权限；不开放脚本或任意代码。本地实现及证据见 [U验收记录](../../evaluation/unified-coach-acceptance.md)。下文旧日期状态保留为历史，不能当作当前未提交/已发布结论。

新顺序：S0/S1/S2 → M → C0–C4 → U0–U6 → S3 → S4 → S5。S3 仍持有正式任务、共享两轮修订、版本差异与原子确认；不另建一套具有独立权限与预算的模型 Planner/Writer。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 按六阶段交付可恢复、受约束、可评估的业务 Agent。

**Architecture:** 沿用统一 Runtime，扩展领域任务状态；先测试基础，再安全契约，再业务纵向切片，最后做同等安全前提下的性能对照。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---


## 依据与当前范围

设计：`docs/superpowers/specs/2026-10-10-agent-task-system-design.md`。代码核对基线：`1029a27`。
计划编写时仅生成文档。S0 已完成并以 `e3027f6` 提交、推送到 `codex/agent-runtime-refactor`，未合并到 main。2026-10-15 用户授权并完成 S1：四个任务及最终集成审查通过；最终后端 1719 passed、计划指定套件 99 passed、前端 229 passed 且构建通过，六类离线基线 6/6 通过。S1 已按用户授权提交为 `eff4527`，提交前复验相关套件 129 passed（3.96 秒），尚未推送或合并到 main。2026-10-17 S2 五项任务已完成实现与离线验收，最终规格和质量复核问题已关闭；后端全量 1919 passed、前端全量 267 passed，构建通过，八类交互与六类旧基线离线场景分别 8/8、6/6 通过。S2 所有改动仍未提交或推送，功能默认关闭；S3–S5 尚未启动。详细证据与边界见 S2 计划、`docs/evaluation/2026-10-16-s2-entry-acceptance.md` 及 `docs/agent-task-contracts.md`。

用户已确认整任务共享两轮自动修订；生命周期期限和联合确认策略沿用设计建议值，在相关阶段实施前再确认，不把离线实施许可推断为生产迁移、真实模型调用或上线许可。S1 的生命周期验证仅为纯访问/导出契约；新任务存储、账户集成与原子确认属于 S2/S3。

## 2026-10-17 集成状态与新增前置阶段

上节阶段记录是当时快照，其中“未提交／未合并”的描述已由后续集成取代：S0、S1、S2 已合入本地 main；S1 为 `eff4527`，S2 为 `120f7ca`。目录发布修复和验收文档已另提交；本次计划编写时 main 为 `aa63c77`，缓存 origin/main 为 `120f7ca`，本地 ahead 3，不能宣称最新修复已发布远端。S3–S5 尚未启动。

用户确认在 S3 前插入独立 **M：通用模型连接与显式验证**，不重编号原 S0–S5，也不把它计入原 23 个检查点。新增设计：[模型连接设计](../specs/2026-10-17-model-connection-workflow-design.md)；实施计划：[M 阶段七个检查点](2026-10-17-model-connection-workflow.md)。2026-10-18 已在 `codex/model-connection-workflow` 完成本地实现、独立复审及离线完整回归（后端业务 2012、配置 6、前端 276 项及构建通过）；未提交、合并或部署，未进行真实 Provider 验收。S3 仍尚未开始。

当时新增执行顺序为S0 → S1 → S2 → M → S3 → S4 → S5；现已由下方2026-10-18联合编排取代。M负责当前表单测试、后端验证凭证、草稿与生效配置隔离以及可复用服务商预设，不包含工作树启动脚本改造。

2026-10-18 后续用户确认 [连接测试业务化修订](2026-10-18-connection-business-check.md)：取消原生工具调用准入和分能力展示，统一「测试连接」，内部生成＋最小业务 JSON 解析，兼容服务探测与实际结构化业务共用本地验证。凭证升级 v2，保留工作区／安全／超时约束。修订已完成本地实现及离线验收：新版后端完整业务2026项、配置6项、前端278项及构建通过，独立复审无遗留发现；以上首版2012项仅作历史。未提交、合并、推送或部署，真实供应商未实测。S3–S5未启动。

## 2026-10-18 教练体验与剩余计划联合编排（历史执行顺序）

用户已整体确认 [教练会话与交互设计](../specs/2026-10-18-coach-conversation-experience-design.md)，并要求与原未完成计划一起推进。新增 [C阶段及联合实施计划](2026-10-18-coach-conversation-experience.md)，保持S0–S5原编号；不是把聊天、计划调整和性能重写成一个巨大任务。

当前顺序：**S0/S1/S2（已完成） → M（已完成本地验收） → C0 → C1 → C2 → C3 → C4离线 → S3 → S4 → S5**。

C阶段5个检查点为语言／输出契约、90天持久会话、原子准入与真实取消、悬浮多聊天、离线整体验收。S3原5项、S4原3项、S5原2项保留，合计还剩15个阶段级检查点；批准设计／写好计划不等于代码交付。M仍未提交／合并／部署，不能以本地验收代替远端或生产状态。

**进度（2026-10-19）：** C0、C1、C2 已完成离线实现与验收，未提交／推送／部署，未调用真实模型，未对真实库执行迁移。
证据见 [C0 回答契约](../../evaluation/2026-10-18-c0-answer-contract.md)、
[C1 持久会话](../../evaluation/2026-10-18-c1-coach-persistence.md) 与
[C2 准入与取消](../../evaluation/2026-10-19-c2-turn-admission.md)。

2026-10-19 后续修复删除聊天提前释放执行槽，并接入真实可取消异步传输。**C3核心实现与自动化已落地，浏览器验收仍有尾项**：统一浮窗、多聊天、持久计划/周报引用、实际多轮输入、来源、账户取消和显式失败重试已接通；375–1440px合成浏览器检查已执行，真实缩放/OS输入法及完整焦点/滚动演练不冒充完成。准确测试结果、限制见 [C3实施与验证](../../evaluation/2026-10-19-c3-coach-experience.md)。2026-10-20已推进C4独立评估器的异步等待和首批四个场景，仍非完整C4，详见[C4验收记录](../../evaluation/coach-conversation-acceptance.md)。阶段级余量仍为12项（含未全部验收的C3/C4），不是工作量完成百分比。未提交／推送／部署，正式库未迁移。

统一职责：Conversation/Turn保存交流和单次请求；S2/S3 Task继续拥有业务状态、权限、修订和确认。Coach只展示并引用同一S3任务，不能重置整任务两轮修订或另建激活通道。聊天90天清理不级联删除正式计划，S3任务／候选TTL仍按其阶段规则单独确认，不被聊天期限覆盖。范围许可、差异确认不由模型自行决定。

C的真实模型和发布检查并入S5，避免重复耗费密钥／预算；S4对照须固定相同语言和输出长度契约，不能用“少回答”充当同等质量的算法提速。新存储进入实施时遵循AGENTS.md备份／隔离／副本验证，本文没有执行迁移、模型调用或生产启用。

## 旧版阶段及依赖（由2026-10-23路线取代）

| 顺序 | 计划文件 | 可交付结果 |
| --- | --- | --- |
| 1 / S0 | [评估基线](2026-10-10-agent-task-s0-evaluation.md) | 离线隔离回放与可信基线，不把未实现功能算成功 |
| 2 / S1 | [共享契约与安全](2026-10-10-agent-task-s1-contracts.md) | 持久任务契约、字段最小化、权限与业务范围分离 |
| 3 / S2 | [交互录入](2026-10-10-agent-task-s2-entry.md) | 多项澄清、局部修改、部分确认及恢复完整闭环 |
| 前置 / M | [模型连接及修订](2026-10-18-connection-business-check.md) | 已完成本地验收；当前配置测试、凭证和草稿隔离 |
| 新增 / C | [教练体验与联合实施](2026-10-18-coach-conversation-experience.md) | 受控回答、悬浮多聊天、90天历史、单请求及真实取消 |
| 原4 / S3 | [统一计划调整](2026-10-10-agent-task-s3-plans.md) | 双领域协调、有限纠错、差异确认及原子激活，与Coach同源 |
| 原5 / S4 | [性能优化](2026-10-10-agent-task-s4-performance.md) | 局部复用、路径裁剪及同等安全／回答契约配对报告 |
| 原6 / S5 | [真实模型验收](2026-10-10-agent-task-s5-acceptance.md) | C/S2/S3统一分场景验收，获授权后实测及受控发布 |

原串行主依赖 S0 → S1 → S2 → S3 → S4 → S5；当前执行顺序以新增前置阶段一节为准。S2/S3 的场景分别随业务补齐，S0 不伪造不存在的多轮 API。
共 23 个任务检查点：S0 4 个、S1 4 个、S2 5 个、S3 5 个、S4 3 个、S5 2 个。阶段不是单个大提交，每任务先写失败测试，再实现，再回归。

## 旧版设计覆盖与验收位置（当前映射见文首）

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
| 语言、动作长度与安全渲染 | C0；C4；S5 | zh/en、受控短答、来源与最终安全检查 |
| 悬浮多聊天、关闭继续、真实取消 | C1–C4；S3接口接入 | 会话与run分离、跨标签页单槽、传输清理后释放 |
| 聊天90天、跨聊天隔离、导出删除 | C1/C4；S5生命周期演练 | 访问过滤先于清理、无过期摘要、正式数据不被聊天删除 |

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
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
git status --short --untracked-files=no
git rev-parse HEAD
$taskPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $taskPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
$env:DATA_DIR = Join-Path (Get-Location).Path ".tmp\agent-unified-tests-$taskStamp"
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
$env:OPENAI_API_KEY = ''
New-Item -ItemType Directory -Path $env:DATA_DIR -Force | Out-Null
& $taskPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed' }
& $taskPython -m pytest backend/tests --ignore=backend/tests/test_config.py -q -p no:cacheprovider --basetemp=".tmp/pytest-full-$taskStamp"
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
npm --prefix frontend test
if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
```

记录命令、环境、提交、工作区差异、耗时、失败类别；不能复用过去“1498 passed”当本次基线。环境故障和真实断言失败分开，修复仅限任务必要范围。
新测试不能访问真实账户和 Provider。前端构建内脚本含 shell 逻辑由 npm 处理，不在 PowerShell 手写 Bash 运算符。
上述是合成回归命令，不是主库备份命令。配置优先级测试另起独立PowerShell进程，清除DATA_DIR、SQLITE_DATABASE_PATH、LLM_ENABLED、OPENAI_API_KEY等本轮覆盖后，以同一项目解释器执行 `-m pytest backend/tests/test_config.py -q -p no:cacheprovider`；不修改.env；新API fixture还需固定自己的tmp_path数据库。详细隔离和分组约束见C联合计划。本文只更新命令，没有实际运行测试或生成数据。

## 阶段结束检查

- [ ] 目标测试及受影响旧测试通过；接口/数据库变化阶段运行全量后端及前端测试、构建。
- [ ] 文档中的已实现范围、配置默认值与运行命令已更新。
- [ ] 新存储覆盖导出、删除、到期访问和清理；数据迁移先 dry-run，禁止删除旧文件。
- [ ] 对安全/效果没有未经测量的提升百分比，Mock/live 不合并统计。
- [ ] 记录风险、待授权事项和下一阶段入口，再决定是否进入下一阶段。

## 回退原则

新业务入口配置默认关闭，先离线测试；关入口只停止新任务，不删除草稿和正式记录。确认接口仍检查版本、权限和过期。
计划存储切换后禁止直接退回旧文件作为当前状态源；先停写并核对导出，避免丢失新激活版本。数据库只做兼容性增加，不安排破坏性 down migration。
