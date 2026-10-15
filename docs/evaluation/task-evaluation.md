# 业务任务评估：S0 操作与验收

新评估包是同仓库的离线测试设施，不是业务服务，也不替代真实模型效果评测。S0 实现与离线验收已完成，之后已以 `e3027f6` 提交并推送，未合并到 main。以下保留 S0 当时的验证记录；2026-10-15 的 S1 后续工作与验证见 `docs/superpowers/plans/2026-10-10-agent-task-s1-contracts.md`。

## 运行命令（Windows PowerShell）

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
& $taskPython -m pytest backend/tests/task_evaluation -q -p no:cacheprovider --basetemp .tmp/s0-local-check
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/baseline.json --output .tmp/task-evaluation/s0
```

重复测试时使用新的 `--basetemp` 子目录，避免 pytest 删除旧测试目录。权限或安全守卫阻断时申请批准后在沙箱外执行，不清除守卫、不修改 ACL 绕过权限。

新入口默认 Mock，未传预算时使用整批 **200 次网关尝试、200000 个估算 token、300 秒**的有限上限。可显式限制整批任务：

```powershell
& $taskPython -m backend.task_evaluation.cli --suite backend/task_evaluation/scenarios/baseline.json --max-calls 20 --max-tokens 200000 --max-seconds 120 --output .tmp/task-evaluation/s0-bounded
```

输出为指定目录中的 `report.json` 和 `report.md`。退出码：`0` 仅表示全部案例通过且资源清理成功；`1` 表示存在失败、unsupported、预算/超时或清理异常；`2` 表示无效输入或本阶段禁止的 live 执行。不能只看报告文件是否生成来判断通过。

## 与旧评估入口的区别

| 入口 | 用途 | 默认与边界 |
| --- | --- | --- |
| `backend/evaluation.py`、`scripts/run_eval.py` | 单问答的工具、关键词、结构化检查 | 历史默认仍为 live，兼容回归不执行真实调用 |
| `backend/task_evaluation/cli.py` | 多步骤公开业务 API 回放和实际状态判分 | 默认 Mock，S0 不启用 live |

旧入口离线运行应显式指定模式：

```powershell
& $taskPython scripts/run_eval.py --limit 5 --mode mock
```

新入口的 live 参数准入要求 `--allow-live` 和三个正预算，但 S0 即使准入通过也拒绝执行，返回 `2`。真实模型评测留在 S5，经单独授权后开展。

## 隔离与判分

- 完整验证 suite 后才构造网关或运行案例。场景是带版本的声明式合成数据，不从任意文件导入初始状态，也不接受外部请求 URL。
- 每案例采用 Windows spawn、独立临时 DATA_DIR、独立 SQLite 和合成账户；配置仅使用显式初始化值，不读取 `.env` 或继承生产配置。
- 父进程拥有临时目录，子进程退出/终止并等待回收后清理。清理失败保留案例结果并记录受控 `cleanup_status`，不输出敏感路径或假称成功。
- 应用级 socket 守卫拒绝 Provider 对外及普通 localhost 连接；仅在 Windows `socketpair` 内部构造期间允许必要的自管道连接。这不是操作系统级容器或网络权限隔离。
- 请求按捕获的 ID/版本、结构化变量引用和 actor 认证回放。正式记录、幂等映射、草稿版本、账户归属和计划状态由隔离存储的只读观察判定，不用答案关键词替代保存成功。
- 六类基线覆盖正常录入、幂等重放、跨用户拒绝、过期草稿、现有计划激活和范围内问答。Mock 验收证明的是执行契约与确定性不变量，不证明真实模型健康建议质量。

版本化档案、结构化目录、记录和现有计划种子可用于 S0。旧版 profile 字段种子、多轮澄清/自动回答和未来 `requires` 能力明确记为 unsupported，不计作通过；脚本未定义的问题记为 unexpected_question。S0 不伪造 S2/S3 尚未存在的 API。

## 批次预算与异常

父进程账本在同一把锁下同时预留调用和 token，不能一个额度成功而另一个失败后泄漏容量。每个网关尝试、重试和审核入口都先预留后执行；已知消耗结算，未知用量或异常退出保留上限。案例共享整批额度和一个单调时钟 deadline，不会逐案例重置预算。

超时终止未完成 worker，后续案例标记未完成并保存部分报告。预算耗尽不回退到真实 Provider，也不通过另建 run 获得新额度。报告分开呈现已知用量和未知数量，失败与重试成本不能从分子中删除。

## 来源、时间和统计口径

每条记录包含案例 ID/版本、Git SHA、工作区源码摘要（包含未提交评估实现，兼容字段名 `workspace_diff`）、场景/目录摘要、实际安全配置指纹、提示源码摘要、模型、规则包和 Runtime 策略版本，以及关联 run IDs。摘要只输出 hash，不输出 diff、提示正文、凭据、原始用户文本或隐藏推理。

`processing_ms` 是业务请求的服务端处理时间合计，不包含子进程启动、注册、种子准备和用户思考。`elapsed_ms` 单列端到端回放耗时，不拿它替代处理时间。`candidate_ms` 表示首次经确定性校验的候选时点；无合格候选保留 null 并说明原因。问答的 `response_ready_non_confirmation` 单独标明是有效响应、不是可写入确认候选。

Mock token 是明确标记的字符估算，不是 Provider 返回的 token，也不是付费成本。失败/中断后无法确认的总用量保持 null；同时保留已知小计和保守预留。未执行模型的案例不捏造模型版本；其他案例的已知版本不能掩盖未知项。

Mock/live 分组统计，不合并准确率或成本；混合模式顶层成本保持 null。状态覆盖单列 passed、failed、unsupported 和受控错误类别。失败耗时单列，六个合成样本不用于宣称 P95 或性能提升百分比。

## 验证记录

2026-10-14 收尾前已有业务基线：后端排除新增评估测试后 **1500 passed**（526.81 秒）；前端 **36 files / 229 passed**，生产构建成功，保留既有 bundle 大小警告。以上均在获得批准后沙箱外执行。

第一次收尾验收：新增评估套件 **92 passed**，但实际六类基线均被误标 unsupported，暴露 spawn 序列化默认字段的问题。已修复，并增加真实六类回放与序列化回归。独立复核还补齐了计划安全结构、失败元数据、首次候选版本关联和超估算用量 unknown 的边界。

最终验收（2026-10-14，HEAD `1029a27` 加未提交工作区）：

- 规格复核通过；代码质量复核通过，无剩余阻断问题。
- 完整后端回归：**1598 passed**，551.21 秒，命令 `backend/tests -q -p no:cacheprovider --tb=short --basetemp .tmp/s0-finish-full-20261014`。
- 最后补入一个超估算用量回归后，最终 S0 套件完整重跑：**99 passed**，94.20 秒，`--basetemp .tmp/s0-finish-target-20261014-final`。完整后端运行收集的是此前 98 项 S0 测试；该新增项与全部最终 S0 测试均在这次重跑验证，不把 1598 误写成 1599。
- 最终六类基线：**6/6 passed**，CLI 退出码 `0`；产物为 `.tmp/task-evaluation/s0-final-reviewed-20261014/report.json` 与 `report.md`。六条配置/源码/场景摘要均有效，清理状态全部 completed。
- `--max-tokens 1`：五个确定性案例通过，问答案例为 budget_exceeded、实际网关调用为 0；保存报告并退出 `1`。
- `--max-seconds 1`：六个案例全部为 deadline_exceeded，保存部分报告并退出 `1`。
- 前端 **229 passed**，生产构建成功。保留 Starlette/httpx 兼容提醒与既有 bundle 体积警告，不把它们当成业务失败。

上述 S0 验证未调用真实 Provider，未修改主仓库的用户改动或生产数据；当时 S1–S5 未启动。本阶段产物不能用于宣称真实模型准确率、健康效果或性能提升百分比；后续阶段状态以总交付计划为准。
