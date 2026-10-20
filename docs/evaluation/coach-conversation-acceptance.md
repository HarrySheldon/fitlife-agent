# 教练会话离线整体验收（C4）

日期：2026-10-20。分支 `codex/model-connection-workflow`，基准 HEAD `aa63c77`，既有未提交工作区。
状态：**C4 回放与回归已完成；S3 原子激活、真实模型与上线不在本记录范围内。**

本记录替代同日早前“首批四场景”的阶段性结论。早前结论只覆盖零模型调用的边界路径，不能代表
完整教练质量或生命周期；下文以当前 16 个可重放场景与整体回归为准。

## 结论

- **回放**：16/16 场景通过。全部为 mock、独立临时数据库、网络阻断；没有任何真实 Provider 调用。
- **回归**：见“整体回归”一节。后端业务组、配置独立组、前端全量、生产构建与 diff 检查分别记录，
  不把不同组件的通过数相加成“覆盖总量”。
- **S3 交接**：`business_task_ref={kind, task_id}` 的只读展示能力已实现并有单元/组件回归；
  当前没有 S3 生产者，因此不声称任何计划候选、预算或原子激活已经完成。
- **不声称**：真实模型回答质量、真实网络时延/费用、OS 输入法与真实屏幕阅读器、生产启用或部署。

## 可重放场景（16）

| 场景 | 实际检查 | 不证明什么 |
| --- | --- | --- |
| coach-zh-boundary | 中文显式语言、确定性边界正文、终态/入库、无未审核回答、零模型调用 | 任意中文范围外问法都零调用拒绝 |
| coach-en-explicit-boundary | 英文显式语言、边界正文、完成/入库、零调用 | 真实模型遵循语言或复杂回答质量 |
| coach-idempotent-owner-isolation | 同键只留一个 Turn；另一账号读取/取消均 404 | 两标签页并发竞争（由 cross-tab 场景补） |
| coach-missing-saved-plan-no-generation | 缺失已保存计划→failed，仅用户消息，不生成计划 | S3 候选生成或原子激活 |
| coach-zh-quick-explain | 中文快捷解释真正执行（2 次网关调用）、终态、2 条消息 | 真实模型自然语言质量 |
| coach-en-account-language | 账户语言设为 en-US、请求不显式指定时回执为 en-US | 模型正文本身是英文 |
| coach-explicit-language-override | 账户 en-US、请求显式 zh-CN 时回执为 zh-CN | 所有语言分支都已本地化 |
| coach-oversize-answer-rejected | 超长输出→failed，仅保留用户消息，不截断发布 | 所有动作的输出上限都被同一路径覆盖 |
| coach-multiturn-same-chat | 同聊天两轮→4 条消息、2 次成功、4 次调用 | 长历史预算与投影质量 |
| coach-cross-chat-isolation | 两个聊天各自只返回 2 条；总库 4 条 | 跨标签页正文隔离 |
| coach-cross-tab-conflict | 运行中第二键→409，只产生一个 Turn | 分布式多 worker 协调 |
| coach-stop-cleanup | 取消→cancelled、槽释放、迟到答案不入库、随后可再发 | 上游已产生费用可撤销 |
| coach-retention-90d | 消息回拨到 2000 年后读取为 0，Turn 与库内行仍在 | 定时物理清理调度 |
| coach-chat-deleted | 删除聊天→Turn 终止、消息/取消均 404 | 删除中迟到发布的全部竞态 |
| coach-account-deleted | 删除账户→Token 失效（401）、聊天与消息计数为 0 | 文件系统清理的完整审计 |
| coach-sources-visible | 知识型回答的消息回执含来源，接口仍只暴露计数 | 来源正文、排序或质量 |

## 与计划 12 类清单的对照

| 计划条目 | 证据 |
| --- | --- |
| 中文快捷解释 | coach-zh-quick-explain |
| 英文设置／明确语言覆盖 | coach-en-account-language、coach-explicit-language-override |
| 过长结果 | coach-oversize-answer-rejected |
| 安全拒绝 | coach-zh-boundary、coach-en-explicit-boundary（确定性范围拒绝，零调用） |
| 多轮同聊天 | coach-multiturn-same-chat |
| 跨聊天不共享正文 | coach-cross-chat-isolation（各自 `messages.length`） |
| 收起完成 | C3 真实浏览器：最小化后后台完成、只提示新回复、请求数不变（见 C3 记录） |
| 跨标签页冲突 | coach-cross-tab-conflict（第二请求 409，不排队） |
| 停止清理 | coach-stop-cleanup（cancelled=1、slot=0、消息 3 条） |
| 90 天过期 | coach-retention-90d（可见 0、库内 2） |
| 聊天删除／账户删除 | coach-chat-deleted、coach-account-deleted |
| 来源和旧数据提示 | 来源：coach-sources-visible；“旧数据提示”是客户端固定文案，由 C3 组件回归覆盖 |

“收起完成”和“旧数据提示”没有对应的后端可观察量，不伪造回放通过；它们分别由 C3 的真实浏览器
演练与组件回归覆盖。这张对照表是 C4 勾选依据的一部分。

## 评估器新增能力

- `FaultSeeds.slow_coach_answer_seconds`：让生成确定性地慢下来，取消与单槽竞争才可重放。
- `FaultSeeds.oversize_coach_answer`：确定性超长输出，仍走真实 Runtime、安全与发布路径。
- `FaultSeeds.expire_coach_messages_at_step`：在第 N 步前把消息回拨，复现 90 天读取窗口。
- 观察项：`coach_cancelled`、`coach_failed`、`coach_slot_holders`、`coach_messages_with_sources`。
- `data.messages.length`：只允许观察条数，正文与任意字段仍被拒绝。
- `business_task_ref`：只投影 `kind`（`[a-z_]{1,40}`）与 `task_id`（`[A-Za-z0-9_-]{1,64}`），
  候选、预算、权限字段被丢弃；前端只渲染为不可点击文本。

## RED / GREEN 记录

- RED 1：声明新故障字段后 suite 被拒（`invalid evaluation suite`），证明旧契约不接受这些场景。
- RED 2：补故障后 15 个场景中 8 个 `case_error`，原因是 `data.messages.length` 当时不可解析。
- 修正：路径解析只对列表开放 `length`；删除聊天的期望从 2 条消息改为 1 条（答案未发布）。
- GREEN：15/15；随后新增 `coach-sources-visible`，16/16。
- 评估器测试：`backend/tests/task_evaluation/test_coach_conversations.py` **17 passed**；
  其中三个代表场景（边界、模型解释、停止清理）在隔离 worker 中真实重放并逐项比对 manifest 期望。

## 整体回归

2026-10-20 在隔离种子环境执行，全部为 mock，没有 live 报告，因此不做 Fake 与 live 的合并陈述。

| 组 | 命令要点 | 结果 |
| --- | --- | --- |
| 后端业务组 | `pytest backend/tests --ignore=backend/tests/test_config.py`，`DATA_DIR=.tmp/c4-seed-20261020b`，`SQLITE_DATABASE_PATH` 为空，`LLM_ENABLED=false` | **2237 passed / 0 failed**，1596.72s（26:36），报告 `.tmp/c4-full-20261020b.xml`（356 KB） |
| 配置独立组 | 同一解释器，**移除** `DATA_DIR`／`SQLITE_DATABASE_PATH`／`LLM_ENABLED` 后单独进程 | **6 passed**，报告 `.tmp/c4-config-20261020b.xml` |
| C4 专项 | `test_coach_conversations.py` + `test_coach_context_wiring.py` | **33 passed**（17 + 16） |
| 前端全量 | `vitest run` | **46 文件 / 299 passed** |
| 生产构建 | `tsc -b && vite build`，开关 true／false | 均通过；true 1,164.94 kB、false 1,148.84 kB |
| diff 检查 | `git diff --check` | exit 0，仅有既存 CRLF 提示，非空白错误 |

过程说明：首轮全量在磁盘写满时启动，pytest 收尾写 JUnit 报告抛 `OSError: [Errno 28] No space left on device`，
那一轮的数字不可用，也未据此勾选任何项。清理出空间后用新的 `--basetemp` 与新的种子目录完整重跑，
上表是重跑结果。重跑前后未修改任何产品代码。

未覆盖：真实模型质量、分布式 worker、进程重启续跑、定时物理清理调度。这些不在 C4 的通过范围内。

## 边界

- 默认前后端开关仍为 false；未提交、推送、合并或部署；未迁移正式库；未调用真实模型。
- 单进程单槽、无分布式 worker 协调、无定时物理清理、无进程重启续跑。
- 结构化卡片投影、S3 原子计划确认、真实模型质量仍属于 S3/S5 的验收范围。
- 真实 200% 浏览器缩放、OS 输入法、完整屏幕阅读器演练仍未取得可验证证据；C3 的缩放结论是
  指标模拟，不是物理快捷键。
