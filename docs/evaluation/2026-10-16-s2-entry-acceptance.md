# S2 交互录入验收（2026-10-16，更新至 2026-10-17）

范围：八类独立合成回放、公开 API 与独立只读 SQLite 双重判分，以及部分保存→新 Service 恢复→人工补全的端到端验收。验收工作目录为 `.worktrees/agent-runtime-refactor`；验收阶段不提交、不推送、不调用真实 Provider、不使用生产数据。S2 实现与离线验收已完成，不代表真实模型效果验收或生产发布。

## 最终验证结论（2026-10-17）

**结论：S2 五项任务已完成实现与离线验收。** 所有已发现的集成问题已实施修复并经独立规格及质量复核关闭，无待修复的 critical/important 结论。最终源码保持冻结，最终完整回归均已返回。该验收检查点的 S2 改动尚未提交或推送，主工作区未修改；后续集成状态以 Git 记录为准。S3–S5 不在本次交付范围。

- 后端目标：98 passed，204.23 秒；最终完整后端：**1919 passed，798.10 秒**，退出码 0；报告 `.tmp/s2-backend-final-closure1017.xml` 已核实 tests=1919、failures=0、errors=0、skipped=0。
- 前端目标：46 passed，5.10 秒；最终完整前端：267 passed / 39 files，22.54 秒。
- 最终构建：退出码 0，Vite 7.76 秒；保留既有大于 500 kB 包体警告。
- 最终 Mock CLI：交互 8/8、旧基线 6/6，退出码均为 0；报告分别在 `.tmp/task-evaluation/s2-interactive-final1017`、`.tmp/task-evaluation/s2-baseline-final1017`。
- own canonical 回归已先复现 1 failed / 8 passed，再以与草稿原子发布的可信内存来源修复；不向 localStorage 新增健康正文或来源字段。

交付包括稳定条目与来源、整餐最多两轮澄清、局部更正、原子部分保存及长期防重、持久任务预算、只读恢复、训练旧通路兼容、账户导出/删除和显式到期清理。最后的集成修复还覆盖目录切换归因、失效食品不阻断训练、本地训练编辑保留、并发冲突审阅，以及规范化后丢失响应的同键重试。功能仍默认关闭，不自动执行维护或写入用户正式记录。

最终命令均在指定工作树运行：

```powershell
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest backend/tests -q --basetemp .tmp/s2-backend-final-closure1017 --junitxml=.tmp/s2-backend-final-closure1017.xml -p no:cacheprovider
npm --prefix frontend test
npm --prefix frontend run build
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s2-interactive-final1017
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/baseline.json --output .tmp/task-evaluation/s2-baseline-final1017
```

下文保留执行历史；其中 PENDING 及失败描述是当时检查点，不取代本节最终验证状态。CLI 的 workspace_diff 记录实际执行检查点；随后只更新验收文档，不更改受测源码。

## 配置

生产默认 `INTERACTIVE_ENTRY_ENABLED=false`；可在部署环境显式设置 `INTERACTIVE_ENTRY_ENABLED=true`，`ENTRY_TASK_TTL_DAYS=30`（正整数，创建时快照）。`.env.example` 列出开关，`docker-compose.yml` 已显式映射 `${INTERACTIVE_ENTRY_ENABLED:-false}` 与 `${ENTRY_TASK_TTL_DAYS:-30}`。禁用后已有草稿仍可 GET 查看，变更命令被拒绝。

交互评估 worker 仅对 `requires=["interactive_entry"]` 的声明案例显式开启能力，固定关闭全局 LLM 并保持无模型连接。八类分别为充分信息、目录歧义、未知份量、两轮上限、部分保存、局部更正、GET 恢复和跨账户拒绝。每例独立账户和数据库，保留网络守卫与预算/截止时间边界。

## 命令与验证记录

以下命令由根代理执行并记录实际结果；未返回的项目明确为 PENDING：

```powershell
$taskPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
& $taskPython -m pytest --version
& $taskPython -m pytest backend/tests/task_evaluation backend/tests/test_s2_entry_acceptance.py backend/tests/test_s2_model_availability.py -q -s -p no:cacheprovider --basetemp .tmp/s2-eval-model-green1016b
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/interactive_entry.json --output .tmp/task-evaluation/s2-interactive1016b
& $taskPython -m backend.task_evaluation.cli --mode mock --suite backend/task_evaluation/scenarios/baseline.json --output .tmp/task-evaluation/s2-baseline1016b
```

- 初始 RED：捕获数组索引和显式能力准入两个测试实际失败（2 failed，2.20 秒），随后实现。
- 评估回归与双重判分负例首次运行：105 passed / 1 failed；唯一失败为旧测试 SimpleNamespace 配置缺少新指纹字段，已显式补齐。加入模型准入回归后冻结重跑 **111 passed，118.51 秒**。
- 八类 CLI：**8/8 通过**；六类基线 CLI：**6/6 通过**。两套均为隔离合成 Mock，命令退出码 0，产物为上述 output 目录内的 report.json/report.md。
- 端到端 acceptance trace：冻结重跑通过，实际观察如下表。模型接线 RED：1 failed / 3 passed，确认全局开关关闭时已配置用户模型被遗漏；元数据准入回调修复后的四种连接状态已包含在上述 111 passed 中，GET 禁止读取模型配置的断言保持通过。
- 前端完整测试：**251 passed / 37 files，31.08 秒**；`npm --prefix frontend run build` 退出码 0，Vite 构建 9.06 秒，保留既有大于 500 kB 包体警告。完整后端：PENDING。
- S2 最终规格与代码质量复核：PENDING。

2026-10-17 中断续作：中断前的后端全量进程结果不可读取，不能据此宣告通过；重新执行并请求保存 `.tmp/s2-backend-final1017.xml`，报告须待命令结束后核实。前端本次复验 **251 passed / 37 files，63.10 秒**；报告参数没有生成预期 JUnit 文件，以上依据实际终端退出码 0 与汇总输出，不声称已存在文件。本次构建退出码 0，Vite 17.80 秒，仍有既有大包体警告。

最终跨模块审查发现两项 P2，S2 暂不通过：active 混合草稿中的未完整训练条目被锁住，需补安全的训练局部编辑路径；食品切换或解除目录后仍沿用旧目录 provenance，需重建当前来源。修复与回归进行中，既有通过结果不覆盖这两项缺陷。

修复前完整后端基线已实际结束：**1892 passed，762.69 秒**，`.tmp/s2-backend-final1017.xml` 已读取确认 tests=1892、failures=0、errors=0、skipped=0。新增目录切换/解除来源回归实际 **2 failed，11.45 秒**，证明这两种来源错误未被既有全量覆盖；修复后须再次验证，不将该全量基线冒充最终通过。

集成修复进展：来源按当前目录的八个明确业务字段重建，不合并任意目录 metadata；解除目录清除旧归因，目标回归 **2 passed，12.58 秒**。训练兼容新增后端负例实际 **2 failed / 14 passed，78.45 秒**（两种开关下正例均被拒绝），前端新增 Hook/UI 首次 **4 failed / 1 passed**，其中一个 UI 选择器需先对齐真实文案，不能冒充编辑器行为复现；其余三项明确复现保存/重试/退出路径缺口。修复与独立复核尚未结束。

第二轮续作：补齐 active PATCH 的提交映射响应；规范化后确认指纹的真实负例 **1 failed / 6 passed** 修复后，前端目标 **37 passed，29.47 秒**。后端目标 **73 passed / 2 failed** 的两项输入诊断确认有氧仍未匹配目录，改为先创建独立可见的合成有氧目录且显式断言缺时长，不删除完整性断言。随后来源与混合训练目标 **19 passed，104.56 秒**。修复后前端全量 **258 passed / 38 files，39.51 秒**，构建退出码 0（Vite 19.73 秒，既有大包体警告）。

质量复核继续发现两个关联 P2，最终状态仍待完成：失效目录的只读 GET 食品投影与持久原值不同，会阻断仅训练 PATCH；食品交互响应整体刷新候选会覆盖尚未保存的训练手工输入。正在新增独立回归，不能用上述通过结果覆盖这些边界。修复后后端全量 `.tmp/s2-backend-post-review1017.xml` 仍待运行结束，且不覆盖后续新修复。

关联边界已实际复现：`test_s2_stale_food_training.py` **4 failed / 4 passed，43.28 秒**（目录更新/停用 × 开关开/关的正常训练更新被拒，食品篡改负例通过）；`SmartEntry.mixedLocalEdits.test.tsx` 修正问题组数据后 **5 failed / 2 passed，4.57 秒**（三类食品命令覆盖本地训练输入、清除作用域不清页面、并发训练变更缺少显式冲突）。修复拟共享只读依赖投影，并严格识别可信服务器食品视图后还原持久食品；前端按稳定训练身份保留本地修改，食品使用新服务器值，冲突需审阅而不自动确认。

上述关联边界修复前，第二轮完整后端已结束：**1911 passed，770.67 秒**，JUnit `.tmp/s2-backend-post-review1017.xml`。这证明此前两项修复未破坏既有全量，但不覆盖随后新增的失效投影与本地编辑回归；最终完成仍须等关联修复及复核、回归。

关联修复目标：共享恢复投影、可信食品比对与持久食品还原后，后端相关新旧录入/生命周期目标 **98 passed，204.23 秒**（`.tmp/s2-linked-boundary-green1017.xml`）。前端新增同步等待实际 enabled 及请求/响应落定后，相关目标 **44 passed**；规格复核又补“本地次数 + 远端重量”合并后的完整性回归，实际 **1 failed / 7 passed**，随后复用编辑器原校验函数重算可解除问题，目标 **45 passed，5.80 秒**，独立规格复核通过。未直接清空 issues，安全与估算接受等问题仍保留。同字段冲突保留本地并禁确认，可显式加载最新训练；清除作用域、换账户均清本地编辑。

最终冻结回归正在执行：后端 `.tmp/s2-backend-final-closure1017.xml`、前端全量/构建、两套 CLI 的 `s2-interactive-final1017` / `s2-baseline-final1017` 报告，以及质量复核。结束前保持 PENDING，不据目标测试提前宣告完成。

前端本轮完整回归 **266 passed / 39 files，27.98 秒**，构建通过（Vite 9.11 秒，既有大包体警告）。后续质量复核确认此前三项合并/投影问题关闭，但补充了自身训练保存覆盖实际手改目录字段的重试边界：服务器会还原目录 primary_muscle，界面不能把该规范结果误判为食品响应并保留旧本地值。正在新增真实字段覆盖回归，拟将可信发布来源与 Hook 草稿内存状态原子绑定；不新增本地健康正文持久化。上述前端全量不覆盖此新边界，最终仍未完成。

## 可复现的验收路径

| 实际步骤 | version | rounds | formal_count |
| --- | ---: | ---: | ---: |
| create | 1 | 0 | 0 |
| start | 2 | 1 | 0 |
| unknown_answers | 3 | 2 | 0 |
| save_oats | 4 | 2 | 1 |
| new_service_get_recovery | 4 | 2 | 1 |
| manual_correct_milk | 5 | 2 | 1 |
| save_milk | 6 | 2 | 2 |

`backend/tests/test_s2_entry_acceptance.py` 通过规范公开 API 创建合成全麦燕麦与未知牛奶，开始第一轮问题、以未知值回答进入第二轮、仅保存燕麦。随后构造同一数据库的新 Service，并通过公开 GET 读取相同 version、轮数、item 状态与保存映射；再用人工提供的牛奶名称、amount/unit、basis_type 和四项营养值完成局部更正并保存。每一步只读 SQLite 核对响应版本、轮数、item 状态、正式餐次数和零训练记录；最后检查两个 item commit。追踪输出只含步骤名称、实际 version、rounds、formal_count。

## 限制

Mock 与确定性路径验证执行契约和持久化不变量，不等同真实模型准确率、健康效果或成本证据。模型测试只能使用合成连接和假 Provider。恢复表示新 Service 对同库执行 GET，不表示后台任务队列、进程自动重启或自动续跑。无可信候选时保留 candidate_ms unknown；没有 S4 性能百分比结论。S3/S4 功能不在本次范围。
