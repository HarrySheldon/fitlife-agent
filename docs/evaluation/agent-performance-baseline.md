# 统一 Agent 性能基线（S4-A）

## 状态与边界

| 项 | 值 |
| --- | --- |
| 阶段 | S4-A1（闭合计量与来源指纹）、S4-A2（同引擎参考策略与配对基础）、S4-B1（受控预取与有界整理）、S4-C1（权威依赖与局部重算）、S4-C2（有界确定性复用，**默认关闭**）、S4-D1（同质量安全配对与门禁）离线完成 |
| 分支 | `codex/s4a-measurement-baseline`（基于 `main` `8ef90a6`） |
| 运行日期 | 2026-10-23（A1/A2）、2026-10-27（B1/C1/C2/D1） |
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

## S4-B1：受控预取与有界整理（2026-10-27）

B1 只做一件事，也只在一个动作上做：`explain_today` 这个快捷动作不再花一轮决策去发现唯一能回答它的
Skill。`backend/agent/context_policy.py` 是纯策略，不持有执行器、不发放授权。

### 封闭表

- `PREFETCH_TABLE` 只有 `explain_today → skill:today-explanation`。其余动作没有实测就没有条目，
  开放任务继续渐进发现。
- `trusted_action_of` 只接受注册表里的名字（`ACTION_REGISTRY ∪ ADVICE_REGISTRY`），并且要求页面意图
  可信（`trusted_page_intent` 为真且用户没在页面上自己写问题）。把 `explain_today` 打进问题框不产生
  任何预取；页面上带用户自己问题的动作也不算可信。
- 预取走 `ToolExecutor.prefetch` → 同一个 `resources.read`，所以 release digest、owner 检查、
  取消检查都是原来那一套。**标识可信不等于正文可信**：`SKILL.md` 在计划选定之后被改过，
  `RESOURCE_VERSION_CHANGED` 会终止整次运行，而不是把旧字节发出去。
- `include_verified_page_context` 现在恒为 `False`：`VERIFIED_PAGE_CONTEXT_KEYS` 为空，
  `PrefetchEntry` 在导入期就拒绝把它打开（`NO_VERIFIED_PAGE_CONTEXT_PRODUCER`）。页面投影是私有记录
  数据，在没有确定性的生产者与净化步骤之前，不因为"页面可信"就塞进 prompt。

### 实测（mock，同进程，脚本决策，无 Provider）

数值由同一条链路（`UnifiedCoachWorkflow` + 脚本网关）测得，取自 provider 实际会收到的
`AgentDecisionRequest`，不是本地拼接的字符串：

| 项 | reference | optimized |
| --- | --- | --- |
| 模型调用（`decision_count`） | 3 | 1 |
| 工具执行（`executions`） | 2（`skills.search` → `resources.read`） | 1（`resources.read`） |
| 每轮输入字符 | 5724 / 7523 / 8761 | 6849 |
| 输入字符合计 | 22008 | 6849 |
| 峰值字符 | 8761 | 6849 |
| 回答 | `今天的状态如何？` | `今天的状态如何？`（逐字节相同） |

带 3 条有效历史：22701 → 7080；带 12 条（上限）：24789 → 7776。历史没有因为预取而消失，只是不再需要被读两遍。

不变的部分由断言保证，不是由注释保证：`instructions` 相同、工具描述顺序相同、当前问题与 runtime
frame 的位置和内容相同、`max_output_tokens` 相同、zh/en × brief/detailed 四种组合回答相同、
无可信页面意图时 0 次读取。复现：`pytest backend/tests/unified_coach/test_context_policy.py -q`。

**为什么不在 `performance_coach.json` 上量这一对**：那些场景的决策是固定脚本，脚本永远会发出
`resources.read`，预取省下的那一轮在脚本里不存在。用固定脚本跑这一对会得到"optimized 多执行一次"
的假象。省下的东西是"模型不必再问"，只能在 provider 输入这一层观察。

### 有界整理

`organize_rear` 只在 optimized 侧生效，只在超出预算时生效，只动 `tool_data`，只从最旧的开始，
保留最近 2 条，**拒绝（`status=denied`）永不压缩**——拒绝携带硬限制，模型看不见的限制会被再试一次。
压缩后留下的是身份（`call_id` / `tool` / `source_version` / `required_domains`），丢的是正文；
证据仍从 `ToolExecutor.observations` 取，所以被压缩的那条照样能渲染出数字块
（`test_compaction_does_not_remove_evidence_from_the_answer`）。

**上面三组实测里整理一次都没触发**（峰值 8761 < 24000）。这条路径的证据只有单测，
不是这对场景跑出来的，不能读成"整理已在真实长度上验证过"。

### 配置与报告

`Settings.context_policy_version`（默认 `context-policy-v1`）与 `prefetch_enabled`（默认 `true`）
现在有真实取值，因此 `treatment_config_fingerprint` 不再记录两个 `null`。
`ContextPolicyConfig` 拒绝与代码不一致的版本号（`CONTEXT_POLICY_VERSION_MISMATCH`），
否则报告会把收益归给一个没跑过的策略。reference 侧无论 `prefetch_enabled` 是什么，都不预取、不整理。
`task_cache_enabled` 仍记为 `null`：C2 尚未实现，这里的 `null` 是"没有这个设置"，不是"关闭"。

### 门禁（同一代码树，2026-10-27）

| 门禁 | 结果 |
| --- | --- |
| B1 目标测试（本文件新增 + `test_context_builder` + `test_agent_loop` + `test_safety_guard_contract`） | **40 passed**，3.78s，exit 0 |
| 后端全量 | **2615 passed / 1 skipped**，1554.44s，exit 0 |
| 独立配置组（单独进程，清 `DATA_DIR`/`SQLITE_DATABASE_PATH`/`LLM_ENABLED`/`OPENAI_API_KEY`） | **6 passed**，1.83s，exit 0 |

唯一 skip 仍是 Windows 符号链接权限用例（`test_skill_catalog.py`），记为平台限制，不写成通过。
B1 没有前端改动，前端门禁未重跑。

## S4-C1：权威依赖与局部重算（2026-10-27）

`backend/domain/task_dependencies.py` 是一个**纯决策模型**：不存结果、不读仓库、不知道节点里装的是什么。
它只回答两件事——一个结果还能不能复用，以及一次改动应该让谁失效。

| 构件 | 语义 |
| --- | --- |
| `DependencyKey` | `scope` / `resource_id` / `resource_revision` / `constraints_revision` / `catalog_revision` / `processor_revision` |
| `key.reusable` | 四个版本号任一缺失即为 `False`；这种节点**重算**，不复用 |
| `graph_edges` | `parent → children`，失效传播的方向 |
| `affected_nodes` | 从改动点做 BFS；环不会死循环（每个节点只入队一次），未知节点不放大影响面 |
| `plan_recompute` | 逐节点判定，顺序固定：`explicitly_changed` → `revision_unknown` → `version_changed` → `upstream_changed` → `no_previous` → 复用 |
| `domain_reuse` | 计划任务的视图：`frozen` 哈希 vs `actual` 哈希，表达成同一套 `RecomputeOutcome` |
| `RecomputeOutcome.as_record()` | **只有计数与原因直方图**，不写节点标识符 |

三条被测试钉住的语义：

1. **改一个菜不能碰另一个菜**。面改粉/奶茶用例里，只有被改名的那一项重算；
   汇总节点因为读它而必须重算（`upstream_changed`），奶茶不在影响面里。
2. **字节变了就不能算"没改"**。冻结域的哈希与当前哈希不同时记 `version_changed` 并失效，
   而不是"没被点名所以复用"。这正是把过期数字发布出去的路径。
3. **没有权威版本就重算**。`catalog=''` 的键被判为 `revision_unknown`，而不是与旧键"相等"。

接线范围：`backend/agent/plan_adjustment/session.py` 在 `validation.evaluate(...)` 之后调用
`domain_reuse(frozen, actual, touched)`，结果写进 `submission["dependency"]`（计数 + 原因直方图）。
S2 侧没有新增缓存——`interactive_entry` 本来就是逐项解析的，
`backend/tests/test_s2_entry_dependencies.py` 用一个 `resolve_item` 探针**证明**了这一点
（改一个名字，只有那一项被重新解析），而不是再加一层"优化"。

门禁：`test_task_dependencies.py` + `test_plan_adjustment_service.py` +
`test_plan_adjustment_session.py` + `test_smart_entry_confirmation.py` + `test_s2_entry_dependencies.py`
= **56 passed**，48.97s，exit 0。

**这一节不主张提速。** C1 让"该重算什么"可判定且可复查，本身不减少一次模型调用；
它的收益只有在 S3 计划任务的轮次里才可能体现，而那需要 D1 的配对证据。

## S4-C2：有界确定性复用——建了，量了，默认不启用（2026-10-27）

`backend/infrastructure/agent_runtime/task_cache.py` 实现了 `TaskResultCache`，并把三条规则做成**结构性的**，
不是写在注释里的建议：

| 规则 | 实现 | 为什么 |
| --- | --- | --- |
| 先授权后命中 | `get()` / `remember()` 第一句就是 `authorize()` | 授权被撤销时，内存里有字节也不构成答案；miss 不是免费的存在性探测 |
| `None` 不是数据 | `put(key, None)` 抛 `CACHE_MUST_NOT_STORE_A_MISS` | 把临时失败存成成功数据，是它变成永久答案的方式 |
| 无版本不入缓存 | `put` 拒绝 `key.reusable is False`（`UNVERSIONED_KEY_MUST_NOT_BE_CACHED`） | 没有权威版本就没有可失效的锚点 |
| 写读都复制 | 两侧 `deepcopy`，先复制再入表 | 调用方改自己拿到的对象，不能改到别人的答案 |
| 到期用注入时钟 | `clock()` 决定 `expires_at`，测试直接推进 1 秒 | 不 sleep，不依赖墙钟 |
| 满了淘汰最旧写入 | 按 `written_at` 取最小；重写刷新排序 | 容量有界，行为确定 |

`scope` 由 `owner_scope()` / `task_scope()` 构造并校验：`task:<owner>.<task>`。
任务号在跨用户时不唯一，所以 owner 是 scope 的一部分；标识符里不允许出现分隔符，scope 不能由模型指定。
`NOT_APPLICABLE = '-'`（"这个依赖没有该输入"）与 `''`（"不知道"）是两件事，后者禁止复用。

测试：`backend/tests/infrastructure/test_task_cache.py` **30 passed**。

### 冷/热实测（同机、真实域对象、`timeit` 取 5 次最优；两次运行相差 <10%）

| 接缝 | 冷（真实计算） | 热（`get()`：authorize + 查表 + deepcopy） | 冷/热 |
| --- | --- | --- | --- |
| `catalog_signature`（返回 str） | 11.1 µs | 0.8 µs | 14.2× 更快 |
| `resolve_item`（返回 `EntryItem`） | 98.8 µs | 24.4 µs | 4.1× 更快 |
| `json.loads` 5883 B 候选文档 | 78.9 µs | 304.8 µs | **0.26×，慢 3.9 倍** |
| `json.loads` 18987 B 候选文档 | 275.6 µs | 933.0 µs | **0.30×，慢 3.4 倍** |
| `json.loads` 55584 B 候选文档（schema 上限 64 KiB） | 924.9 µs | 2738.6 µs | **0.34×，慢 3.0 倍** |

单看复制成本就很清楚：同一份 4581 B 文档，`deepcopy` **331 µs**，`json.loads` **184 µs**。
"复制一份再交出去"比"重新解码一份"更贵——所以对结构化值，缓存是**负优化**。

### 结论：默认不启用

`Settings.task_cache_enabled = False`，并且**没有接进任何请求路径**。理由分开写：

1. **收益太小。** 可缓存的两个确定性换算每次省 10 µs 和 74 µs。一个计划任务 8 个场景实测
   578–5808 ms，省下的是 0.001%–0.01% 量级，落在噪声里。
2. **结构化值是负优化。** S3 已验证候选文档是这条缓存最想服务的对象，实测反而慢 3–4 倍。
3. **S2 目录接缝在结构上不可缓存。** 食物行的身份是它自己的 `content_hash`，而拿到它必须先读这一行；
   用 `catalog_id` + 一个查不到的全局版本号做键，会被 `put` 直接拒绝。
   这不是"收益不够"，是"做不对"。

按计划原文处理：**保留代码的无缓存实现及局部重算，默认不启用**，不为简历加 Redis 或并行读。
`task_cache_enabled` 记 `False`（不是 `null`）：两侧都没有结果缓存，这是treatment 的事实，
而不是"未知"。

门禁：`test_task_cache.py` + `test_task_dependencies.py` + `test_account_delete_api.py` +
`test_plan_adjustment_service.py` + `test_measurements.py` = **107 passed**，89.79s，exit 0。
`test_account_delete_api.py` 在这一组里，是为了证明删除账号仍然清空全部数据——
缓存不存在，所以也没有需要按 scope 清理的残留。

## S4-D1：同质量、安全配对与质量门禁（2026-10-27）

`backend/task_evaluation/comparison.py` 现在除了配对，还要回答"这个数字能不能用"。

### 新增的可复查字段

| 字段 | 口径 |
| --- | --- |
| `paired_count` / `unmatched_count` / `rejected_pairs` | 分开计数；单侧缺失留在 `unmatched`，不进分母也不被删除 |
| `Distribution` | `count` / `minimum` / `maximum` / `p50` / `p95` / `method="nearest-rank"` |
| `latency_reduction_interval` | 逐配对下降率的百分位 bootstrap（1000 次，固定种子）；样本 < 8 时 `reason="insufficient_sample"` |
| `reference_cost_per_success` / `optimized_cost_per_success` | **双方全部已配对运行**的 token ÷ 成功数；任一 token 未知即 `null`；无成功即 `null` |
| `MeasurementCoverage` | `unknown_usage` / `unknown_usage_rate` / `incomplete_attempts` / `cleanup_failed`，与安全门禁分开报 |
| `QualityGate` | 三类安全计数（`unauthorized_access` / `duplicate_writes` / `invalid_activations`）+ 退化用例 + 单侧缺失 + 拒配 |

最近秩而不是插值：返回的延迟一定是某次真实运行观测到的值，可以从日志复现。

### 质量门禁怎么判定

安全事实来自场景**自己声明的期望**。`RunRecord.details["failed_fields"]` 现在记录"哪条声明没对上"，
门禁按封闭映射归类：`coach_unapproved_answers` / `coach_boundary_replies` / `denials` /
`plan_authorize_denials` → 越权；`confirmed_meals` / `confirmed_workouts` / `plan_history` → 重复写入；
`plan_activations` / `plan_head_revision` / `plan_task_states` / `violations` → 无效激活。
三类都出现在记录里，即使为 0——**零是测出来的，不是缺项**。

另外两条独立的拒绝理由：`quality_regression`（reference 通过、optimized 失败的用例，即使失败与安全无关）
与 `unmatched_case` / `rejected_pair` / `no_comparable_pair` / `no_successful_pair`。
样本不足**不是**门禁失败项，它削弱区间，不改变产品是否安全。

### S3 计划场景集

新增 `backend/task_evaluation/scenarios/performance_plans.json`，8 个场景，覆盖计划要求的分组：

| 类别 | 场景 |
| --- | --- |
| 单域 | `plan-task-training-only`、`plan-task-diet-only` |
| 联合 | `plan-task-two-rounds`（训练 + 饮食） |
| 局部修订 | `plan-task-same-round-recovery` |
| 目标冲突 | `plan-task-goal-conflict-asks` |
| 无解 | `plan-task-rounds-exhausted` |
| 过期 | `plan-task-stale-head-refused` |
| 撤销 | `plan-task-read-only-no-grant` |

场景正文与 `plan_adjustment.json` 中同名用例逐字一致，只取子集，不重写期望值。

### 实测（mock，两侧各 1 次，2026-10-27 19:22）

```bash
python -m backend.task_evaluation.cli --mode mock --strategy reference --repeat 1 \
  --cache-state cold --suite backend/task_evaluation/scenarios/performance_plans.json \
  --output .tmp/task-evaluation/d1-plans-ref-20261027-192234 --max-calls 600 \
  --max-tokens 2000000 --max-seconds 1200
# 同命令 --strategy optimized → d1-plans-opt-20261027-192234
python -m backend.task_evaluation.cli --compare <ref> <opt> --output <compare>
```

| 项 | reference | optimized |
| --- | --- | --- |
| 运行数 / 通过 | 8 / 8 | 8 / 8 |
| 已知 token 合计 | 70758 | 70758 |
| 每成功任务成本 | 8844.75 | 8844.75 |
| 延迟 P50 ms | 3628.53 | 2589.30 |
| 延迟 P95 ms | 5807.47 | 4574.01 |
| 延迟范围 ms | 578.11–5807.47 | 674.66–4574.01 |
| 候选耗时样本 | 0 | 0 |
| usage 未知 | 0 | 0 |

配对：`paired_count = 8`、`rejected_pairs = 0`、`unmatched_count = 0`。
门禁 **passed**：越权 0、重复写入 0、无效激活 0、退化用例无。
`latency_reduction_percent = 21.67`，区间 **[10.10, 31.34]%**（bootstrap 1000 次），
`token_reduction_percent = 0.00`。

**这 21.67% 不是收益，是漂移，而且这次有两条独立证据：**

1. **token 完全相同（70758 = 70758）**，逐用例也完全相同。两侧做的是同一件事。
2. **唯一没有工作的用例反向移动**：`plan-task-read-only-no-grant` 在 optimized 侧慢了 **16.7%**
   （578.1 → 674.7 ms），而这个用例 `gateway_attempts = 0`、token = 0，没有任何可优化的内容。
   一个"优化"不可能只在有工作时变快、在无工作时变慢。

这与 A2 那次"同一份代码两次运行差 −16%"是同一个现象。D1 的结论因此很具体：
**区间能挡住"样本太小"，挡不住"两次顺序运行把时间当成了策略"**。
正式 live 对照必须在同一授权批次内**交替**执行两侧，否则 21.67% 这种数字会被当成提速写进报告。

逐用例下降率（仅作漂移证据，不作收益）：15.7 / 34.3 / 33.1 / 28.4 / 11.0 / 10.1 / 20.2 / **−16.7** %。
`treatment_config_fingerprint` 两侧不同（`696cd4…` vs `664cd3…`），说明策略确实是变量；
`invariant_config_fingerprint` 两侧相同，所以 8 对全部配对成功。

### 门禁（同一代码树，2026-10-27）

| 门禁 | 结果 |
| --- | --- |
| D1 目标测试（`test_performance_acceptance.py` + `test_comparison.py` + `test_cli.py`） | **55 passed**，23.80s，exit 0 |
| 计划场景集 mock 回放（reference / optimized 各 8） | **8/8 与 8/8 通过**，exit 0 |
| 配对 + 质量门禁 | `--compare` exit 0，门禁 passed |

## 完整收口（2026-10-27，同一代码树）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `pytest backend/tests -q --basetemp=…/wb-close/full3` | **2691 passed / 1 skipped**，2130.81s，exit 0 |
| 独立配置组（单独进程，清 `DATA_DIR`/`SQLITE_DATABASE_PATH`/`LLM_ENABLED`/`OPENAI_API_KEY`） | `pytest backend/tests/test_config.py` | **6 passed**，1.95s，exit 0 |
| 前端测试 | `npm run test`（vitest） | **48 文件 / 313 tests passed**，78.72s |
| 前端构建 | `npm run build` | 通过，29.55s（2485 modules；`index-*.js` 1158.29 kB，体积告警是既有问题） |
| S3 计划回放 | `--mode mock --strategy reference --suite plan_adjustment.json` | **12/12 通过**，101792 估算 token，exit 0 |

唯一 skip 仍是 Windows 符号链接权限用例（`test_skill_catalog.py`），记为平台限制，不写成通过。
后端全量比 B1 记录的 2615 多 76 个，全部来自 C1/C2/D1 新增的用例。
后端全量连跑了两次（1547.47s 与 2130.81s，同为 2691 passed / 1 skipped / exit 0）：
**墙钟时间受机器负载影响，不作为性能证据**，这也是本文件只用 token 与决策轮次谈收益的原因。

**踩坑记录（会反复出现）**：`--basetemp` 的父目录不存在时，每个用例都在 setup 阶段报
`FileNotFoundError: [WinError 3]`，一次全量能刷出 2692 个 error，看起来像整棵树崩了。
跑之前先 `mkdir -p` 父目录。

## 本阶段不主张的事

- 没有真实模型提速、没有 token 节省、没有费用节省的结论。
- A 阶段的 `optimized` 与 `reference` **完全等价**：`REGISTERED_TRUSTED_ACTIONS` 为空，
  `plan_execution` 对 optimized 也返回 `use_shortcut=False`。B1 之后这句话只对"短路径选择"成立：
  `plan_execution` 仍然不选短路径，B1 改变的是**上下文组装**（预取 + 有界整理），
  而且只在一个已注册动作上。任何"优化收益"都必须在同一授权批次里用交替策略实测。
- B1 的 3 → 1 是**决策轮次**，不是 token 或耗时。mock 没有 Provider usage，B1 这一对也没有时间数字。
- D1 的 21.67% **不写成提速**：两侧 token 相同，且无工作的用例反向移动 16.7%。它是顺序运行的漂移。
- C1/C2 **都没有可观测的耗时收益**。C2 被量过之后默认关闭；C1 只让"该重算什么"可判定。
- S3 计划场景集的 `candidate_ms` 样本数为 0：`plan_adjustment` 不经过 coach 候选计时路径，
  所以这一列是"无样本"，不是"很快"。原先这些记录写 `candidate_reason = no_verified_candidate`，
  而同一份记录里 `plan_candidates = 1`——读起来像"没有候选"。D1 把该值改为 `no_timed_candidate`：
  它只说明"没有为候选计时"，不宣称候选是否存在。
- mock 的两次顺序运行不能用来声称控制了 Provider 抖动。
- `perf-review-unavailable` 的 0 token 是"未知"，不是"零成本"。

## 下一步

1. S3（Task 1–8）：类型 Patch、持久任务、候选工具、有限修订、原子确认。（已完成）
2. S4-B1：上下文预取与有界整理。（已完成）
3. S4-C1：权威依赖与局部重算。（已完成）S4-C2：有界确定性复用。（已实现并实测，**默认不启用**）
4. S4-D1：同质量、安全配对报告与质量门禁。（已完成；mock 下门禁与区间可用，真实对照待 S5）
5. S5：只有获得授权后，才在受控 live 链路里做真实探查与盲化标注；
   正式对照必须在同一授权批次内交替执行两侧策略。
