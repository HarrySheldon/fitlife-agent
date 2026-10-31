# S3/S4 审查修补记录（2026-10-30）

> 2026-10-31 状态校正：本文是当时验证快照，以下“未提交、未合并、未推送”已被集成取代。当前本地 main 为 f9e70fc，与缓存 origin/main 相同；本次未 fetch。本文最终验证尚待完成的结论仍保留，不以代码集成代替测试。后续待办统一见[当前验收清单](../superpowers/plans/2026-10-31-agent-delivery-status.md)。

范围：当前 `codex/s4a-measurement-baseline` 的 S3/S4 实现及未提交改动；不包含 S5、U7、RAG 升级、正式迁移、真实 Provider 调用或发布。既有未提交代码保留。代码未提交、未合并、未推送。

## 已实施修补

| 审查问题 | 修补位置与行为 |
| --- | --- |
| 上下文压缩丢约束 | context_policy 仅允许压缩 Skill 发现元数据，私有事实、计算证据和 Skill 正文保留 |
| 未知版本失效不传播 | task_dependencies 将未知版本和缺少历史的节点纳入失效闭包 |
| 统计量不一致 | comparison 对完整配对重采样，点估计和区间均为均值耗时比 |
| 无审核被标记已审 | 无 reviewer 不写审核证明；enforce 在 Runtime 预算内审核，成功前不可确认；新证明前缀不信任旧错误标记 |
| 修订状态未入模 | 后置 task_state 含可信阶段、轮次、待修域和持久 violations，实际调用前复验版本 |
| 无差异可确认 | 由原始基准和候选计算 old/new；前端展示来源及具体差异，无差异数据不允许确认 |
| 必要限制无法补充 | 共用 Dialog 提交受控 answers，支持等待、作答、再次显式执行 |
| 两入口及恢复缺口 | Coach 与计划页使用同一 Dialog/API，增加认证 owner 的任务列表和 GET 恢复 |
| 幂等不完整 | 不透明 UUID 操作键；未知创建结果保留账号隔离的指纹/键；execute 在单槽内持久 claim，同 key 不重复执行 |
| 复审边界 | 关闭/卸载/换账号使旧请求失效；候选过期后不能再审或发布 receipt |
| 生命周期导出 | 账户导出包含本人未过期任务、轮次、候选与回执；既有删除路径覆盖同一回执表 |

新增回归集中在 `backend/tests/test_plan_closeout_regressions.py`、依赖/上下文/性能测试及前端 Dialog/Card 测试。

## 验证证据与边界

- 首次完整后端：2691 passed、1 skipped、1 failed，1113.79 秒；唯一失败为账户导出文件列表未包含新增 `plan-tasks.json`。该契约已修正，不能将首次全量写成全绿。
- 前端中间完整回归：48 文件、317 测试通过，构建通过；此后又补窗口生命周期和未决创建键修补，最终结果须以新回归为准。
- 初始4项修补回归通过；后续新增候选期限、旧证明与实际审核预算、执行失败重放测试，待最终回归记录。
- 后续定向后端103项通过；新增7项收尾回归全部通过，包含真实 collect_review/Runtime 工具记账、过期候选与旧证明处理。
- 最新前端全量为317 passed、1 failed，失败在既有 SmartEntry.mixedTraining 的确认时序断言；未将其当作通过，正在限制并发后复验。此次未运行到构建步骤，前一次构建通过仅作历史。
- 沙盒内出现临时文件权限/无响应，相关测试已申请在沙盒外运行；所有业务数据均为独立合成目录，无真实密钥或正式库操作。
- 原有 Windows 符号链接权限 skip 和构建大分块警告保留，不计为行为通过或本次新增缺陷。

## 当前交付状态

限制前端测试并发（`npm --prefix frontend test -- --maxWorkers=2`）后，48 文件、318 项全部通过；不隐去此前默认并发失败的记录。两路独立只读复审已确认其发现关闭。

S3/S4 的上述修补已写入代码，**最终验证与进度收口尚待完成**。不以测试数量替代计划覆盖；S5 真实质量/性能证据、U7 默认启用与 legacy 退役仍未完成。缓存保持默认不启用，不宣称真实提速或安全无漏洞。浏览器人工完整验收不冒充已完成。

## 2026-10-31 最终验证补充

补充[当前验收清单](../superpowers/plans/2026-10-31-agent-delivery-status.md) A 节的未完成项。以下为本轮实际执行的命令与结果，不改写此前记录。

**环境**：`main` / `f9e70fc138ad7ea067df33976c4743fb5520bd23`（与 `origin/main` 相同）；Python 3.13.12；pytest 9.1.1。开始时工作区仅含 8 项文档改动（2 份新计划 + 6 份计划修订），**无代码改动**。所有业务数据为独立合成目录，未访问真实 Provider、真实密钥或正式库。

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量业务 | `.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider --basetemp=.tmp\final-full` | **2701 passed, 1 skipped, 1 warning, 1638.95s, exit 0** |
| 独立配置组 | 单独进程，先 `Remove-Item Env:DATA_DIR/SQLITE_DATABASE_PATH/LLM_ENABLED/OPENAI_API_KEY`，再 `pytest backend/tests/test_config.py -q` | **6 passed, 3.51s, exit 0** |
| 前端测试 | `npm --prefix frontend test -- --maxWorkers=2` | **48 文件 / 318 项通过, 44.28s, exit 0** |
| 前端构建 | `npm --prefix frontend run build` | **通过, exit 0**；保留既有「chunk > 500 kB」警告，不计为行为通过 |

首次集成前的 `2691 passed / 1 skipped / 1 failed` 保留原样：该失败（账户导出缺 `plan-tasks.json`）已由 `1b9527e` 修正，本轮全量是修正后的结果，两者不可拼接为同一次运行。

### 任务评估场景回放（mock，合成数据）

先核 `--help` 取得真实参数（`--mode/--suite/--output/--strategy/--repeat/--cache-state/--compare`），未沿用不存在的参数。输出目录 `.tmp/task-evaluation/20261031-142311`。

| 场景文件 | 运行 / 成功 | 退出码 |
| --- | --- | --- |
| `baseline.json` | 6 / 6 | 0 |
| `interactive_entry.json` | 8 / 8 | 0 |
| `plan_adjustment.json` | 12 / 12 | 0 |
| `coach_conversations.json` | 16 / 16 | 0 |
| `unified_coach.json` | 28 / 28 | 0 |

报告把模型版本如实记为 `unknown`，并标注 tokens 为字符估算、非 Provider 用量或付费成本。

### 配对性能对照（同一代码、相同不变量）

两臂均以同一 `f9e70fc` 执行，仅 `--strategy` 不同；各自保留报告后用 `--compare` 配对。

| 套件 | 配对 / 双方成功 | 质量门禁 | 延迟下降 | 95% 区间 | 判定 |
| --- | --- | --- | --- | --- | --- |
| `performance_plans.json` | 8 / 8 | 通过 | **-10.02%** | [-17.35, -3.48] | **退化**（负数为退化） |
| `performance_coach.json` | 12 / 12 | 通过 | 1.76% | **[-1.87, 5.00]** | **区间跨零，不构成收益** |

质量门禁在两套件均报 `unauthorized_access=0`、`duplicate_writes=0`、`invalid_activations=0`、`regressions=[]`：**安全不变量未被牺牲**，但也**没有换到可辩护的提速**。`performance_plans` 的 token 下降为 0.00%（两侧 75718）；`performance_coach` 的 token 与成本为 `null`（未知用量不作零处理）。

**结论必须照此表述**：本轮未测出优化策略的可靠收益——计划套件是退化，教练套件的区间跨零。因此**缓存与重排继续保持默认不启用**，不写入任何提升百分比，也不据此调整默认路径。若后续要在真实 Provider 上验证，须按交付清单 C 节单独取得授权。

### 仍然未完成（不由本轮勾选）

- **浏览器人工演练**：Coach／计划页创建并恢复同一任务、补充约束、查看具体差异、确认与冲突、断线后未知结果重试、关闭重开与换账户隔离，以及焦点、滚动、缩放、输入法项。单元测试不替代人工验收，本轮未执行、未冒充完成。
- S5 真实模型质量与性能证据、U7 默认启用与 legacy 退役、RAG R0–R4：见交付清单 B/C/D 与 RAG 计划。

## 2026-10-31 S5 工程交付补充

补充交付清单 B 节。范围**仅离线工程**：未调用真实 Provider、未迁移、未发布。

**环境**：同一 `main` / `f9e70fc`；Python 3.13.12；pytest 9.1.1。所有数据为独立合成目录。

### Task 1：离线准入、风险场景与标注协议

| 交付 | 位置 |
| --- | --- |
| 准入类型与校验 | `backend/task_evaluation/acceptance.py`：`EvaluationBudget`（三项严格为正）、`AcceptanceManifest`（`synthetic_only` 只能为真）、`ActualState`（本地重算）、`Authorization`（操作者构造，不由 manifest 自签）、`admit_live` |
| CLI 离线 dry-run | `--admit-manifest/--admit-actual/--admit-authorization`：只校验，构造 Provider 次数为 0，拒绝时只输出受控原因码 |
| 风险场景 | `backend/task_evaluation/scenarios/safety_boundary.json`，**6/6 通过**，退出码 0 |
| 标注协议 | `docs/evaluation/agent-annotation-guide.md`：双人盲标、第三人裁决、缺失记 `unknown` 且不进准确率分子 |

TDD 记录：先建接口（未加 `gt=0`）→ RED 为 `DID NOT RAISE`（4 项，非模块缺失）→ 加约束 → GREEN。

风险场景覆盖并区分：可分离混合任务（拒股票、照常答训练）、不可分离混合（澄清且 `gateway_attempts=0`）、正常否定描述（"我不想吃鸡胸肉"不是注入）、正常业务含"代码"（"写代码久坐"）、正常"今天练胸"、不可能计量单位（未确认则零写入）。既有套件覆盖的类别（直接/间接注入、他人数据、跨域、超长输出、健康边界、离题）**复用未重写**。

一处自我修正：`boundary-mixed-ambiguous` 最初断言 `coach_boundary_replies=1`，实测为 0——它使用独立的 `clarification` 消息而非 `out_of_scope`。改为断言真实不变量（零模型调用），不是削弱断言。

### Task 2：Gateway 边界与物理 attempt 计量

`backend/task_evaluation/live_gateway.py`，18 项测试：

- 唯一允许顺序 `admission() → factory() → attempt 在预留内`；准入失败时 factory **零调用**；
- factory 失败**不伪装**为准入失败；
- 预留被拒则 attempt **不启动**；attempt 抛异常**仍结算**；`usage=None` **保留全额预留**；
- 消息白名单仅 `generation/structured/decision/review`（无 `file_path`、无任意 Python）；
- `FakeGateway` 覆盖四边界，超时记 `failed`、取消记 `cancelled`；准入被拒时 **attempt 数为 0**（"从未调用"可由账本证明）；
- 批次超时仍写 partial 报告且不丢弃未跑案例。

父进程预算账本沿用既有 `BatchBudget` IPC，未新增第二套。

### Task 4 离线：演练与手册

- 新增 `docs/release/controlled-rollout.md`：备份与 integrity 校验、六步发布门禁、开关演练、故障/隐私演练清单、回退步骤、未授权事项。
- 手册记录**实测默认值**：`coach_agent_mode` 仍为 `legacy`、`plan_storage_mode=file`、`task_execution_strategy=reference`、`safety_review_mode=off`。**不得声称统一教练已默认开启。**
- 复用既有覆盖（确认重放、head 冲突、导出/删除/TTL、超时/取消、约束更新）共 **111 passed**，退出码 0。
- 新增 `docs/evaluation/2026-10-31-delivery-statement.md`：规定"问题→技术→结果→证据"表述与三类状态（离线完成 / live 待授权 / 迁移发布待授权），并列出必须声明的能力边界。

### 最终门禁

| 项 | 结果 |
| --- | --- |
| 后端全量 | **2758 passed, 1 skipped, 1113.22s, exit 0** |
| 前端测试 | **48 文件 / 318 项通过, 68.61s, exit 0** |
| 前端构建 | **通过, exit 0**（保留既有 chunk>500 kB 警告，不计为行为通过） |

### 本轮新增的已知缺口（未掩盖）

`早餐：白饭 100kg` 被换算为 `100000 g` / `182000 kcal`，`issues` 为空，**无任何单位告警**。未自行加营养或医学阈值（需经评审的领域判断）。已写入标注协议第 5 节，标注时记 `wrong_unit` 次要标签与 `unknown` 主标签。

### 仍未完成

C 节真实效果验收（需模型、脱敏场景、预算与质量判定规则授权）、D 节默认入口切换与 legacy 退役、正式迁移与扩大上线、浏览器人工演练、RAG R0–R4。
