# Agent 当前交付与验收清单

## 2026-11-04 两项接入修补（开发分支）

2026-11-05真实模型验收交接已准备，见[完整命令与人工判定](../../evaluation/live-model-operator-guide.md)及[离线验证记录](../../evaluation/2026-11-05-live-evaluation-handoff.md)。操作者尚未执行真实批次，不勾选下文C节；教练hashing检索不算真实语义embedding验收。

`codex/live-evidence-integration` 已补CLI受控live运行链路与Agent最终回答引用校验/同run一次纠正，见[实施与验证记录](../../evaluation/2026-11-04-live-citation-integration.md)和[命令说明](../../task-evaluation-live.md)。相关离线回归605 passed、1 skipped；最终live定向12项通过；只读独立审查发现关闭。下文“live明确未启用”描述旧main基线，不再适用于该开发分支；分支尚未提交或集成。真实模型验收、U7及正式迁移/发布仍未执行。

核查日期：2026-10-31。代码基线：`main/f9e70fc`。本文件是当前进度入口，历史计划仍负责技术细节；新增证据应更新此表，不再通过叠加旧待办数量描述进度。本轮仅调整文档，未执行新测试、真实模型调用、迁移或部署。

## 状态规则

- **已集成**：实现存在于本地 main；不表示生产启用。
- **有历史验证**：存在明确命令/结果，但必须核对是否覆盖最新修补。
- **待最终验收**：不能用修补前全量通过、Mock或定向测试替代。
- **待实施**：后续工程任务；真实调用、数据迁移、发布分别取得授权。

## 三条 Agent 主线与证据

| 主线与问题 | 已集成机制 | 现有证据 | 未完成的证明 |
| --- | --- | --- | --- |
| 可信执行：注入、隐私过读、模型越权与正常任务误拒 | 封闭工具、可信授权、必要上下文、审核证明、用户确认后的业务事务 | U验收、S3定向回归、审查修补记录 | S5正常/对抗场景盲标；真实模型误拒及健康建议质量；不声称消除注入 |
| 可靠落地：多域约束失败、中断、重复执行与旧候选确认 | 类型候选、持久TaskSession、两轮共享修订、依赖失效、CAS、幂等回执、同源差异界面 | S3计划回放历史、7项修补回归、318项前端限并发回归 | 最新代码完整回归/场景回放；人工操作与生命周期故障演练 |
| 执行效率：多轮重复发现、重复计算和上下文膨胀 | 稳定前缀、渐进披露、可信预取、发现元数据压缩、依赖驱动复用、attempt/usage与配对报告 | S4历史基线及配对测试；压缩/失效/统计修补 | 最新配对离线回放；授权真实Provider对照；缓存继续默认关闭 |

统一Runtime/Adapter是工程底座。稳定前缀不等于已证明KV缓存命中；本地复用不等于模型token节省；Mock估算不等于Provider usage。当前可描述机制与能力，不填写未经验证的效果。

## A：S3/S4 最终收口（先执行）

- [x] S3 Task 1–8实现与审查修补集成main。
- [x] S4 A1/A2/B1/C1/C2/D1实现与审查修补集成main。
- [x] 复审发现关闭；保留独立验证边界。
- [x] 使用现有 `.venv\Scripts\python.exe -m pytest --version` 确认解释器，再以合成数据执行完整后端业务测试及独立配置组。记录SHA、dirty diff、环境、命令、exit及失败；不得把首次2691 passed/1 skipped/1 failed写成全绿。
  - 证据：`main`/`c3c7f14`，pytest 9.1.1 / Python 3.13.12，工作区干净。后端全量 **2890 passed, 1 skipped, exit 0**；独立配置组（单独进程清空四类环境变量）**6 passed, exit 0**。首次 2691/1 skipped/1 failed 保留在原文，未改写为全绿。
- [x] 重跑 `backend/task_evaluation/scenarios` 中计划、教练及性能适用场景；reference/optimized使用同一代码和相同不变量，分别保留报告后配对。先查CLI帮助及场景文件，不能沿用不存在的参数。
  - 证据：先核 `--help` 取得真实参数。baseline 6/6、interactive_entry 8/8、plan_adjustment 12/12、coach_conversations 16/16、unified_coach 28/28；性能两套件（plans 8 配对、coach 12 配对）质量门禁通过。**配对结果未测出可辩护提速**（plans -10.02% 退化，coach 区间跨零），故缓存与重排保持默认关闭。
- [x] 最新前端完整测试与构建。已有318项通过使用 `npm --prefix frontend test -- --maxWorkers=2`，需保留先前默认并发失败记录；本次文档修改不重新制造测试通过结论。
  - 证据：**318 项通过 / 48 文件**，`npm run build` 通过（25.87s，退出码 0）；既有 chunk>500 kB 警告保留，不计为行为通过。先前默认并发失败记录保留在 closeout 原文。
- [x] 浏览器演练：Coach/计划页创建及恢复同一任务、补充约束、查看具体差异、确认/冲突、断线后的未知结果重试、关闭重开和换账户隔离。补C3/C4未覆盖的焦点、滚动、缩放与输入法项，记录执行人与结果；单元测试不替代人工验收。
  - 证据：**用户本人执行并于 2026-10-31 会话内确认：8 项全部通过，未发现问题。** 边界如实记录于 closeout：这是用户确认而非本 agent 观察，**无逐项截图/日志留档**，可靠阅度低于自动化项。
- [x] 将新证据写入 `docs/evaluation/2026-10-30-s3-s4-review-closeout.md`，确认覆盖后才将本节未完成项勾选。
  - 证据：closeout 新增「2026-10-31 A 节收口补充（含人工演练）」一节，含自动化实测表、人工演练记录与证据边界、勾选依据。

历史：`docs/evaluation/agent-performance-baseline.md` 记录修补前完整通过；修补后证据位于上述closeout。二者适用代码不同，不拼接为一次成功运行。

## B：S5 工程交付（A通过后，离线准备可提前）

技术步骤沿用 `2026-10-10-agent-task-s5-acceptance.md`。

- [x] Task 1：离线准入清单、合成正常/对抗案例、人工标签及分歧复核协议。必须包含正常“今天练胸”请求。
  - 证据：`backend/task_evaluation/acceptance.py`（准入类型 + `admit_live`，33 项测试）；`specs`→`scenarios/safety_boundary.json` 6/6 通过，含 `normal-chest-plan`；`docs/evaluation/agent-annotation-guide.md` 定义双人盲标、分歧裁决、缺失记 `unknown`。
- [x] Task 2：Gateway/Broker、父进程批次预算、物理attempt计量、取消与partial报告；FakeProvider覆盖完整CLI路径，拒绝时Provider零触达。
  - 证据：`backend/task_evaluation/live_gateway.py`（admission→factory 顺序、reserve/settle、消息白名单、`FakeGateway` 四边界，18 项测试）。超时记 failed、取消记 cancelled、未知用量保留全额预留、准入被拒时未开任何 attempt。父进程预算账本沿用既有 `BatchBudget` IPC。
- [x] Task 4离线部分：开关行为、账户导出/删除/TTL、确认响应丢失、版本冲突、超时与取消演练、发布及回退手册。已有覆盖先复用，不重写第二套存储或审核系统。
  - 证据：新增 `docs/release/controlled-rollout.md`；复用既有覆盖 10 个文件共 **111 passed**，含确认重放、head 冲突、导出/删除/TTL、超时与取消。手册记录实测默认值（`coach_agent_mode` 仍为 `legacy`，不得称已开启 unified）。

## C：S5 效果验收与受控发布

- [ ] 用户确认模型、脱敏场景、调用/token/时间预算、质量判定规则后执行Task 3。暂不预设提升比例；完整保留失败、unknown usage和缺标签。
  - **未执行**：需要模型选择、脱敏场景、预算与质量判定规则的独立授权。当前 `live` 分支明确返回“live execution is not enabled in this stage”。
- [ ] 同一授权批次交替执行reference/optimized。按入口/场景分别报告完成质量、安全不变量、往返数、usage和延迟，不能把不同suite拼成一个收益。
- [ ] 迁移/生产发布依照Task 4独立授权与备份流程执行。代码合并不合并SQLite数据。

## D：U7 默认路径与退役

- [ ] S5相应验收通过后，按路线重组设计§13核对四处默认入口及配置；不因文档写默认开启就声称运行环境已开启。
- [ ] 仅退役教练legacy模式分叉，保留S2仍用的business_scope、BoundaryWorkflow及structured_workflow。
- [ ] 回归教练、计划、智能录入与配置兼容；数据源迁移和实验策略不随默认入口切换。

## 独立RAG工作线

按 `2026-10-31-rag-quality-upgrade.md` 的R0–R4执行。RAG已有基础能力，不应列为全新系统；Agent权限与审核复用现有边界。RAG工程不依赖先取得Agent性能百分比，但接入验收必须覆盖统一教练。

- [x] **R0：固定离线基线与合同。**
  - 契约：`backend/rag/contracts.py`（`Chunk` 位置/版本分离、`IndexManifest`、`RetrievalResult` 的 `ok/insufficient/unavailable` 三态互斥、`QueryCase` 的 dev/holdout 与 locator 校验）。
  - 语料：`backend/tests/fixtures/rag/corpus.json`，版本 `rag-corpus-v1`，7 文档 / 9 查询（dev 7、holdout 2），全部合成。
  - 基线：`docs/evaluation/rag-quality-baseline.md`。当前实现 **5/9**（dev 4/7、holdout 1/2），明确标注为 hashing+词项能力，不是语义模型能力。
  - 已复现三个缺口并固化为 `strict=True` 的 xfail（R1/R2/R3 的目标）：长行 2000 字符被截断为 900（丢 1100）；同数量改文仍返回旧索引内容；零匹配与离题查询仍返回 3 条。
  - 另记录两项能力边界：同一 source 每块只取一条；跨语言查询不可用。
- [x] R1：完整切分与知识元数据
  - `backend/rag/ingest.py` 重写：长块切分而非截断（2000 字符行完整可重组）、续块保留标题、ordinal 连续、位置型 `chunk_id` 与 `content_hash` 分离、`document_version`、未声明溯源保持 `None`。`backend/tests/rag/test_ingest_integrity.py` 21 项。
- [x] R2：索引失效、增量构建与发布
  - `backend/rag/index_release.py`：按 manifest 判定有效性（语料摘要/切分版本/provider/model/维度/chunk 数），新 release 写独立目录后 `os.replace` 原子切换；缺向量、NaN/Inf、维度不齐、重复 id 一律拒绝发布；增量复用仅限同配置同 content_hash。`EmbeddingProvider` 增加 `provider_name`。`backend/tests/rag/test_index_release.py` 17 项。
- [x] R3：检索融合、可选重排与无证据状态
  - `backend/rag/ranking.py`：RRF `sum(1/(60+rank))`、按 source 上限（默认 2）、可注入重排且失败退回并记因、重排分数不作置信度。`retriever.retrieve_detailed` 返回 `ok/insufficient/unavailable`；`retrieve_knowledge` 保留 list 契约但无证据返回空。`backend/tests/rag/test_ranking.py` 22 项。
  - **实测提升**：语料 dev 4/7→**5/7**，总分 5/9→**6/9**（多证据 1/2→2/2；离题由误返 3 条→`insufficient`）。
  - 排序策略按查询形态区分：字母词查询词项参与融合，CJK 单字查询仅作门限。此区分由全量回归发现（纯向量排序曾使两条 `test_agent_graph` 契约失败）后修正。
- [x] R4：证据约束生成与 Agent 接入
  - `backend/rag/evidence.py`：编号证据块（上限默认 5）、`check_citation` 拒绝未知 id／跨 release／hash 不符、`check_answer` 检出无证据的权威性措辞、来源正文指令型文字中性化（hash 仍描述原始文本，引用可校验）。`coach_composition.local_knowledge` 返回带 `evidence_id`/`chunk_id`/`release_id` 的块，非 ok 返回空；`unified_coach` 的 `sources` 携带同字段。`backend/tests/rag/test_evidence.py` 25 项、`test_coach_evidence.py` 8 项。
  - **边界**：`check_answer` 是确定性文本检查，不是忠实性判定；中性化不声称消除注入；引用合法 ≠ 事实正确。

## 执行纪律

后续代码工作默认顺序执行。新分支/工作树前按AGENTS备份、校验并隔离数据库；本轮文档修改不创建分支、不读取真实配置。提交、推送、真实调用及正式迁移不从计划复选框推断授权。
