# S4 任务分级与性能对照 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 实际执行时使用环境中同名技能；是否委派由用户选择。

**Goal:** 在质量、安全一致的前提下减少可确认候选的处理时间与调用成本。

**Architecture:** 保留完整顺序执行作为reference，新增optimized策略。复用确定性目录结果与已验证局部状态，使用依赖版本失效，评估模块负责配对报告。

**Tech Stack:** Python、FastAPI、Pydantic、SQLite、pytest；前端 React、TypeScript、Vitest。

---

undefined
## 依赖与文件分工

依赖S2/S3完整可用的功能与场景。先测reference，再选择实际热点；不为简历预设性能提升数字。
新增：
`backend/agent/tasks/execution_policy.py`；
`backend/domain/task_dependencies.py`；
`backend/infrastructure/agent_runtime/task_cache.py`；
`backend/task_evaluation/comparison.py`；
`backend/tests/test_task_execution_policy.py`；
`backend/tests/domain/test_task_dependencies.py`；
`backend/tests/infrastructure/test_task_cache.py`；
`backend/tests/task_evaluation/test_comparison.py`。
修改：
`backend/agent/entry_workflow.py`、
`backend/agent/plan_adjustment/coordinator.py`、
`backend/application/use_cases/interactive_entry.py`、
`backend/application/use_cases/plan_adjustment.py`、
`backend/task_evaluation/contracts.py`、`runner.py`、`report.py`、`cli.py`。
修改 `backend/config.py` 增加task_execution_strategy(reference/optimized，默认reference)，每任务快照策略，实验显式选择。
修改 `docs/evaluation/task-evaluation.md` 记录reference/optimized、冷热缓存及指标。
各文件在前序阶段创建后再修改；不得为此重构无关Runtime代码。

### Task 1：路径选择与同等安全基线

- [ ] test_task_execution_policy.py 添加路由函数测试：目录唯一匹配且必要字段充分的录入可走短路径；缺字段或scope/risk不确定必须完整路径；两条路径都有同样输入/输出守卫。
- [ ] RED：`& $taskPython -m pytest backend/tests/test_task_execution_policy.py -q`。
- [ ] execution_policy.py定义 TaskFacts（task_kind、fields_complete、catalog_unambiguous、scope_decided、risk_decided、constraints_complete）与 ExecutionStrategy(reference/optimized)。路径选择使用确定性事实，不相信模型说“任务简单”。
- [ ] 接线规则：

```python
def entry_path(*, strategy: str, fields_complete: bool,
               catalog_unambiguous: bool, scope_decided: bool,
               risk_decided: bool) -> str:
    short = (strategy == "optimized" and fields_complete
             and catalog_unambiguous and scope_decided and risk_decided)
    return "deterministic_candidate" if short else "full_entry_workflow"
```

- [ ] 短路径直接确定性解析/换算，但仍执行授权、输入检查、类型验证、证据和配置要求的安全审核。review_mode=enforce时不能因不调用Writer就省掉必需Reviewer。
- [ ] reference与optimized具有相同已授权范围、场景和安全配置；reference只禁用路径裁剪与缓存，不剥离守卫。复杂计划仍用规划/校验/两轮修订，不用简单关键词替代约束。
- [ ] 记录各步骤耗时（使用monotonic）、调用类型、输入/输出tokens；因预算拒绝与模型耗时分别记录。隐私正文不进入telemetry。
- [ ] GREEN：验证mock provider调用数减少来自省略非必要生成；拒绝路径、审核失败路径两策略行为一致。
- [ ] CLI增加 --strategy reference|optimized 默认reference；现有S0调用保持兼容。

### Task 2：条目依赖失效和安全缓存

- [ ] test_task_dependencies.py 测“面改粉”只使该项目录/营养节点与餐合计失效；奶茶不失效。test_task_cache.py 测不同用户不可命中私有结果，目录版本变化miss。
- [ ] RED：`& $taskPython -m pytest backend/tests/domain/test_task_dependencies.py backend/tests/infrastructure/test_task_cache.py -q`。
- [ ] TaskDependencyKey包含数据scope、resource_id、resource_revision、catalog_revision、processor_revision。缓存键不使用“查询词”单独作为身份；公共目录可public scope，私有目录必须user scope。
- [ ] 依赖图只维护业务真正依赖关系：食物匹配→份量換算→营养→合计；计划base/硬约束→领域candidate→联合验证。field更新映射失效节点，无需引入通用工作流引擎。
- [ ] task_cache.py只缓存确定性目录匹配/换算或任务内已验证候选。每次复用仍验证owner、resource版本及权限；不缓存身份授权，不跨用户复用模型正文，不缓存最终确认结果作为校验替代。
- [ ] 缓存目录和数据版本以权威仓储版本生成；没有版本的Adapter先禁用该缓存，不能以mtime作为可靠跨进程一致性保证。
- [ ] 缓存有大小/到期上限；取消不留敏感临时正文，账户删除清理用户缓存；进程内缓存命中只是性能，不参与正式记录真相。
- [ ] 如果测量显示目录缓存无明显收益，保留局部重算而不强行启用全局缓存。计划成功模块复用受约束摘要版本绑定，constraints变更后重新验证。
- [ ] GREEN：修订一个训练字段不改diet、目录权限撤销立即不可复用、失败结果不污染缓存、冷热执行写入效果相同。并行读优化仅在profile证明收益时加入，读取必须独立且已授权。

### Task 3：配对实验、质量门槛和可引用指标

- [ ] test_comparison.py添加匹配指纹不一致拒绝配对、失败样本计成本、空基线不算提升：

```python
from backend.task_evaluation.comparison import reduction_percent

def test_reduction_requires_valid_baseline():
    assert reduction_percent(100.0, 75.0) == 25.0
    assert reduction_percent(0.0, 1.0) is None
```

- [ ] comparison.py最小算式：

```python
def reduction_percent(baseline: float, optimized: float) -> float | None:
    if baseline <= 0:
        return None
    return (baseline - optimized) / baseline * 100.0
```

- [ ] 只有相同case/version、模型/参数、安全规则、输入数据、硬件环境和mode可配对；允许strategy不同。每case按相同重复序号配对，采用交替执行顺序控制模型服务抖动。
- [ ] 分充分录入/模糊录入/局部更正/单域计划/联合计划报告：成功率、字段/硬约束质量、范围/隐私负例、系统处理P50/P95、首次可确认时间、调用/token、失败重试成本。不同path不混成一个无说明“平均速度”。
- [ ] 置信区间或样本不足说明，与原始样本一起保存；Mock可证明调用路径与缓存失效，不能写成真实模型延迟提升。发布门槛：确定性越权/重复写入/无效激活为0；语义质量真实效果由S5验证。
- [ ] CLI增加 --repeat（正整数）、--cache-state cold|warm（cold隔离清空应用缓存，不能承诺Provider缓存也冷）、--compare两个结果目录；比较文件只读。示例：

```powershell
& $taskPython -m pytest backend/tests/test_task_execution_policy.py backend/tests/domain/test_task_dependencies.py backend/tests/infrastructure/test_task_cache.py backend/tests/task_evaluation/test_comparison.py -q
& $taskPython -m backend.task_evaluation.cli --mode mock --strategy reference --repeat 3 --cache-state cold --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s4-entry-reference
& $taskPython -m backend.task_evaluation.cli --mode mock --strategy optimized --repeat 3 --cache-state cold --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s4-entry-optimized
& $taskPython -m backend.task_evaluation.cli --compare .tmp/task-evaluation/s4-entry-reference .tmp/task-evaluation/s4-entry-optimized --output .tmp/task-evaluation/s4-entry-comparison
```

- [ ] 计划场景执行同样两策略并配对，分别出报告。补 `docs/evaluation/agent-performance-baseline.md`，填写测得事实、样本和限制，不提前写百分比。
- [ ] 总入口回归通过后交付：可复现实验命令、配对原始结果、收益来源、质量约束；无收益的优化标无收益或回退，不挑选成功案例宣传。
