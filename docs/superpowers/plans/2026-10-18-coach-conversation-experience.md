# C 教练会话体验与原 Agent 计划联合实施 Implementation Plan

> **For agentic workers:** Use executing-plans for sequential implementation and verification. 当前会话不自动创建分支／工作树，不自动提交／合并；独立审查与实现委派分别遵循用户授权。Steps use checkbox syntax for tracking.

**Goal:** 在原 Agent 主计划中补齐受控回答、悬浮多聊天及真实取消，再复用其交互承载 S3 计划调整，统一执行 S4/S5 的性能与效果验收。

**Architecture:** 共享现有 Runtime、安全链路、任务预算和确定性业务确认。Conversation/Turn 只管理交流和请求，S2/S3 的业务任务独立保存并以带所有权的引用关联；不复制任务状态机或确认通道。新会话位于现有业务 SQLite，不增加第三个数据库。

**Tech Stack:** FastAPI/Pydantic/SQLite/pytest；React/TypeScript/Vitest；可取消异步模型传输。

---

## 依据、状态和统一顺序

设计已获用户整体确认：[教练设计](../specs/2026-10-18-coach-conversation-experience-design.md)。原计划：[Agent 主计划](2026-10-10-agent-task-system-plan.md)，未开始部分为 S3/S4/S5。M及其业务化连接修订已经本地实现和离线验收，仍未提交／合并／部署。用户要求将本次体验方案与未完成计划一起推进，本文负责联合编排，不把设计审批记录成代码完成。

统一顺序：S0/S1/S2 已完成 → M 已完成本地验收 → **C0 → C1 → C2 → C3 → C4（离线） → S3 → S4 → S5**。

C有5个检查点，原S3有5个、S4有3个、S5有2个，合计剩15个阶段级检查点，不代表15个提交或15个小开发动作。每个检查点进入实施时按本文测试契约及准确文件分工细分，完成一个即可回归审阅；不要把全计划压成一次大改。C4中的真实模型与生产启用统一交给S5，不提前重复开展。

上述15项是联合计划建立时的起始余量，不是最新余量。2026-10-20：C0/C1/C2已有离线实现；C3核心接线已落地但浏览器人工验收有尾项。C4已开始第一批可独立推进的离线回放设施及四场景，不代表绕过C3验收或C4整体完成；S3/S4/S5未开始。详见各节、[C3记录](../../evaluation/2026-10-19-c3-coach-experience.md)及[C4记录](../../evaluation/coach-conversation-acceptance.md)。未提交／推送／部署，未对真实库迁移，未调用真实模型。

## 公共执行约束

1. 保持当前用户工作区和无关文件。计划编写不创建分支；将来若创建分支／工作树、集成或正式迁移，先依AGENTS.md备份保留的业务库和需要保留的runtime库，验证完整性并记录校验和，不能沿用M阶段的备份例外。
2. 测试只用隔离合成DATA_DIR和SQLite，凭据／DNS／模型均注入替身。每个测试进程显式配置隔离路径；全量旧fixture需要SQLITE_DATABASE_PATH空覆盖，配置优先级测试独立运行。
3. 所有步骤复用同一套输入最小化、范围判定、安全审核和预算；等待用户不占活动执行槽，用户确认不是模型生成调用。
4. 已批准每任务共享两轮修订不能被新聊天、刷新、详细解释、网络重试或候选更新重置。C普通问答不伪装成可无限恢复的S3业务任务；如果允许回答修订，必须绑定该Turn的持久额度。
5. 一账户一次教练执行：统一入口覆盖新Turn和旧Coach/解释API。S3中由教练发起的生成／修订进入同一活动准入；确定性查询／确认无需占用模型执行槽。不能让旧接口绕开单请求限制。S2预算和会话不因此混成Coach聊天状态。
6. 没有积压队列、跨聊天正文记忆、未经审核的流式草稿或重启自动重发。终端状态不能等同于尚未结束的模型传输清理。

## 文件分工与允许复用

| 位置 | 责任 |
| --- | --- |
| `backend/domain/coach_conversation.py`（新） | Conversation/Turn/Message、所有权、状态和90天可见性契约 |
| `backend/domain/coach_answer.py`（新） | zh/en、动作输出结构／长度、证据引用和正文显示契约 |
| `backend/application/ports/coach_conversation_repository.py`（新） | 列表、消息、幂等接受、活动准入、终态发布、到期／删除接口 |
| `backend/application/use_cases/coach_conversations.py`（新） | 创建／读取／删除、上下文投影、执行／停止协调，不实现第二套规划器 |
| `backend/infrastructure/repositories/sqlite_coach_conversation_repository.py`（新） | 业务库事务、条件更新、跨标签页准入、生命周期保护 |
| `backend/infrastructure/model_gateway/async_coach_gateway.py`（新） | Coach可取消异步传输；共用载荷构造／本地校验，不把现有同步线程当作可强杀 |
| `backend/api/coach_conversations.py`、`coach_conversation_schemas.py`（新） | owner范围的聊天／Turn／状态／停止HTTP接口 |
| `backend/agent/graph.py`、`contracts.py`、`workflow.py`、`model_payloads.py` | 传递受控语言、动作契约和当前聊天历史投影；仍由现有Runtime执行 |
| `backend/agent/tasks/input_contracts.py`、`backend/agent/grounded_answer.py` | 最小输入允许列表、证据与安全文案本地化 |
| `backend/infrastructure/sqlite/schema.py`、`backend/main.py`、`backend/config.py` | 追加迁移、依赖接线、服务关闭及新体验入口配置 |
| `backend/application/use_cases/export_account_data.py`、`backend/api/account.py` | 受限导出、删除／撤销认证时取消及迟到结果防复活 |
| `frontend/src/hooks/useCoach.tsx`（新） | Layout级统一控制器，窗口／页面不各自创建第二份请求状态 |
| `frontend/src/components/coach/CoachLauncher.tsx`、`CoachWindow.tsx`、`CoachMessages.tsx`、`CoachComposer.tsx`、`CoachHistory.tsx`（新） | 悬浮状态、非模态窗口、消息、输入法和历史 |
| `frontend/src/services/coachApi.ts`、`frontend/src/types/coach.ts`（新） | 新owner受控API与类型，不再用单次Markdown响应假装会话 |
| `frontend/src/components/Layout.tsx`、`routes/AppRoutes.tsx`、`pages/Chat.tsx` | 同一个教练入口及完整视图路由 |
| Today/Profile/PlanDetail/WeeklyReview与i18n/CSS | 快捷动作一次点击、日期／计划引用、准确业务文案、响应式 |

S3文件继续由其原实施计划负责，C仅创建任务引用展示位。不得在Coach会话表中另存一份可激活计划，也不得在聊天解析器里执行任意工具名／任意JSON路径。

## C0：语言和有界回答纵向闭环

**Test files:** `backend/tests/domain/test_coach_answer.py`、`backend/tests/test_coach_response_contract.py`（新）；回归既有 `test_coach_api.py`、`test_grounded_answer_providers.py`、`test_safety_writer_payload_reaches_provider.py`。

**状态（2026-10-18）：** 六项已完成离线实现与验收，证据见 `docs/evaluation/2026-10-18-c0-answer-contract.md`。未提交／推送／部署，未调用真实模型。

- [x] 写失败测试，构造中文账户＋无自由问题的explain_today，捕获真正Adapter发送的载荷，断言回答语言元数据是zh-CN而不是根据内部英文模板推断；英文证据标签／无证据／拒绝亦不得写死中文。再测用户明确要求英文只覆盖本次。
- [x] 输出契约先在domain中定义并测试：summary≤120字符，findings≤3条且各≤120字符，next_step≤120字符；普通正文≤1200，明确详细模式≤3000。证据数字由代码查表，模型只能引用允许证据；必要安全模板独立，不直接裁剪后发布。

```python
# backend/tests/domain/test_coach_answer.py
import pytest
from pydantic import ValidationError
from backend.domain.coach_answer import CoachBrief

def test_long_summary_and_extra_findings_are_rejected():
    with pytest.raises(ValidationError):
        CoachBrief(summary="长" * 121, findings=[], next_step="查看记录", evidence_refs=[])
    with pytest.raises(ValidationError):
        CoachBrief(summary="简短结论", findings=["重点"] * 4, next_step="查看记录", evidence_refs=[])
```

- [x] RED：先验证项目解释器pytest，再运行上述domain套件；预期缺少新契约失败，不能把环境故障当RED。随后实现 `CoachBrief`（extra=forbid、显式字段限制）及逐动作投影，使GREEN。
- [x] 受控语言／回答模式字段贯穿AgentCommand、state、最小输入与两种协议Adapter，不能只修改提示词而被投影丢掉；模型生成Token限制按协议映射。Reviewer看到的是将发布的完整受控结果，不能在安全审核后再拼未审核的模型正文。
- [x] 把“解释当前计划”与“生成调整草稿”解耦；目标建议只解释确定性计算结果。现有UI暂用旧布局也可验收C0，不提前声称多聊天／取消已实现。
- [x] GREEN后记录zh/en、长文本、虚构数字、安全拒绝和错误格式的合成执行证据。只提交用户授权的文件；本计划不自动提交。

## C1：持久会话、90天和输入投影

**Test files:** `backend/tests/domain/test_coach_conversation.py`、`backend/tests/infrastructure/test_sqlite_coach_conversations.py`、`backend/tests/application/test_coach_context.py`（新）；回归账户导出／删除与SQLite迁移。

**状态（2026-10-18）：** 五项已完成离线实现与验收，证据见 `docs/evaluation/2026-10-18-c1-coach-persistence.md`。未提交／推送／部署，未对真实库执行迁移。

- [x] 先定义仓储interface，参数必须显式包含user_id；当前选择的聊天、turn和消息所属账户不可由前端body覆盖。消息created_at由服务端产生，role和审查状态同样不能由浏览器伪造。

```python
# backend/domain/coach_conversation.py 中的纯到期规则；比较均使用aware UTC
from datetime import datetime, timedelta

def message_visible(created_at: datetime, now: datetime) -> bool:
    if created_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("Aware timestamps required")
    return now - timedelta(days=90) < created_at <= now
```

```python
# backend/tests/domain/test_coach_conversation.py
from datetime import datetime, timedelta, timezone
from backend.domain.coach_conversation import message_visible

def test_exact_ninety_days_is_expired():
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    assert not message_visible(now - timedelta(days=90), now)
    assert message_visible(now - timedelta(days=90) + timedelta(microseconds=1), now)
```

- [x] RED/GREEN：`& $coachPython -m pytest backend/tests/domain/test_coach_conversation.py -q -p no:cacheprovider`。数据库测试先建副本，追加迁移而不改已有迁移编号；新表使用owner键／FK／幂等唯一键，不新建第三个库。
- [x] 真实SQLite测试必须覆盖：跨用户读写拒绝、删除中迟到发布失败、90天过滤先于后台清理、用户消息过期后派生回复同失效、空聊天标题清除、重复清理幂等、导出不含过期正文、正式记录不受删除聊天影响。
- [x] 上下文interface输入user_id/conversation_id/turn_id/预算与时间；只选同聊天未过期完整回合，最多近期6轮并受预算剩余量限制。不自动摘要、不跨聊天读取，不将模型历史回答转换成权威档案；业务事实从正式仓储按需重读。
- [x] 接入账户受限快照导出与删除；不会在会话和runtime日志中复制两份原文。正式数据和runtime备份按AGENTS.md验证，仅在用户授权后正式迁移。

## C2：接受请求、单槽、状态与真实取消

**状态（2026-10-19）：** 七项已完成离线实现与验收，证据见 `docs/evaluation/2026-10-19-c2-turn-admission.md`。未提交／推送／部署，未调用真实模型。

**Test files:** `backend/tests/test_coach_conversation_api.py`、`backend/tests/test_coach_turn_lifecycle.py`、`backend/tests/infrastructure/test_async_coach_cancellation.py`（新）。

- [x] 新路由先写公开接口失败测试：认证、owner、幂等重复、不同键并发单槽、stopping不得放行第二次、等待用户后可释放执行槽。新入口独立配置默认关闭，C0的语言错误修复不依赖开启新聊天入口。

```text
POST   /api/v1/coach/conversations
GET    /api/v1/coach/conversations
PATCH  /api/v1/coach/conversations/{conversation_id}
DELETE /api/v1/coach/conversations/{conversation_id}
GET    /api/v1/coach/conversations/{conversation_id}/messages
POST   /api/v1/coach/conversations/{conversation_id}/turns  + Idempotency-Key
GET    /api/v1/coach/active-turn
GET    /api/v1/coach/turns/{turn_id}
POST   /api/v1/coach/turns/{turn_id}/cancel
```

- [x] POST Turn在owner生命周期与数据库原子准入中保存输入和执行身份，返回turn_id；执行只接受已有身份，不让GET触发模型。若没有活动槽则拒绝，不排队。生成前后不持有数据库写事务或跨线程持有lifecycle锁。
- [x] 原子终态发布必须检查owner、未删除、未取消、未过期、版本和已完成审核；终态响应未知重试只读取同一回执，不启动第二次调用。startup将本进程不能恢复的旧活动任务标interrupted，不重发；新功能不宣称支持多worker分布式执行。
- [x] 用可取消的合成慢HTTP验证真正的关闭：记录传输started/closed，cancel后直到closed前活动槽都不释放，任何迟到答案不保存；对Planner、Writer、Reviewer及重试等待分别覆盖。不能只断开浏览器fetch而继续留下同步模型线程。
- [x] 旧 `/coach/action`、计划解释和周报解释接入同一准入，不留绕过路径；新客户端逐步迁移，普通返回错误保持脱敏。安全检查失败不流式泄露草稿。关闭浏览器／刷新后请求身份仍可读，服务进程重启不自动恢复推理。
- [x] 删除聊天、账户注销／撤销认证和退出登录的取消规则纳入同一服务，不以“当前窗口关闭”代替账户执行状态。模型上游已产生费用不可撤销的限制有明确提示。
- [x] GREEN后才可对用户交付“收起继续”和“停止生成”。（后端准入与取消已 GREEN；按钮本身属于 C3 前端，本阶段只交付可依赖的接口。）

## C3：统一悬浮多聊天和快捷入口

**状态（2026-10-20）：核心实现与自动化已落地，浏览器验收已完成自动化部分。** 计划/周报持久引用、来源、多轮输入、账户生命周期及失败显式重试已接通；真实 Chrome 下 375/768/1024/1440 与 200% 缩放模拟共 64/64 检查通过，并据此发现并修复两处真实缺陷（停止提示跨回合残留、空会话在短视口下欢迎标题被裁）。真实物理键盘缩放、OS 输入法与屏幕阅读器演练仍未取得，不冒充通过。准确证据见 [C3实施与验证](../../evaluation/2026-10-19-c3-coach-experience.md)。默认开关关闭，未部署。

**Test files:** `frontend/src/components/coach/CoachWindow.test.tsx`、`CoachComposer.test.tsx`、`frontend/src/hooks/useCoach.test.tsx`（新）；回归Today/Profile/计划/周报路由测试。

- [x] 使用Mock API先写失败测试：窗口入口不请求模型；快捷动作一次点击追加用户可读动作并执行；收起/最大化/路由切换不重复调用。切换聊天按ID保存输入与滚动位置，活动Turn提示所属聊天，不自动把当前页面变成隐式上下文。完整手工滚动演练仍见末项。

```tsx
// CoachComposer 的interface明确包含 composing、disabled 与发送行为。
// 最小交互回归：中文输入法按Enter不得发送；结束组合后Enter才发送。
fireEvent.compositionStart(input)
fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
expect(onSend).not.toHaveBeenCalled()
fireEvent.compositionEnd(input)
fireEvent.keyDown(input, { key: 'Enter' })
expect(onSend).toHaveBeenCalledTimes(1)
```

- [x] Layout级Provider持有同一useCoach控制器；窗口与最大化完整视图只改变展示方式，不各挂一套请求／轮询。读取服务端状态／终态，断线恢复不重发，离开账号作用域清除本地私密状态。
- [x] 桌面默认居中非模态窗，720px/80vh建议尺寸、拖拽限制在视口内；不同时设置aria-modal=true和允许背景操作。最大化及手机全屏保持状态；危险确认使用原生模态dialog，完整焦点人工演练仍见末项。
- [x] 消息顺序追加；sources/日期／建议标识可见，技术信息折叠。实现阅读位置保存和新回复提示，错误/停止使用live status；IME composition和发送快捷键有组件回归。未声称已完成真实屏幕阅读器或OS输入法验收。
- [x] 新入口开启时移除各页面独立CoachDrawer执行状态，开关关闭时保留旧入口回退；既有业务表单不变。计划页解释和正式调整命名/接口分开，确认不被“发送”代替。
- [x] 运行目标前端测试、全量与生产构建。浏览器验收用合成账户／合成模型响应，检查375/768/1024/1440与键盘缩放；不能仅凭jsdom通过声称视觉和移动端合格。（2026-10-20 完成：定向 8 文件/55 项、全量 46 文件/299 项、`VITE_COACH_CONVERSATIONS_ENABLED` true/false 两种构建均通过；真实 Chrome+CDP 在 375/768/1024/1440 与 200% 缩放下 **64/64 检查通过**，证据 `.tmp/c3-browser/results.json` 与 15 张截图。**缩放是 CDP 指标模拟（CSS 视口减半 + DPR 2），不是物理键盘 Ctrl 加号缩放**；OS 中文输入法与真实屏幕阅读器仍未验收，见 [C3记录](../../evaluation/2026-10-19-c3-coach-experience.md)。）

## C4：离线整体验收与S3交接

**Files:** 新增 `backend/task_evaluation/scenarios/coach_conversations.json`、`docs/evaluation/coach-conversation-acceptance.md`；更新 `docs/agent-task-contracts.md`、README及主计划。

**状态（2026-10-20）：离线验收完成，未上线。** 场景清单从首批 4 个扩展到 **16 个**，覆盖计划要求的全部类别；判分读取真实消息、运行记录与数据库不变量，观察项只允许非负整数与固定枚举。全量后端业务组 2237 passed / 0 failed、配置独立组 6 passed、C4 专项 33 passed、前端 46 文件 / 299 passed、两种开关构建与 `git diff --check` 均通过。**仍不包含**：真实模型质量、分布式 worker、进程重启续跑、定时物理清理调度、S3 原子计划激活。详见 [C4验收记录](../../evaluation/coach-conversation-acceptance.md)。

- [x] 回放：中文快捷解释、英文设置／明确语言覆盖、过长结果、安全拒绝、多轮同聊天、跨聊天不共享正文、收起完成、跨标签页冲突、停止清理、90天过期、聊天删除/账户删除、来源和旧数据提示。判分检查真实消息／运行记录和数据库不变量，不只匹配“成功”文案。（16 个场景 **16/16 通过**，全部 mock、网络阻断、每个场景独立 `tmp_path` SQLite。其中“收起完成”“旧数据提示”没有后端可观察量，**不伪造回放通过**，分别由 C3 浏览器演练与组件回归覆盖，对照表见 [C4记录](../../evaluation/coach-conversation-acceptance.md)。）
- [x] 沿用独立评估环境和网络阻断；没有对应功能不得伪造成功，Fake与live报告分组。整体验收前运行本次解释器与隔离环境下的完整后端业务组、配置独立组、前端全量、构建与diff检查。（后端业务组 **2237 passed / 0 failed**（26:36，报告 `.tmp/c4-full-20261020b.xml`）；配置独立组 **6 passed**；前端 **46 文件 / 299 passed**；两种开关构建均通过；`git diff --check` exit 0，仅既存 CRLF 提示。全部 mock，无 live 报告，因此不存在 Fake/live 合并陈述。）
- [x] 给S3交接 `business_task_ref={kind, task_id}` 的只读展示能力，不复制候选／预算／权限。C4离线通过不表示S3原子计划激活完成，真实模型和上线仍等S5授权。（`kind` 限 `[a-z_]{1,40}`、`task_id` 限 `[A-Za-z0-9_-]{1,64}`，候选/预算/权限字段在投影时丢弃；前端只渲染为不可点击文本，无 `button`/`a`。6 项测试覆盖合法投影与 4 类非法拒绝。**目前没有 S3 生产方写入该字段**，能力已就绪但未被业务调用。）

## S3 接入同一教练，不重建计划生成器

S3仍执行原 `2026-10-10-agent-task-s3-plans.md` 的5个任务，以下是追加契约：

1. 教练显示范围许可、任务状态和差异卡片，所有scope/answers/execute/confirm委派S3同一业务服务。
2. 自然语言“顺便改饮食”只提出范围变更，不视为模型已获授权；显式确认持久化后才读取该域资料和调用模块。
3. 聊天重试／详细说明不重置S3整任务两轮修订、任务预算、候选版本或基准head。候选过期按S3规则处理，不能换聊天获得新额度。
4. PlanAdjustmentDialog/PlanDiff应拆为可复用内容，计划页和教练卡片复用同一数据与确认interface；不可出现两个不同激活通道。
5. 旧计划接口继续受同一S3权限／版本／幂等约束。确认动作确定性且原子，模型没有confirm权限。
6. 聊天90天到期只移除聊天及引用；业务任务按自己的TTL处理，正式计划／激活回执遵守业务保留规则，不因删除聊天被级联删除。显式确认形成的业务对象不是用于绕过聊天到期的隐藏摘要，不保存整段对话镜像。

## S4 统一性能评估，不用弱化安全换速度

原S4的3个任务保留，追加Coach分组：简短快捷解释、同聊天追问、长历史投影、计划差异解释、失败／取消。比较reference/optimized必须使用相同语言、回答长度契约、数据、模型、安全模式和预算。

不能把“旧版本输出几千字，新版本只输出短卡片”直接宣传成同等质量推理性能提升；输出体验改造单列指标，算法／缓存优化用同等契约配对。

指标区分请求接受时间、首次安全可读结果时间、S3候选首次可确认时间、取消传输清理时间、调用/token及失败成本。未审核text_delta不算首个可读答案；轮询的loading出现也不算生成变快。真实网络时延不从Mock估算。

## S5 一次收口，分业务场景记录证据

原S5的2个任务保留，增加Coach90天生命周期、zh/en回答质量、悬浮跨页面连续性和取消演练。S5先做离线manifest／标注／迁移演练，再在用户明确批准的模型、批次费用／调用预算、数据范围内实测；正式迁移和上线另取对应许可。

范围按教练问答、S2录入、S3单域／联合计划分组，不用一个连接测试成功代替全部业务验收。不会在本计划编写阶段读取真实密钥、执行正式清理或迁移。

## 可重放验证环境

以下只定义实施时的合成测试环境，不在计划编写阶段执行：

```powershell
$coachPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
& $coachPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
$env:DATA_DIR = Join-Path (Get-Location).Path '.tmp\coach-conversation-tests'
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Path $env:DATA_DIR -Force | Out-Null
& $coachPython -c "import os; from pathlib import Path; from scripts import generate_sample_data as s; s.DATA_DIR=Path(os.environ['DATA_DIR']); s.main()"
if ($LASTEXITCODE -ne 0) { throw 'Synthetic seed failed' }
& $coachPython -m pytest backend/tests --ignore=backend/tests/test_config.py -q -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
npm --prefix frontend test
if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
```

每个新API fixture还要显式使用自己的tmp_path SQLite，不能只依赖全局目录。配置测试在另一进程移除DATA_DIR/SQLite环境后执行。真正备份使用主checkout的配置，不可以在上述测试环境下备份后假称保留主库。

## 完成判据

- [ ] C0–C4离线交付，不把五个设计检查点当作已实现。
- [ ] S3五项完成业务闭环和原子确认，含Coach与计划页同源。
- [ ] S4三项有可重放同等安全对照，无收益如实记录。
- [ ] S5两项离线与获授权的live／上线状态分开报告。
- [ ] 每阶段更新准确的代码SHA／diff、测试报告、数据隔离、风险与待授权动作；没有授权不自动提交、推送、部署或进入真实模型实验。
