# 交付表述与证据边界（2026-10-31）

本文件规定**如何对外描述这个项目**，防止把"已实现机制"写成"已获得效果"。依据 [S5 验收计划](../superpowers/plans/2026-10-10-agent-task-s5-acceptance.md) Task 4「交付表述」与[当前验收清单](../superpowers/plans/2026-10-31-agent-delivery-status.md)。

## 1. 三种必须分开的状态

| 状态 | 含义 | 可以写 | 不可以写 |
| --- | --- | --- | --- |
| **离线已完成** | 有代码 + 离线测试 + 合成场景证据 | "建立…闭环"、"实现…约束"、"定义…准入" | "效果已验证"、"提速 X%" |
| **live 待授权** | 能力就绪，但未做真实模型调用 | "已就绪，待授权验收" | "已通过真实模型验收" |
| **迁移/发布待授权** | 手册与演练就绪，未执行 | "已准备受控发布流程" | "已上线"、"已迁移" |

**禁止**把三者混成一句"已完成"。

## 2. 项目表述：问题 → 技术 → 结果 → 证据

每条都必须能指到具体文件或测试，**没有实测数字就不写数字**。

### 2.1 可信执行（注入、越权、误拒）

- **问题**：健康助手的输入可能夹带注入与越权指令；过度拒绝又会伤害正常任务。
- **技术**：业务范围与健康风险分轴判定；封闭工具与可信授权；按任务构建最小必要上下文；上下文只允许压缩 Skill 发现元数据；审核证明与确认后业务事务；混合任务只拒有害部分。
- **结果**：建立**准入—授权—确认**闭环；未测出误拒率与真实注入抵抗力。
- **证据**：`backend/safety/business_scope.py`、`backend/agent/context_policy.py`、`backend/task_evaluation/scenarios/unified_coach.json`（28 场景）、`safety_boundary.json`（6 场景）。

**不得写**："消除注入"、"误拒率为 X%"。

### 2.2 可靠落地（多域约束、中断、重复执行）

- **问题**：多域计划约束失败、运行中断、重复点击与旧候选确认会造成错误写入。
- **技术**：类型化候选 patch 与受信任务会话；持久 TaskSession；两轮共享修订；依赖失效闭包；CAS 与幂等回执；同源差异界面；确认前必须存在真实差异。
- **结果**：建立**幂等—版本—原子激活**闭环。
- **证据**：`backend/domain/task_dependencies.py`、`backend/application/use_cases/plan_adjustment.py`、`backend/tests/test_plan_closeout_regressions.py`、既有 111 项演练覆盖。

**不得写**："零故障"。

### 2.3 执行效率（重复发现、重复计算、上下文膨胀）

- **问题**：多轮任务重复发现与上下文膨胀拖慢可确认结果的到达时间。
- **技术**：稳定前缀、渐进披露、可信预取、发现元数据压缩、依赖驱动复用、attempt/usage 与配对报告。
- **结果**：**建立了测量能力**（配对、区间、unknown usage 单列）；**未测出可辩护收益**。
- **证据**：`backend/task_evaluation/comparison.py`、`docs/evaluation/agent-performance-baseline.md`。

**实测结论（必须照此表述）**：`performance_plans` 延迟下降 **-10.02%**（区间 [-17.35, -3.48]，**退化**）；`performance_coach` **1.76%**（区间 **[-1.87, 5.00]**，跨零，**不构成收益**）。质量门禁两套件均通过，安全不变量未被牺牲。

**不得写**："提速 10%"、"优化后更快"、"缓存显著降低 token"。

### 2.4 评估与准入

- **问题**：契约测试与 Mock 结果容易被当成真实效果。
- **技术**：独立场景/执行器/判分/报告；Mock 与 live 分组；配对重采样；准入在 Provider 构造**之前**；物理 attempt 计量；partial 报告。
- **结果**：建立**可复核的评估与准入边界**。
- **证据**：`backend/task_evaluation/acceptance.py`、`live_gateway.py`、`measurements.py`、`report.py`。

## 3. 必须主动声明的能力边界

| 边界 | 事实 |
| --- | --- |
| 任意代码工具 | **没有**。工具是封闭白名单，不存在通用执行或沙箱逃逸面 |
| 后台自动续跑 | **没有**。恢复是读取持久状态后**显式创建新 run**，不是进程重启续跑 |
| 模型直接写库 | **没有**。写入只经确定性业务事务 |
| 医学正确性 | **不承诺**。健康风险只做限制与建议，不做诊断 |
| 真实模型质量 | **未验收**。`live` 分支当前明确返回"live execution is not enabled in this stage" |
| 缓存/重排 | **默认关闭**，无实测收益 |

## 4. 可复现命令

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
$py = '.venv\Scripts\python.exe'
& $py -m pytest --version
& $py -m pytest backend/tests -q
npm --prefix frontend test -- --maxWorkers=2
npm --prefix frontend run build
& $py -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/safety_boundary.json --output .tmp/task-evaluation/demo
```

**每次引用数字都要重跑并记录 SHA、脏工作区、命令与退出码**，不得复用历史通过数。
