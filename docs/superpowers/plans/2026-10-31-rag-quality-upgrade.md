# 健康知识 RAG 治理、检索与证据升级 Implementation Plan

> **For agentic workers:** Use executing-plans，默认顺序执行；不自动委派。R0先固定接口和测试样本，后续按检查点实现；本文件授权范围为方案，不代表允许真实模型调用、知识正式发布或数据库迁移。

**Goal:** 在现有知识检索上建立可更新的索引、可验证的检索质量和可追溯的回答证据，对应知识治理、检索准确性、生成可信性三条亮点。

**Architecture:** 保留 `retrieve_knowledge(query, top_k)` 兼容入口；入库负责版本与完整切分，索引负责内容指纹与发布，检索负责召回/融合/可选重排，证据层负责引用合法性及不足状态。Agent继续由现有Runtime、工具权限和安全审核控制，不建立另一套模型执行框架。

**Tech Stack:** Python、现有EmbeddingProvider/JSON VectorIndex、pytest、现有AgentRuntime及离线评估。首版不引入向量数据库或外部搜索服务；可选远端embedding/reranker通过适配器显式配置。

## 1. 已有基础与已观察到的缺口

核查基线 `main/f9e70fc`，未执行新测试。

| 位置 | 现有实现 | 本轮设计要解决的问题 |
| --- | --- | --- |
| `backend/rag/ingest.py` | Markdown按标题切分，默认900字符 | flush使用截断，长行可能丢尾；无稳定chunk标识/内容版本 |
| `backend/rag/vector_store.py` | hashing默认、可选远端embedding、余弦与JSON持久化 | hashing不保证语义；批量zip非严格匹配，需验证向量数/维度/有限值 |
| `backend/rag/retriever.py` | 向量与词项原始分数相加、每source最多一个、异常后词项回退 | 索引只比较模型名和chunk数量，同数量改文可能复用旧索引；原始分数量纲不同；零匹配回退仍返回内容；回退原因不可见 |
| `backend/agent/unified_coach.py` | 从工具观察收集source/heading | 来源列表不能证明每条回答主张受证据支持；须增加证据ID及校验，不能只增加引用外观 |

这些为代码观察，不是生产故障复现结论。R0应先用最小测试复现；无证据不预判收益。

## 2. 接口与范围决定

知识只收录发布的公共健康资料，不把个人饮食记录、病史或聊天加入全局索引。用户事实经既有授权工具取得。来源正文视为不可信数据，不能授予工具权限。

- Chunk增加 `chunk_id`、`content_hash`、`document_version`、`source`、`heading`、`text`；`chunk_id`由source、标题、分块序号确定，同位置内容变化由hash区分。
- 新增manifest：schema版本、规范化语料摘要、切分版本、embedding提供商/模型/维度及配置摘要、release_id。不存密钥、用户数据或提示词全文。
- 新详细检索接口返回 `status`（ok/insufficient/unavailable）、`hits`、`release_id`、`retrieval_mode`、`fallback_reason`。旧入口只返回hits，保留source/heading/text；不得用无关结果填满top_k。
- Hit携带chunk_id/content_hash与检索排序信息。一次请求固定一个release；不得引用已替换的另一版本正文。
- 引用校验只证明来源有效与版本匹配。主张是否被支持须独立标注/审核，不能仅凭引用ID宣称事实正确。

首版采用本地不可变发布目录与原子manifest切换。增量复用仅限相同embedding配置及相同内容hash；embedding配置变更整批重建。来源多样性作为可配置上限，不强制一文只能取一段。

## 3. R0：固定离线基线与合同

**Files:** 新建 `backend/tests/rag/test_contracts.py`、`backend/rag/contracts.py`、`backend/tests/fixtures/rag/`、`docs/evaluation/rag-quality-baseline.md`；复用既有retriever/vector测试。

- [ ] 建立固定合成语料：长行、同文件多证据、同数量内容替换、中英同义问法、离题、缺证据、冲突来源、包含注入文字的正文。语料无私有数据。
- [ ] 为每个查询保存case_id、语料版本、相关chunk、允许答案要点及应拒答/追问条件；开发集和保留验收集分开，测试样本不写入Skill答案。
- [ ] contracts中定义上述Chunk/manifest/检索状态；测试旧调用仍得到list，详细结果状态不可混淆。
- [ ] 复现长行不完整和同数量内容替换不失效，保留失败结果作为R1/R2的RED证据。用现有实现生成基线，不将mock同义能力当语义模型能力。

## 4. R1：完整切分与知识元数据

**Files:** 修改 `backend/rag/ingest.py`；新建 `backend/tests/rag/test_ingest_integrity.py`。

- [ ] RED：输入超过900字符的单行，重组输出后必须覆盖所有非空正文；更改正文hash改变，重复加载ID稳定，两个source同标题不冲突。
- [ ] 实现无截断的分段，明确保留标题关系和分块顺序；字符上限不是远端token上限，后者在embedding适配器处理。
- [ ] 产生稳定ID与内容hash；文档版本由内容计算，可附来源URL、发布日期、审阅日期，但没有的字段保持unknown，不虚构权威性。
- [ ] GREEN：新测试和既有retriever/vector测试通过；记录切分版本。旧JSON索引通过R2重建，不直接编辑旧文件伪装新发布。

## 5. R2：索引失效、增量构建与发布

**Files:** 新建 `backend/rag/index_manifest.py`、`backend/rag/index_release.py`、`backend/tests/rag/test_index_release.py`；修改vector_store与retriever索引加载部分。

- [ ] RED：同数量改文必须失效；模型名相同但提供商/维度/切分版本不同必须失效；缺向量、NaN、维度不齐不得发布；构建中断后旧release仍可读。
- [ ] 以manifest比对完整配置和语料hash；同配置未变hash复用向量，变更块重新计算，删除块从新发布排除。
- [ ] 新release写独立目录，校验完成再原子替换活动manifest；请求先读取固定release再检索，旧版本保留至无读者/保留策略满足。首版不自动清理用户知识文件。
- [ ] embedding异常显式记录受控原因，不打印输入或密钥；旧索引不兼容时不能静默当当前版本使用。
- [ ] GREEN：用假embedding记录调用次数证明仅变更块重建，验证并发读取只见完整旧版或新版；不依赖网络。

## 6. R3：检索融合、可选重排与无证据状态

**Files:** 新建 `backend/rag/ranking.py`、`backend/tests/rag/test_ranking.py`；修改retriever与既有test_vector_retriever。

- [ ] RED：原始向量分数缩放不能改变基于排名的融合结果；同source两段均相关时可同时进入候选；离题不得自动返回前几块。
- [ ] 将词项和向量分别召回后按RRF融合，使用 `sum(1/(60+rank))`，rank从1开始；以chunk_id去重，候选数和source上限显式配置，稳定ID打破并列。
- [ ] 定义可注入reranker接口，输入query与受限候选，输出chunk_id及score；返回未知/重复ID、缺结果、异常或超时时退回融合排序并标明原因。默认无远端reranker，不能声称已有深度重排。
- [ ] 无证据策略用开发集校准后固定：hashing的分数不作语义置信度；离线演示至少要求词项匹配，无匹配为insufficient。真实语义路径阈值需独立验证，不能沿用演示阈值假定有效。
- [ ] GREEN：固定语料比较旧/新排序的相关性与证据覆盖，列出退化case；无整体收益时保留基线，不强行默认开启重排。

## 7. R4：证据约束生成与Agent接入

**Files:** 新建 `backend/rag/evidence.py`、`backend/tests/rag/test_evidence.py`；修改 `backend/agent/unified_coach.py` 及检索工具实际注册/handler（执行前通过rg定位，不新增平行工具）；新增 `backend/tests/rag/test_coach_evidence.py`。

- [ ] RED：伪造引用ID、跨release引用、修改hash、无结果却声称“资料证明”、来源正文中的越权指令必须被测试检出；无证据允许确定性业务工具给出数值，但不能冒充知识来源。
- [ ] 工具返回详细状态和受限证据块，渐进Skill说明引用协议及不足时的澄清/保守回答；系统稳定前缀只定义通用规则，动态release/证据后置。
- [ ] evidence层校验引用属于本次检索快照；非法引用要求已有Runtime预算内有限纠正，预算不足返回受控提示，不能绕过审核或开启无界重试。
- [ ] 区分“证据不足”和“超出业务/健康风险”；不足不一律安全拒绝。检索注入不得改变TaskSession许可、修订预算和写入路径。
- [ ] GREEN：合成Gateway完成教练检索、有效引用、不足追问、错误引用修复及预算耗尽闭环；前端若展示引用，另测source/heading与正文对应，避免只显示不可定位名称。
- [ ] 在 `docs/evaluation/rag-quality-baseline.md` 记录检索相关性、证据覆盖、引用有效性、人工忠实性标签及失败明细；真实embedding/生成评估单独授权，不预填指标。

## 8. 执行命令及最终门禁

以下为未来实现后的离线定向测试模板，本轮不执行。新增分支和数据隔离先遵循AGENTS。

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
$ragPython = '.venv\Scripts\python.exe'
& $ragPython -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'Project pytest unavailable' }
$ragTemp = Join-Path (Get-Location).Path ('.tmp/rag-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $ragTemp -Force | Out-Null
& $ragPython -m pytest backend/tests/rag backend/tests/test_retriever.py backend/tests/test_vector_retriever.py backend/tests/test_vector_store.py -q --basetemp (Join-Path $ragTemp 'pytest')
if ($LASTEXITCODE -ne 0) { throw 'RAG regression failed' }
```

测试使用fixture/临时索引和假Provider，禁止从真实账户配置隐式构造远端Provider。每阶段执行RED/GREEN再记录证据；R4后回归统一教练及全项目适用测试。提交/推送另获授权，不把计划写好当作实现完成。

## 9. 简历表述与交付边界

R1/R2对应知识治理，R0/R3对应检索准确性，R4对应回答可信性。已落地且有证据才能写“构建/实现”；尚未落地写“设计”。有效引用不等于医学正确；离线通过不等于真实模型效果；不以预设提升数字选择样本或调参。
