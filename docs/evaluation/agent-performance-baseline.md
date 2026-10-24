# 统一 Agent 性能基线（S4-A）

## 状态与边界

| 项 | 值 |
| --- | --- |
| 阶段 | S4-A1（闭合计量与来源指纹）、S4-A2（同引擎参考策略与配对基础）离线完成 |
| 分支 | `codex/s4a-measurement-baseline`（基于 `main` `8ef90a6`） |
| 运行日期 | 2026-10-23 |
| 运行模式 | `mock`（确定性脚本决策，拒绝网络） |
| 真实模型 | **未运行**。本文件不含任何 Provider 使用量、费用或提速百分比。 |
| 数据 | 合成 seed（`scripts/generate_sample_data.py`），无真实账户、无真实健康记录 |

**这份基线证明的是流程与计数成立，不是性能提升成立。** mock 的 token 数字是字符估算
（`token_measurement = mock_character_estimate`），不是 Provider 使用量；耗时包含子进程启动，
不是模型往返时间。

## 计量口径（S4-A1）

### token 来源

`backend/task_evaluation/measurements.py` 的 `UsageMeasurement` 只有三个合法来源：

| source | 含义 | total_tokens |
| --- | --- | --- |
| `provider` | Provider 返回的 usage | `input + output` |
| `mock_estimate` | 本地字符估算 | `input + output`（不是成本） |
| `unknown` | 没有测到 | `None` |

规则：`unknown` 必须三个字段全为 `None`，不允许"只测到一半"；`cached_input_tokens` 是
`input_tokens` 的子集，**不**计入 total；Provider 报 0 与没有报数是两个不同结果。

### 物理尝试闭合

每次工具/模型尝试在**操作真正开始之前**分配 `attempt_id` 并写 `TOOL_STARTED`，结束写
`TOOL_FINISHED`（带同一个 `attempt_id` 与 `usage_source`）。因此：

- 只进入队列不算开始；
- 缓存命中不新增 `TOOL_STARTED`（`AGENT_TOOL_DECIDED` 的 `cache_hits` 单独计）；
- 进程崩溃或被强杀时 `TOOL_STARTED` 没有配对终态，`runtime_metrics` 用 `attempt_id` 差集算出
  `attempts_incomplete`，**不会**把它当成"没调用过"。

报告同时给出 `attempts_started / attempts_finished / attempts_incomplete /
unknown_usage_count / known_total_tokens / usage_sources`，未知数量与已知小计并列显示。

### 指纹拆分

`config_fingerprints()` 把配置分成两组：

- **invariant**：引擎模式、会话开关、计划开关与存储模式、安全模式、语言与回答契约 —— 变了就是
  另一个实验，不能配对；
- **treatment**：`task_execution_strategy`、`context_policy_version`、预取/缓存开关 —— 变了正是
  要比较的东西。

`task_execution_strategy` 默认仍是 `reference`。**2026-10-23 的"新引擎默认开启"决定不改它**：
可见性开关与实验变量必须分开，否则 S4 失去对照对象。

## 场景集

`backend/task_evaluation/scenarios/performance_coach.json`，12 个场景：

| 场景 | 覆盖点 |
| --- | --- |
| `perf-quick-action` | 可信快捷动作（`explain_today`，动作名来自注册表而非问题文本） |
| `perf-open-task` | 开放任务，无确定性捷径 |
| `perf-first-training` | 首次训练建议：先发现 Skill 再读取 |
| `perf-followup` | 同一会话内追问 |
| `perf-zh` / `perf-en` | 中英同一形状 |
| `perf-long-history` | 三轮有效历史 |
| `perf-expired-history` | 过期历史在第 4 步被回填后过滤 |
| `perf-permission-denied` | 未授权领域查询被拒绝（`denials = 1`） |
| `perf-review-unavailable` | 必要审核不可用时草稿不泄漏 |
| `perf-cancel` | 取消释放槽位，下一轮仍成功 |
| `perf-retry` | 同 Idempotency-Key 重放不新建 turn |

S2 的 `interactive_entry.json` 继续单独统计（`task_kind=entry`），不与引擎成功率合并。

## 首次实测（mock / reference / cold / repeat=3）

命令：

```bash
python -m backend.task_evaluation.cli --mode mock --strategy reference --repeat 3 \
  --cache-state cold --suite backend/task_evaluation/scenarios/performance_coach.json \
  --output .tmp/task-evaluation/s4-coach-ref-<stamp> \
  --max-calls 600 --max-tokens 2000000 --max-seconds 1200
```

结果：**36 运行 / 36 通过**（12 场景 × 3 次），退出码 0。

| 场景 | 运行 | 通过 | 中位耗时 ms | 最小 | 最大 | 估算 token | 物理尝试 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| perf-quick-action | 3 | 3 | 613 | 601 | 617 | 3381 | 3 | 0 |
| perf-open-task | 3 | 3 | 619 | 614 | 651 | 3392 | 3 | 0 |
| perf-first-training | 3 | 3 | 677 | 670 | 965 | 5658 | 5 | 0 |
| perf-followup | 3 | 3 | 935 | 909 | 944 | 3040 | 2 | 0 |
| perf-zh | 3 | 3 | 544 | 537 | 600 | 1514 | 1 | 0 |
| perf-en | 3 | 3 | 543 | 530 | 610 | 1522 | 1 | 0 |
| perf-long-history | 3 | 3 | 1281 | 1234 | 1488 | 4583 | 3 | 0 |
| perf-expired-history | 3 | 3 | 875 | 848 | 1053 | 3088 | 2 | 0 |
| perf-permission-denied | 3 | 3 | 539 | 538 | 689 | 3162 | 2 | 0 |
| perf-review-unavailable | 3 | 3 | 545 | 542 | 583 | 0（未知） | 2 | 0 |
| perf-cancel | 3 | 3 | 2711 | 2682 | 2809 | 1540 | 1 | 0 |
| perf-retry | 3 | 3 | 564 | 562 | 604 | 1513 | 1 | 0 |

分组口径：`known_total_tokens = 101718`，`unknown_token_count = 3`（全部来自
`perf-review-unavailable`，该场景的 turn 失败所以没有估算值），`attempts_incomplete = 0`，
`unknown_usage_runs = 36`（mock 没有 Provider usage，如实记为 unknown）。

指纹：`invariant` 出现 **2** 个值 —— `perf-review-unavailable` 以 `safety_review_mode=enforce`
运行，其余为 `off`。这不是缺陷：它说明安全模式的改变会正确地把该场景排除在跨配置配对之外。

## 配对基础（S4-A2）

`pair_records(reference, optimized)` 的配对键是 `(case_id, version, repeat_index)`；配对成功后再
检查三项可比性，任一不符即**拒配并给出原因**：

| 原因 | 触发 |
| --- | --- |
| `mode_mismatch` | mock 与 live 混配 |
| `cache_state_mismatch` | 冷 reference 对热 optimized |
| `invariant_mismatch` | 引擎/数据/Skill/授权/审核配置不同 |
| `duplicate_reference` / `duplicate_optimized` | 同一槽位出现两次，双方一起丢弃 |

单侧缺失的用例进入 `unmatched`，不从分母里消失。`reduction_percent` 只在基线为正时给数，负数
表示退化；`paired_summary` 只用**双方都成功**的配对算延迟，失败配对单独计入成本侧。

## 配对实测：等价策略必须显示"没有收益"

同一天用同一套件跑了两侧（`--strategy reference` 与 `--strategy optimized`，各 3 次），
再用 `--compare` 只读配对：

```bash
python -m backend.task_evaluation.cli --compare \
  .tmp/task-evaluation/s4-coach-ref-20261023-2110 \
  .tmp/task-evaluation/s4-coach-opt-20261023-2110 \
  --output .tmp/task-evaluation/s4-coach-compare-20261023-2110
```

| 项 | reference | optimized |
| --- | --- | --- |
| 运行数 | 36 | 36 |
| 通过 | 36 | 36 |
| 平均耗时 ms | 897.9 | 1041.4 |
| 中位耗时 ms | 617.9 | 790.6 |
| 估算 token 合计 | 97179 | 97179 |
| token 未知运行 | 3 | 3 |

配对结果：`matched = 36`、`rejected = 0`、`unmatched = 0`，
`latency_reduction_percent = -15.98`，`token_reduction_percent = null`。

**这就是本阶段最重要的结论，而且是负面结论：**

1. 两侧的估算 token **完全相同**（97179），证明 A 阶段 optimized 与 reference 行为等价 ——
   没有偷偷少做事。
2. 同一份代码两次运行之间，延迟就出现了 **−16%** 的"下降"。这 16% 全是子进程调度与机器噪声，
   不是算法收益。任何只跑一次就宣称提速的报告都会在这里翻车。
3. `token_reduction_percent` 是 `null` 而不是 `0`，因为 `perf-review-unavailable` 在两侧都没有
   估算值。已知量不能吸收未知量。
4. 因此 D1 必须给出重复次数与区间（或明确写"样本不足、无区间"），并且正式 live 对照要在**同一
   授权批次内交替策略**执行，而不是先跑完一侧再跑另一侧。

## 本阶段不主张的事

- 没有真实模型提速、没有 token 节省、没有费用节省的结论。
- A 阶段的 `optimized` 与 `reference` **完全等价**：`REGISTERED_TRUSTED_ACTIONS` 为空，
  `plan_execution` 对 optimized 也返回 `use_shortcut=False`。任何"优化收益"都必须等 B1/C1/C2
  实现后，用同一授权批次里的交替策略实测。
- mock 的两次顺序运行不能用来声称控制了 Provider 抖动。
- `perf-review-unavailable` 的 0 token 是"未知"，不是"零成本"。

## 下一步

1. S3（Task 1–8）：类型 Patch、持久任务、候选工具、有限修订、原子确认。
2. S4-B1/C1/C2：上下文预取、权威依赖局部重算、有界缓存；每步先看冷/热实际收益。
3. S4-D1：同质量、安全配对报告与质量门禁；样本不足时明确写"无区间"。
4. S5：只有获得授权后，才在受控 live 链路里做真实探查与盲化标注。
