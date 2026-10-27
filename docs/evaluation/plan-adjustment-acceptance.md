# 计划调整任务：S3 回放与交付证据（2026-10-27）

本文件记录 S3 Task 8 实测到的内容，不写未测到的结论。回放全部在独立合成 SQLite 的
spawn worker 中执行，Mock 决策脚本化、网络阻断、不接触正式数据、不迁移、不启用、不提交。

## 结论

- `backend/task_evaluation/scenarios/plan_adjustment.json` 声明的 12 个场景在本次代码树上
  **12/12 通过**（`exit=0`，`total_runs=12`、`total_successes=12`）。
- 判分依据是候选、约束、轮次、head 与 receipt 的持久状态，不是模型的一段"已完成"文本。
- 顶层 `model_version` 记为 `unknown`：只读场景 0 次模型调用，没有可归并的模型版本；
  其余 11 个场景记录为 `deterministic-eval-v1`。按既有约定，缺失不记 0。
- 这只证明离线回放边界，不证明真实模型质量、安全充分性或生产可用性；live 与部署不在本阶段。

## 代码与输入版本

| 项目 | 值 |
| --- | --- |
| `git_sha` | `68b2f143d2a1d17fe34e4aa449e22f392c61385a`（HEAD；S3 改动仍在工作树，未提交） |
| `workspace_diff` | `d998bd337fea35cb0ed361216f08be43f82912e40a556ec122c3b6d61bf9d0ac` |
| `config_fingerprint` | `f722d646c7050d4249b1fd68815f187ee4aabaaa0497631db917f3b6c6ab610b` |
| `rule_version` | `fitlife-safety-v1` |
| suite | `backend/task_evaluation/scenarios/plan_adjustment.json`（`schema_version=1`，12 个场景，均 `requires=["plan_adjustment"]`） |

`git_sha` 与 `workspace_diff` 由本次 CLI 运行自身写入报告，是本文件引用的事实。`workspace_diff` 只覆盖
`backend/**` 下的 `.py`/`.json`/`.yaml`/`.md`/`.txt`（排除 `data` 与 `__pycache__`），所以本文件在运行之后
撰写不会改变该指纹所描述的可执行代码。

整套 suite 跑过两遍：`2026-10-26`（`.tmp/task-evaluation/s3-20261026-1910`，`workspace_diff`
`0b792f6a…`）与最终代码树上的 `2026-10-27`（`.tmp/task-evaluation/s3-20261027-1346`，`d998bd33…`）。
两次的 12 行不变量逐字段相同（下表的数字全部来自后一次）；中间只改过注释与一处调试度量的回退，
`workspace_diff` 因此变化，行为没有变化。此处记录两个指纹，避免用旧指纹描述新代码。

计划把 `backend/task_evaluation/report.py` 列入待改文件，实际未改动：`RunRecord.details` 是透传字典，
`plan_invariants` 随 `to_run_record` 写入即已进入 `report.json`（已核对报告中的 `details.plan_invariants`）。
无改动需要，故不留空改动。

## 运行命令

```powershell
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest backend/tests/task_evaluation/test_plan_adjustment.py `
    backend/tests/domain/test_plan_adjustment.py backend/tests/test_plan_adjustment_service.py `
    -q --basetemp=C:/Users/HarrySheldon/AppData/Local/Temp/wb-t8/green-3
& $taskPython -m backend.task_evaluation.cli --mode mock `
    --suite backend/task_evaluation/scenarios/plan_adjustment.json `
    --output .tmp/task-evaluation/s3-20261027-1346 `
    --max-calls 400 --max-tokens 1000000 --max-seconds 900
```

产物：`report.json`、`report.md`；轮次轨迹由 `.tmp/record_traces.py` 另存为 `traces.json`（两条轮次轨迹
与同轮恢复轨迹）。退出码 `0` 表示全部场景通过且清理完成，不等于报告文件存在。

`--basetemp` 指向 C 盘是因为 D 盘在本次任务中一度为 0 字节可用（测试 basetemp 累积约 16 GB），
与代码无关；换盘只影响临时目录位置，不影响任何被测路径。

## 12 个场景的实测结果

`rounds`＝已占用轮次数，`indices`＝实际被认领的轮次编号，`cand`＝候选数，`act`＝激活数，
`head`/`hist`＝激活后的 head revision 与计划历史条数，`same`＝两版候选间未改动的领域（深比较），
`tgt`＝受保护目标未变，`authz`＝授权检查次数。`–` 表示该键**不存在**（候选不足两版，或没有可比对的
基线计划），不是 `false`：缺事实和"事实为否"必须能分开。

| 场景 | 调用 | rounds | indices | cand | act | head | hist | same | tgt | authz | 终态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `plan-task-training-only` | 5 | 0 | `[]` | 1 | 1 | 2 | 2 | – | true | 20 | activated |
| `plan-task-diet-only` | 5 | 0 | `[]` | 1 | 1 | 2 | 2 | – | true | 20 | activated |
| `plan-task-cross-domain-refused` | 5 | 1 | `[1]` | 1 | 0 | 1 | 1 | – | – | 20 | repairing |
| `plan-task-read-only-no-grant` | 0 | 0 | `[]` | 0 | 0 | 1 | 1 | – | – | 0 | collecting |
| `plan-task-first-candidate-passes` | 5 | 0 | `[]` | 1 | 1 | 2 | 2 | – | true | 20 | activated |
| `plan-task-two-rounds` | 9 | 2 | `[1,2]` | 3 | 1 | 2 | 2 | `["training"]` | true | 36 | activated |
| `plan-task-rounds-exhausted` | 9 | 2 | `[1,2]` | 3 | 0 | 1 | 1 | `["training"]` | true | 36 | awaiting_user_decision |
| `plan-task-goal-conflict-asks` | 7 | 2 | `[1,2]` | 3 | 0 | 1 | 1 | `["training"]` | true | 28 | awaiting_user_decision |
| `plan-task-stale-head-refused` | 5 | 0 | `[]` | 1 | 1 | 2 | 2 | – | true | 20 | activated |
| `plan-task-confirm-replay` | 5 | 0 | `[]` | 1 | 1 | 2 | 2 | – | true | 20 | activated |
| `plan-task-same-round-recovery` | 8 | 1 | `[1]` | 2 | 0 | 1 | 1 | `[]` | true | 32 | awaiting_confirmation |
| `plan-task-unauthorized-and-forged-confirm` | 5 | 1 | `[1]` | 1 | 0 | 1 | 1 | – | – | 20 | repairing |

整批估算 token 98642（Mock 字符估算，不是 provider 用量或成本）。

## 两条轮次轨迹

`plan-task-two-rounds`（步骤：创建 200 → execute 200 → GET 200 → answers 200 → execute 200 → execute 200 → execute 200 → confirm 200）：

| 阶段 | 观察 | 含义 |
| --- | --- | --- |
| 首次 execute | `stopped=awaiting_user_decision`，`missing=2` | 训练改动缺少 action_restrictions，候选未记录，先问用户 |
| answers | `missing=0` | 两个澄清被写入任务快照，状态回到 generating |
| 第 1 版候选 | `r0_state=repairing`，`r0_failed=["diet","training"]` | 只改了饮食的一餐，两个领域都仍不合格 |
| 第 2 版候选 | `r1_failed=["diet"]` | 只修训练，饮食仍不合格 |
| 第 3 版候选 | `state=awaiting_confirmation`，`rounds=2`，`failed=[]` | 只修饮食，训练保持上一版字节 |
| confirm | `confirmed_head=2` | head 由 1 推进到 2，写入一条激活 receipt |

`plan-task-rounds-exhausted`：同样两条失败轮之后，第 3 版候选仍含过敏原，第 5 次 execute
（前 4 次已经用掉初次尝试与两轮修复）直接落 `awaiting_user_decision`（`exhausted_rounds=2`），
整批调用数停在 9，没有第 4 次模型调用。

`plan-task-same-round-recovery`：第 1 次修复预留轮次 1 后，下一次运行只说了结束语、没有提交，
随后一次运行仍复用轮次 1（`indices=[1]`，2 版候选、1 个轮次），说明"重连不重复认领轮次"。

## 正式写入的深比较

`plan_domains_unchanged` 比较的是 `plan_candidate_submissions.candidate_json` 最近两行的领域根节点，
不是同一段代码写出的 digest；`plan_targets_unchanged` 比较 `plans.plan_json`（任务基线）与最新候选的
`daily_calorie_target`、`daily_protein_target`、`weekly_training_days`、`rest_days`。

- `plan-task-two-rounds`：`["training"]` —— 修饮食的那一轮没有改写训练。
- `plan-task-rounds-exhausted`、`plan-task-goal-conflict-asks`：`["training"]`，且 `targets=true`，
  即连续失败的两轮里训练字节未动、热量目标从未被候选改写。
- `plan-task-same-round-recovery`：`[]`，两版候选都同时改了训练与饮食，这是该场景预期的形状。

## 判分口径

- 候选合格由 `passed`、`failed_domains`、`violations` 决定；激活由 `plan_heads.revision`、
  `plans` 历史条数与 `plan_activation_receipts` 决定。报告里没有任何"计划已生效"的散文证据。
- `score_state` 对 `answer`/`answer_markdown`/`body`/`message`/`text`/`reason`/`summary`/`question`/
  `instructions`/`plan_document`/`constraints` 这些键直接抛 `ValueError`：散文不能作为判分依据。
- 任务级事实（`plan_domains_unchanged`、`plan_targets_unchanged`）只在账号恰好有一个任务时给出；
  0 个或多个时该键缺席，期望它的场景会失败，而不是匹配到错误的行。

## 观察白名单

可观察的量只有有界整数、布尔、摘要、封闭枚举列表与领域列表：`plan_tasks`、`plan_task_states`、
`plan_rounds`、`plan_round_indices`、`plan_candidates`、`plan_activations`、`plan_head_revision`、
`plan_history`、`plan_domains_unchanged`、`plan_targets_unchanged`、`plan_authorize_checks`、
`plan_authorize_denials`，加上响应里的 `state`/`repair_rounds`/`failed_domains`/`violations.length`/
`candidate.digest`/`head_revision`/`replayed`/`missing_constraints.length`。

计划正文、约束取值与 `violations.0.code` 都不可观察：它们要么是用户数据，要么是自由文本。
`data.task.candidate`、`data.task.constraints.available_equipment`、`data.plan.workout_plan.days.0.focus`
一类的路径会在单测里被拒绝（`backend/tests/task_evaluation/test_plan_adjustment.py`）。

## 授权计数

`plan_authorize_checks` 是 `ToolExecutor._domains` 被调用的次数（spy 在 worker 内替换），不是"工具清单看起来是闭的"。
本次实测：只读场景 0 次（从未进入模型）；单轮场景 20 次；两轮场景 36 次；目标冲突 28 次；
同轮恢复 32 次。`plan_authorize_denials` 全部为 0 —— 这些场景里没有撤销授权，撤销路径由
`unified_coach` 的回放与 `test_plan_adjustment_coach_handoff.py` 覆盖。

"精确计数"这条断言放在单测（`test_the_authorization_spy_counts_checks_and_denials`：两次检查 →
`{"checks": 2, "denied": 0}`，撤销后一次 → `{"checks": 1, "denied": 1}`）。场景里只有
`plan-task-training-only` 断言 `plan_authorize_denials == 0`；把 20/36/28 这类次数写进场景会把证据
钉在决策脚本的行数上，改一句提示词就整批变红，却说明不了授权语义；语义本身由单测用精确值锁住，
场景只负责"整条链路真的走了这么多检查"。上表列出的次数是实测值，不是断言。

## 哪些结论来自回放、哪些来自单测

回放（本文件上表）：

- 训练单改、饮食单改、跨域许可拒绝、只读不授权修改、首次联合合格、R1 两域/R2 单域、两轮仍失败、
  目标冲突停止、非当前 head 拒确认、同 key 重放、同轮恢复、越权读取与伪造确认被拒。

单测（不在本 suite 内，另由目标测试保证）：

| 断言 | 位置 |
| --- | --- |
| 取消后不可再执行 | `test_plan_adjustment_service.py::test_cancel_is_terminal` |
| 候选被旧 head 推走（跨任务、head 真被推进） | `test_sqlite_plan_activation.py::test_a_candidate_reviewed_against_an_old_head_is_refused` |
| digest 不符、候选过期、越权领域 | `test_sqlite_plan_activation.py` 同名用例 |
| 两进程不能同时确认同一 head、不能同时抢最后一轮 | `test_sqlite_plan_activation.py::test_two_processes_cannot_both_confirm_the_same_head`、`test_plan_task_repository.py::test_two_processes_cannot_both_take_the_last_round` |
| 删除账户后不能复活计划、只删本人行 | `test_sqlite_plan_activation.py::test_a_confirmation_after_deletion_cannot_resurrect_a_plan`、`test_plan_task_repository.py::test_delete_user_data_removes_every_row_for_that_owner_only` |
| 任务过期、候选过期 | `test_plan_task_repository.py::test_expired_task_reads_as_expired_and_refuses_writes` |
| 入口开关关闭仍可读旧任务 | `test_plan_adjustment_api.py::test_the_entry_can_be_switched_off_without_hiding_existing_tasks` |
| Reviewer 故障不发布候选、策略收紧后要求复审 | `test_plan_adjustment_service.py::test_an_unavailable_reviewer_publishes_nothing`、`test_confirm_requires_a_review_when_the_policy_tightens` |
| 计划轮与教练轮共用单槽 | `test_plan_adjustment_api.py::test_a_round_may_not_run_beside_a_coach_turn` |
| 文件存储不能确认 | `test_plan_adjustment_api.py::test_the_default_wiring_cannot_confirm_on_a_file_store` |

## 本轮发现并修复的证据链缺陷

首次整批运行时 `plan-task-two-rounds` 的 `r0_failed` 只有 `["training"]`，即饮食领域在仍含
"花生酱三明治"时被判合格。原因不在业务校验：`seed_plan_constraints` 先写入声明里的过敏清单，
随后 `activate_sqlite_plan_store` 执行的旧数据导入又把账号 `user_profile.json`（新注册账号为空）
写成更新的一个过敏版本，于是任务被冻结在"已验证无过敏"上。

修法：把过敏版本单独拆成 `seed_plan_safety`，在旧数据导入之后重新写入，让场景声明的取值成为最新版本
（`backend/task_evaluation/seeding.py`、`backend/task_evaluation/worker.py`）。修前这套场景其实无法
发现任何饮食缺陷（过敏规则在回放里从不触发），`plan-task-two-rounds` 的 `r0_failed` 也因此只剩
`["training"]`；修后为 `["diet","training"]`，第 2 轮为 `["diet"]`。

## 失败样本

场景写错时报告长这样（首轮实测，非产品缺陷）：

```
failed       plan-task-two-rounds                             10.3s failures=('unexpected_status',)
   observed: {"stopped": "repairing", "start_state": "generating"}
   facts: {"plan_candidates": 1, "plan_rounds": 1, "plan_round_indices": [1],
           "plan_activations": 0, "plan_head_revision": 1, "gateway_attempts": 3}
   steps: [('plan-adjustment-tasks', 200), ('execute', 200), ('{task}', 200), ('answers', 409)]
```

`answers` 返回 409 而不是 200：首轮提交修好了唯一可修的领域，任务进了 `repairing` 而不是
`awaiting_user_decision`，没有可回答的问题。这类失败以 `unexpected_status` + 步骤状态呈现，
和"候选被判不合格"（`failed_domains`/`violations` 有值）能区分开。

另一类失败是 `case_error`：声明的 observe 路径在响应里不存在（例如 `candidate` 为 null 时观察
`candidate.digest`）。它不产生 observed/facts，说明失败发生在读取响应，而不是业务判定。

## 完整门禁（同一代码树，分别记录，不相加为"总覆盖"）

| 门禁 | 结果 | 说明 |
| --- | --- | --- |
| 目标测试（Task 8 GREEN） | **93 passed，110.61 秒，退出码 0** | `test_plan_adjustment.py` + `domain/test_plan_adjustment.py` + `test_plan_adjustment_service.py` |
| 后端全量 | **2596 passed / 1 skipped / 1 warning，1544.81 秒，退出码 0** | `pytest backend/tests -q`；skip 见下 |
| 独立配置组 | **6 passed，2.44 秒，退出码 0** | `backend/tests/test_config.py` 单独进程，`DATA_DIR`/`SQLITE_DATABASE_PATH`/`LLM_ENABLED`/`OPENAI_API_KEY` 覆盖已移除；JUnit `.tmp/t8-config.xml` |
| 前端单测 | **48 文件 / 313 测试通过，79.66 秒** | `npx vitest run` |
| 前端生产构建 | **通过，27.64 秒** | 保留既有"分块 >500 kB"警告，非本次引入 |
| Mock suite | **12/12，退出码 0** | 见上表 |

唯一 skip 是 `backend/tests/unified_coach/test_skill_catalog.py` 的符号链接用例：
Windows 账户没有创建链接的权限（`Windows symlink creation privilege unavailable`）。
这是平台限制，不是被测行为通过，也不改写为通过。唯一的 warning 是既有的
Starlette/httpx 弃用提示。

## 未覆盖与限制

- 本 suite 里"旧 head 拒确认"用的是**非当前 head**（提交 head=2，当前为 1，返回 `PLAN_BASE_STALE`）。
  真正"head 被另一次激活推走"的跨任务形态由 `test_sqlite_plan_activation.py` 的单测覆盖，不在回放里。
- `plan-task-same-round-recovery` 的同轮复用发生在同一进程内的一次运行之后；跨进程重连复用由
  `test_plan_task_repository.py::test_repeated_reservation_does_not_spend_a_second_round` 覆盖。
- 全部为 Mock 决策脚本，没有真实模型调用；`model_version` 顶层为 `unknown`。
- `plan_adjustment_tasks_enabled` 默认 `True`（2026-10-23 用户决定"交付即默认开启"），前端计划页的
  任务卡片没有额外开关，因此本次回放对应的入口在部署里是可见的。教练侧的统一聊天入口
  （`coach_conversations_enabled`）仍默认 `False`，所以"从教练轮进入同一任务"这条路径在默认部署里
  不可达；它由 `test_plan_adjustment_coach_handoff.py` 与 `unified_coach` 回放覆盖，不在本 suite 里。
- `plan_storage_mode` 仍默认 `file`：存储源切换是数据迁移，不由"默认开启"推导。回放里显式切到
  `sqlite` 是因为文件存储无法 compare-and-swap head，不能确认候选。
- 本次没有迁移正式库、没有启用真实模型、没有提交以外的部署动作。合并代码前需再次备份保留主库；
  迁移与启用另需授权。
