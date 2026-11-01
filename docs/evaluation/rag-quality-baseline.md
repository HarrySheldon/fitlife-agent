# 知识检索质量基线（R0）

日期：2026-10-31。依据 [RAG 升级计划](../superpowers/plans/2026-10-31-rag-quality-upgrade.md) R0。代码基线 `main`。

**本文件是"当前实现有多差"的记录，不是效果声明。** R0 只固定契约、语料与失败证据，不修检索。

## 1. 语料与查询集

| 项 | 值 |
| --- | --- |
| 语料版本 | `rag-corpus-v1` |
| 文档数 | 7（训练负荷、长段落、多证据、可替换、冲突 A/B、含注入正文） |
| 查询数 | 9 |
| 划分 | **dev 7 / holdout 2**（分开统计，不合并） |
| 语言 | zh-CN 6、en-US 3（含中英同义问法） |
| 私有数据 | 无，全部合成 |

位置：`backend/tests/fixtures/rag/corpus.json`；契约：`backend/rag/contracts.py`；测试：`backend/tests/rag/test_contracts.py`。

覆盖类别：长行、同文件多证据、同数量内容替换、中英同义问法、离题、缺证据、冲突来源、含注入文字的正文。

## 2. 基线结果（当前实现，hashing 向量 + 词项混合）

```
case                     split    ok   result
dev-overload-zh          dev      Y    hit 1/1
dev-overload-en          dev      Y    hit 1/1
dev-deload               holdout  Y    hit 1/1
dev-long-line-tail       dev      Y    hit 1/1
dev-multi-evidence       dev      Y    hit 1/2
dev-conflict             dev      N    MISS
dev-injection-body       dev      N    MISS
dev-missing-evidence     holdout  N    WRONGLY 3
dev-off-topic            dev      N    WRONGLY 3

dev     : 4/7
holdout : 1/2
TOTAL   : 5/9
```

**必须这样表述**：当前实现在 9 个查询上命中 5 个。这是 **hashing 向量 + 词项匹配** 的能力，**不是语义模型能力**，不能外推为真实 embedding 或生成模型的效果。

## 3. 三个结构性问题（已复现为 xfail 证据）

`backend/tests/rag/test_contracts.py` 中以 `strict=True` 的 `xfail` 固化；R1/R2/R3 修好后标记会自行失败，提醒删除。

### 缺口 1：长行截断（R1 修）

`ingest.py::flush()` 用 `text[:max_chars]` 截断，超出部分**直接丢弃**，不进入下一块。

| 输入 | 恢复 | 丢失 |
| --- | --- | --- |
| 单行 2000 字符 | 900 字符 | **1100 字符** |

**注意一个反直觉现象**：`dev-long-line-tail` 这个 case 竟然命中了。原因是存活的前 900 字符里已包含"遇到平台期先检查睡眠和总热量"的关键词，**所以该 case 不能证明截断无害**——截断本身另有独立测试证明。

### 缺口 2：同数量改文不失效（R2 修）

`retriever.py::_load_or_build_index()` 只比较 `embedding_model` 与 **chunk 数量**：

```python
if index.embedding_model == provider.model_name and len(index.entries) == len(chunks):
    return index
```

实测：把内容从 `xxx` 改成 `zzz`（chunk 数不变），索引**继续返回 v1 的 `xxx`**；用 v2 独有词 `zzz` 检索，返回的仍是 v1 内容。

### 缺口 3：零匹配仍返回内容（R3 修）

`retriever.py::_lexical_retrieve()` 末尾：

```python
if results:
    return results
return [chunk for _, chunk in scored[:top_k]]   # 全部 score <= 0 时仍然返回
```

实测：离题查询"帮我推荐几只股票"返回 **3 条**；语料无法回答的问题"生酮饮食对癫痫儿童的具体用药建议"返回 **3 条**。这正是 `RetrievalResult` 契约要禁止的形态——`insufficient` 携带 hits 会被校验直接拒绝。

## 4. 另外两个已观察到的局限（R3 处理）

| 现象 | 原因 | 影响 |
| --- | --- | --- |
| `dev-multi-evidence` 只命中 1/2 | `_source_diverse()` 每个 source 最多取一块 | 同一文档内的多处证据无法同时呈现 |
| `dev-conflict`、`dev-injection-body` 未命中 | 中文查询 vs 英文正文，词项匹配与 hashing 都不跨语言 | 跨语言检索不可用 |

这两项**不是**"配置问题"，是当前设计的能力边界。R3 的 RRF 融合与可选语义路径才可能改善，且必须用同一语料对比，不能只报提升。

## 5. R0 明确没有测量什么

| 未测 | 原因 |
| --- | --- |
| 真实 embedding 的语义检索效果 | 需要远端 embedding 配置与授权；hashing 不是语义模型 |
| 生成答案的忠实性 | 需要真实生成模型；R4 才有证据层 |
| 引用合法性 | R4 才实现 |
| 人工忠实性标签 | 需按 [标注协议](agent-annotation-guide.md) 由人工完成 |
| 延迟与成本 | 需要真实 Provider usage |

## 6. 复现命令

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
$py = '.venv\Scripts\python.exe'
& $py -m pytest --version
& $py -m pytest backend/tests/rag backend/tests/test_retriever.py backend/tests/test_vector_retriever.py backend/tests/test_vector_store.py -q
```

当前 R0 结果：`28 passed, 3 xfailed`（3 个 xfail 即上述缺口证据）。

**不得**把 `3 xfailed` 写成"全部通过"。

## 7. R1 后的状态（完整切分与元数据）

R1 只修 **完整性**，不改检索。得分**未变，仍为 5/9**——这是预期结果，不应被写成"提升"。

| 项 | R0 | R1 |
| --- | --- | --- |
| 完全切分 | ✗ 长行丢尾（丢 1100 字符） | **✓ 无截断，逐字符可重组** |
| chunk 身份 | ✗ 无 id/hash/版本 | **✓ 位置 id + 内容 hash + 文档版本** |
| 切分版本记录 | ✗ | **✓ `CHUNKING_VERSION` 写入每个 chunk** |
| 溯源字段 | ✗ | **✓ 未声明的保持 `None`，不虚构** |
| chunk 总数（语料） | 11 | **13**（长行正确切成 2 块） |
| 检索得分 | 5/9 | **5/9（未变）** |
| 缺口证据 | 3 个 xfail | **2 个 xfail**（缺口 1 已修，标记按 `strict` 机制自行失败后删除） |

R1 新增 `backend/tests/rag/test_ingest_integrity.py`（21 项）：长行完整性、逐字符可重组、chunk 不超上限、标题跨续块保持、ordinal 连续、id 稳定、同标题跨 source 不冲突、hash 与文本一致、未声明溯源保持 None。

**仍未解决的**（R2/R3 目标）：跨语言查询 MISS、同一 source 只取一块、零匹配与离题仍返回 3 条。

## 8. R2 后的状态（索引失效与原子发布）

R2 修 **索引正确性与发布安全**，不改检索。得分**仍为 5/9**。

| 项 | R1 | R2 |
| --- | --- | --- |
| 同数量改文 | ✗ 复用旧索引，返回 v1 内容 | **✓ 按 manifest 判定，语料摘要不符即重建** |
| 提供商不同、模型名相同 | ✗ 可能误判有效 | **✓ `provider_name` 独立参与判定** |
| 切分版本变更 | ✗ 不参与判定 | **✓ 参与判定** |
| 维度不一致 | ✗ 不参与判定 | **✓ 参与判定** |
| 缺向量 / NaN / Inf / 维度不齐 | ✗ 无校验 | **✓ 发布前拒绝** |
| 重复 chunk_id | ✗ 无校验 | **✓ 发布前拒绝** |
| 构建中断 | ✗ 可能留下半成品 | **✓ 旧 release 仍可读**（新 release 写入独立目录，校验通过后才原子切换 active manifest） |
| 增量复用 | 无 | **✓ 仅当 embedding 配置相同且 content_hash 未变** |
| 检索得分 | 5/9 | **5/9（未变）** |
| 缺口证据 | 2 个 xfail | **1 个 xfail**（缺口 2 已修并转为常规测试） |

实现要点：
- `backend/rag/index_release.py`：`index_is_valid`（按 manifest 比对语料摘要、切分版本、provider、model、维度、chunk 数）、`publish_release`（写入独立目录 → 校验 → `os.replace` 原子切换）、`load_release`、`read_manifest`。
- `backend/rag/vector_store.py`：`EmbeddingProvider` 协议与两个实现增加 `provider_name`，使"模型名相同但提供商不同"能够失效。
- `backend/rag/retriever.py`：`_load_or_build_index` 改为读 release + manifest 判定，不再比较"模型名 + chunk 数"；旧单文件 JSON 索引**不再被复用**，由 R2 机制重建。
- `backend/rag/ingest.py`：`ensure_chunk_identity` 为手工构造的 chunk 确定性补全身份，避免"为了兼容旧调用而绕过校验"的第二条路径。

**仍未解决的**（R3 目标）：跨语言查询 MISS、同一 source 只取一块、零匹配与离题仍返回 3 条。
