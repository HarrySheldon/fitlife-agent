# 受控发布与回退手册（Agent 计划/教练）

日期：2026-10-31。依据：[S5 验收计划](../superpowers/plans/2026-10-10-agent-task-s5-acceptance.md) Task 4 离线部分、[当前验收清单](../superpowers/plans/2026-10-31-agent-delivery-status.md) B/C/D 节、[AGENTS.md](../../AGENTS.md)。

**本手册是离线准备，不是已执行的发布。** 真实迁移、生产启用与扩大上线分别取得授权。

## 1. 当前实际生效的默认值

以下为代码默认值（`backend/config.py`），**不是**已批准的生产配置。实施前必须重新核对目标环境，并记录实际生效值。

| 开关 | 代码默认 | 手册目标 | 说明 |
| --- | --- | --- | --- |
| `llm_enabled` | `False` | 保持 | 关闭时不起真实模型调用 |
| `interactive_entry_enabled` | `False` | 保持 | 录入入口按需开启 |
| `coach_conversations_enabled` | `False` | 保持 | 会话入口按需开启 |
| `coach_agent_mode` | **`legacy`** | 目标 `unified`（D 节，**未完成**）| **不得声称已默认开启 unified** |
| `plan_adjustment_tasks_enabled` | `True` | 保持 `True` | 已是默认开启 |
| `plan_storage_mode` | `file` | **不随默认入口切换** | 属数据迁移授权，另行批准 |
| `task_execution_strategy` | `reference` | 保持 | 对照基线；无实测收益不开 optimized |
| `entry_task_ttl_days` | `30` | 保持 | TTL 快照不因配置更新延长 |
| `safety_review_mode` | `off` | 只能收紧，不能放松 | `off → shadow → enforce` |
| `safety_grounding_mode` | `legacy` | 保持 | `evidence` 未经真实证据验证 |

**规则**：安全政策只能收紧；`plan_storage_mode` 与 `task_execution_strategy` 不跟着默认入口一起改。

## 2. 发布前置：备份与校验（强制）

代码合并不合并 SQLite 数据。合并前必须：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent'
$py = '.venv\Scripts\python.exe'
& $py -m pytest --version                     # 确认解释器
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path (Get-Location) ".local-backups\pre-release-$stamp.sqlite3"
New-Item -ItemType Directory -Path (Split-Path $backup) -Force | Out-Null
& $py scripts/backup_sqlite.py --output $backup     # 输出含 sha256 与字节数
```

记录**备份路径、sha256、字节数**，并独立校验完整性：

```powershell
& $py -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" $backup
```

`integrity_check` 必须为 `ok`。**记录失败即中止发布**，不得以"稍后补"继续。

## 3. 发布步骤（逐项授权）

| 步 | 动作 | 门禁 |
| --- | --- | --- |
| 0 | 备份主业务库 + Runtime 库，校验 integrity 与 checksum | 缺失或非 ok → 停止 |
| 1 | 副本清点与 import dry-run（不写正式库） | 记录条目数与差异 |
| 2 | **用户单独授权**正式迁移 | 无授权不迁移 |
| 3 | 核对历史计划数、head、账户配置、加密密钥一致性 | 任一项不符 → 停止 |
| 4 | 服务端为**指定测试账户**开启入口 | 只开测试账户 |
| 5 | 合成/已批准测试账户跑完整闭环 | 见第 5 节 |
| 6 | **用户单独授权**扩大上线 | 无授权不扩大 |

**禁止**：清空旧账本或历史；把 `plan_storage_mode` 的切换当作代码合并的附带结果。

## 4. 开关演练（离线，已可执行）

以下均可离线验证，不消耗密钥、不接触真实账户：

| 演练 | 期望 | 证据 |
| --- | --- | --- |
| `coach_agent_mode=legacy` | 走边界/混合判定与旧教练路径 | `backend/tests/task_evaluation/scenarios/safety_boundary.json` 6/6 |
| `coach_agent_mode=unified` | 统一教练路径，越权仍拒绝 | `backend/tests/task_evaluation/scenarios/unified_coach.json` 28/28 |
| 关闭 `llm_enabled` | 不构造 Provider，返回受控提示 | `test_acceptance`、`test_live_gateway` 准入拒绝用例 |
| TTL 到期 | 拒绝继续操作，不自动延长快照 | `backend/tests/test_task_lifecycle.py` |
| 账户导出 | 含本人未过期任务、轮次、候选与回执 | `backend/tests/test_account_export_api.py` |
| 账户删除 | 覆盖同一回执表 | `backend/tests/test_account_delete_api.py` |

## 5. 故障与隐私演练清单

每项必须记录：**状态、正式写入数、重放结果**。不得以"测试通过"替代这三项记录。

| 演练 | 期望不变量 | 复用覆盖 |
| --- | --- | --- |
| Provider 不可用 | 受控错误，正式写入数 0 | `test_agent_runtime_controls.py` |
| 超时 | 受控错误，`attempts` 记为 failed，不重放 | `test_runtime_task_budget.py` |
| 断线 | 已完成的 attempt 不重放；未知用量保留全额预留 | `test_runtime_task_budget.py`、`test_live_gateway.py` |
| **确认响应丢失** | 同 key 重试返回首次结果，正式写入数仍为 1 | `test_plan_adjustment_api.py::test_confirming_twice_with_the_same_key_replays` |
| head 冲突 | 拒绝写入，正式写入数 0 | `test_plan_adjustment_api.py`、`test_smart_entry_api.py` |
| 约束更新 | 旧候选不得按新约束确认 | `test_plan_closeout_regressions.py` |
| 账户导出/删除/到期 | 导出覆盖，删除清除，到期拒绝 | `test_account_export_api.py`、`test_account_delete_api.py`、`test_task_lifecycle.py` |

**已跑证据（2026-10-31）**：上述复用覆盖共 **111 passed**，退出码 0。

## 6. 回退步骤

| 情形 | 回退动作 | 注意 |
| --- | --- | --- |
| 新入口行为异常 | 关闭开关（`coach_conversations_enabled` 等） | **只停止新任务，不删除草稿与正式记录** |
| 确认环节异常 | 关闭入口，保留已提交回执 | 已提交记录**不撤销**；不重放旧候选 |
| 存储切换后异常 | **先停写**，核对导出，再决定 | 不得直接把旧文件当最新状态源 |
| 数据库异常 | 用第 2 节备份恢复 | 恢复后重新校验 integrity 与 head |
| 安全政策方向错误 | 只能收紧（`off→shadow→enforce`） | 不允许为"减少误拒"而放松 |

数据库只做**兼容性增加**，不安排破坏性 down migration。

## 7. 未完成与待授权（不得勾选）

- **D 节 U7**：`coach_agent_mode` 仍为 `legacy`；默认入口切换与 legacy 退役未执行。
- **C 节**：真实 Provider 效果验收未执行（需模型、脱敏场景、预算与质量判定规则授权）。
- **正式迁移/扩大上线**：未授权。
- **浏览器人工演练**：未执行；单元测试不替代人工验收。
- **配对性能**：未测出可辩护收益（plans 退化 10.02%，coach 区间跨零），缓存与重排保持默认关闭。

**不得**把本手册的存在写成"已发布"或"已验证提速"。
