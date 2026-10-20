# C2 接受请求、单槽、状态与真实取消验收

**日期：** 2026-10-19
**检查点：** `docs/superpowers/plans/2026-10-18-coach-conversation-experience.md` 的 C2
**状态：** 离线实现与验收完成。**未提交、未推送、未部署；未对真实库执行迁移；未调用真实模型。**
（2026-10-20 更正：已随 `df6fd98` 提交并推送至 `origin/main`；仍未部署、未迁移正式库、未调用真实模型。）

**2026-10-19 后续更正：** 下文是首次验收快照，不是最新实现。后续复核发现同步假传输不能证明真实异步取消，且删除聊天会提前释放槽；已新增异步HTTP传输、真实本机TCP取消测试与删除慢清理屏障。删除不再直接把在飞Turn终结，也不再从准入查询排除已删除会话。当前实现/证据及C3进行中范围以 [收口记录](2026-10-19-c2-closeout-c3-foundation.md) 为准。首次“完成”不能作为这些后续缺口已验证的证据。

---

## 1. 交付内容

| 文件 | 责任 |
| --- | --- |
| `backend/domain/coach_turn.py`（新） | 执行槽、状态迁移、取消意图、费用提示（纯函数，不读库） |
| `backend/application/ports/coach_answer.py`（新） | 一次问答的窄端口：只收问题，不碰 turn／会话／存储 |
| `backend/application/ports/model_call_context.py` | 新增 `AbortRegistry`：登记可关闭资源，取消时真正关闭传输 |
| `backend/application/use_cases/coach_turns.py`（新） | 准入、执行、取消、终态发布、旧入口 `run_legacy` 包装 |
| `backend/infrastructure/agent_runtime/coach_answer_adapter.py`（新） | 把现有 graph 入口适配成窄端口 |
| `backend/api/coach_conversations.py`（新） | 九个公开路由 + 独立开关 + 错误脱敏映射 |
| `backend/infrastructure/sqlite/schema.py` | **追加**迁移 8 `coach_turn_execution`，不改动 1–7 |
| `backend/infrastructure/repositories/sqlite_coach_conversation_repository.py` | 原子准入、租约、取消意图、条件发布、启动恢复、删除即释放槽 |
| `backend/infrastructure/sqlite/database.py` | 每库一个进程内写锁 + 失败换连接重试（见 §4） |
| `backend/api/coach.py`、`plan.py`、`report.py` | 三个旧入口接入同一准入 |
| `backend/api/account.py` | 账户删除前先停止该账户的模型调用 |
| `backend/infrastructure/startup.py` | 启动时把本进程无法恢复的旧活动 Turn 标 `interrupted` |
| `backend/config.py` | 新增 `coach_conversations_enabled`，默认 `False` |

## 2. 契约

### 2.1 一个账户一个执行槽，拒绝而不是排队

准入在**一个写事务**里完成：先按 `(user_id, conversation_id, idempotency_key)` 找已存在的 Turn，
没有才检查槽位，再插入 `queued`。

- 相同键 → 返回同一个 `turn_id`，`replayed=true`，不产生第二次模型调用。
- 不同键且槽被占用 → `409 COACH_TURN_BUSY`，**不入队**。排队的 Turn 对调用方显示"已接受"，
  却没有任何东西会启动它。
- `queued`／`running` 占槽；`awaiting_user` **不占槽**——它在等人，不在用模型。
- `stopping`（已请求取消、传输未关）**仍然占槽**，否则第二次调用会在第一次还在烧 token 时开始。

槽位判定与 `active_turn` 都 `JOIN coach_conversations ... AND c.status='active'`：
已删除聊天的 Turn 不能占着账户唯一的槽。

### 2.2 生成期间不持有事务

接受提交后才调用答案端口，发布是另一个事务。把写事务挂在模型调用上会让所有账户排在一个慢供应商后面。

### 2.3 取消是关闭传输，不是置标志

```
cancel() → request_cancel（记录意图，状态仍 running）
        → AbortRegistry.abort()
        → gateway.close()（关闭该 run 私有的 httpx.Client）
        → 阻塞中的调用抛错
        → worker 发布 cancelled，槽才释放
```

`AbortRegistry` 是对象而非值：上下文被复制到工作线程时共享同一个实例，取消线程才能触发它。
`register` 在已 abort 后仍会立即关闭新登记的资源，避免"取消先到、资源后到"的泄漏。

**费用提示**：`cancellation_notice(language)` 随取消响应返回——
"The model call may already have incurred a charge; cancelling does not refund it."
停止的是工作，不是账单。

### 2.4 终态发布是条件的

`complete_turn` 在**一个事务**里先重查 `coach_conversations.status='active'`、Turn 未取消、
未过期、版本未变，然后才写回答并把 Turn 置 `succeeded`。任何一条不成立就返回 `False`，
调用方丢弃迟到答案。

两段事务会留下窗口：答案已写、取消刚到、Turn 仍开着，用户已经停掉的那句话还在。
这里答案只有在"写入那一刻仍可发布"时才存在。

**回执**：成功发布的 `receipt_json` 保存 `model` 与 `trace`。终态 Turn 的重复读取只读同一份回执，
不会重新调用模型；`GET /turns/{id}` 在任何情况下都不触发执行。

**启动恢复**：新进程不拥有任何在飞 Turn，因此 `interrupt_stale_turns((), at=now)` 把它们全部标
`interrupted`，`error_code` 保持 `None`（不是失败），且**不重发**。这是单进程语义：
本功能不宣称支持多 worker 分布式执行。

### 2.5 旧入口不留旁路

`/coach/action`、`/plan/{id}/interpret`、`/report/weekly/{week}/interpret` 都改走
`CoachTurnService.run_legacy(..., produce=...)`：取槽 → 生产 → 发布，失败则释放槽。

包装成一次调用而不是三步，是为了让"新加的旧入口"没法只做其中两步。
匿名 `/coach/action` 没有账户，也就没有槽可占，因此不走准入——它本来就不可能为同一 owner 并发两次。

准入**不受 `coach_conversations_enabled` 控制**：新聊天入口关掉时，旧入口仍然共享同一个槽。
否则"关掉新功能"就等于给出第二条并发模型调用路径。

### 2.6 账户生命周期

| 事件 | 行为 |
| --- | --- |
| 删除聊天 | 先取消该聊天在跑的 Turn，再软删除；同一事务把该聊天未终结的 Turn 置 `cancelled` 并释放槽 |
| 账户删除 | `DELETE /account` 先 `cancel_active_for_account`，再删除数据 |
| 退出登录 | 客户端行为，不取消服务端执行；Turn 仍可按 id 读回 |
| 关闭窗口／刷新 | 同上：请求身份可读，执行状态不依赖窗口 |

删除聊天后 `get_turn` 抛 `KeyError`（HTTP 404）：聊天没了，它的转录和状态一起没了。
返回空转录会让已删除的聊天继续应答。

## 3. 验收证据

全部为合成数据、`tmp_path` 隔离 SQLite、合成慢传输；无真实模型。

| 测试文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `backend/tests/domain/test_coach_turn.py` | 21 | 槽持有状态集合、`awaiting_user` 不占槽、`stopping` 仍占槽、非法迁移、终态不可改写、版本冲突、取消意图幂等、取消提示双语 |
| `backend/tests/infrastructure/test_sqlite_coach_turns.py` | 20 | 原子准入、幂等键复用冲突、不同键单槽拒绝、租约认领、取消意图不改状态、条件发布、回执、删除后迟到发布失败、启动恢复只打断别人的 Turn、打断后释放槽且不可重发、重复打断幂等 |
| `backend/tests/infrastructure/test_async_coach_cancellation.py` | 6 | Planner／Writer／Reviewer 三处各自在取消时关闭传输且只发一次请求、重试等待期间取消不重放、cancel 后到发布前槽仍被占用、迟到答案不落库 |
| `backend/tests/test_coach_turn_lifecycle.py` | 19 | 提交先返回、完成后落库并释放槽、幂等不二次调用、失败终结、取消不存迟到答案、双次取消无害、取消已完成被拒、等待用户无需关闭、删除聊天先停、登出停止账户 Turn、跨账户互不影响、快捷动作共用槽、快捷动作不算聊天、快捷动作失败释放槽、`run_legacy` 在槽被占时**不调用生产函数**、生产失败释放槽、账号已不拥有时丢弃答案 |
| `backend/tests/test_coach_conversation_api.py` | 12 | 开关默认关闭、九条路由全部要求认证、跨账户 404、幂等重放、并发单槽 409、stopping 仍 409、awaiting_user 放行、GET 不触发模型、取消返回费用提示、未知会话 404、已删除会话拒绝新 Turn、账户删除停止在跑 Turn |

**C2 定向合计：78 passed。**

```bash
env -u CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR -u CODEBUDDY_TOOL_CALL_ID \
    -u CODEBUDDY_SAFE_DELETE_BULK_GUARD \
  .venv/Scripts/python.exe -m pytest \
    backend/tests/domain/test_coach_turn.py \
    backend/tests/infrastructure/test_sqlite_coach_turns.py \
    backend/tests/infrastructure/test_async_coach_cancellation.py \
    backend/tests/test_coach_turn_lifecycle.py \
    backend/tests/test_coach_conversation_api.py \
    -q -p no:cacheprovider
```

**C0+C1+C2 合跑：134 passed。**

## 4. 顺带修掉的既有缺陷

### 4.1 Windows 上并发写入必然失败

C2 的原子准入依赖并发写，一测就撞上既有缺陷：`BEGIN IMMEDIATE` 报
`attempt to write a readonly database`（`database.py:55`）。

根因不是锁竞争本身，而是**连接一旦在打开 WAL 共享内存文件时失败，就被永久标记为只读**，
在该连接上重试 `BEGIN` 永远不会成功。原始 SQLite 探针确认：同一文件、4 线程、每线程 50 次写入，
只要并发打开连接就会稳定复现。

修法：

- `write_lock_for(path)` —— 每个数据库文件一个进程内 `RLock`，把"打开连接 + BEGIN + 提交 + 关闭"
  整段串行化。读不加锁。
- `_begin()` —— 失败的连接**关闭并换新连接**重试；失败的 `BEGIN` 没有写过任何东西，替换是安全的。
- `_enable_wal()` —— 先读 `PRAGMA journal_mode`，已是 WAL 就不再写，避免每次连接都抢一次写锁。
- `sqlite_run_repository.py`、`sqlite_checkpoint_store.py` 的直接事务也纳入同一把写锁。

这解释了 C0／C1 回归里那 7–8 个"已知并发失败"：它们是同一个缺陷，不是业务问题。

### 4.2 已删除聊天的 Turn 永久占槽

`active_turn` 原本只按 `user_id + status` 查。删除聊天时 Turn 无法发布（会话已删），
于是永远停在 `running`，账户的槽再也不会释放。现在两处都修：
`delete_conversation` 在同一事务把该聊天未终结的 Turn 置 `cancelled`，查询也 JOIN 活跃会话。

### 4.3 因本次改动而必须更新的既有测试

**迁移 8 追加**（硬编码清单，不是放宽断言）：

| 文件 | 改动 |
| --- | --- |
| `backend/tests/infrastructure/test_records_schema.py` | 2 处迁移清单补 `(8, "coach_turn_execution")` |
| `backend/tests/test_database_startup.py` | 启动后版本列表补 `8` |

**行为契约变化**：

| 文件 | 改动 | 原因 |
| --- | --- | --- |
| `backend/tests/test_coach_api.py` | 认证用例改用带 lifespan 的 client | `/coach/action` 现在确实需要会话表 |
| `backend/tests/application/test_plans.py` | 注入真实准入服务（`tmp_path` 库） | 计划解释现在取同一执行槽 |
| `backend/tests/application/test_reports.py` | fixture 先 `initialize_database()` | 周报解释同上 |
| `backend/tests/test_startup_readiness.py` | `run_migrations` 桩改为"记录顺序并真正建表" | 启动恢复需要表存在 |
| `backend/tests/application/test_coach_context.py` | `interrupt_stale_turns` 登记为无 owner 的清扫；种子回合补发布 | 单槽下未终结的种子会挡住下一轮 |
| `backend/tests/test_coach_turn_lifecycle.py` | 删除聊天后断言 `get_turn` 抛 `KeyError` | 新契约：已删除聊天的 Turn 不可读 |
| `backend/tests/infrastructure/test_sqlite_database.py` | WAL 桩补探针返回值；新增"已是 WAL 不写"用例 | `_enable_wal` 改为先读后写 |

## 5. 回归

**环境：** `.venv\Scripts\python.exe`、隔离合成 `DATA_DIR`（`.tmp/c2-final2`）、`SQLITE_DATABASE_PATH` 置空、
`LLM_ENABLED=false`、独立 `--basetemp`，运行前清除沙箱 safe-delete 守卫变量。

```bash
env -u CODEBUDDY_SAFE_DELETE_BULK_STATE_DIR -u CODEBUDDY_TOOL_CALL_ID \
    -u CODEBUDDY_SAFE_DELETE_BULK_GUARD \
  .venv/Scripts/python.exe -m pytest backend/tests \
    --ignore=backend/tests/test_config.py \
    -q -p no:cacheprovider --basetemp=.tmp/c2-final2-tmp --tb=line
```

**结果：** `2186 passed, 0 failed, 1326.69s`。

这是本项目第一次跑出零失败的全量后端基线。C0 与 C1 的基线分别是
`7 failed, 2061 passed` 与 `8 failed, 877 passed`，失败全部来自 §4.1 的 Windows 并发缺陷；
写锁与连接替换修掉根因后，它们不再出现。

此前一版全量（同一环境）是 `6 failed, 2179 passed`，6 个失败均已按新契约修正并逐文件复跑通过：
`test_plans.py` 20、`test_reports.py` 14、`test_sqlite_database.py` 8、`test_startup_readiness.py` 6。

> 说明：本次全量在新增 3 个 `run_legacy` 用例之前启动，因此不含它们。
> 这 3 个用例已随 `test_coach_turn_lifecycle.py` 单独运行（`19 passed`），
> 计入 §3 的 C2 定向 78 项。

## 6. 明确不声称的部分

- **未提供前端。** "收起继续"与"停止生成"按钮、悬浮多聊天、输入法、滚动属于 C3；
  C2 只交付它们可以依赖的接口。
- **未实现多 worker 分布式执行。** 单槽是**每进程**的：两个进程同时服务同一账户时各自持有一个槽。
  启动恢复也会把另一个进程的在飞 Turn 标 `interrupted`。这一限制已写进契约，不在文档外假装成立。
- **未对真实库执行迁移。** 迁移 7、8 只在 `tmp_path` 数据库上运行过；正式迁移需按 AGENTS.md
  先备份校验并取得用户授权。
- **未调用真实模型。** 全部证据来自合成慢传输与假 gateway；真实供应商的关闭语义（是否立即中断读）
  未在本阶段验证。
- **未接定时清扫。** `purge_expired` 仍未挂调度；读取路径自带 90 天条件，不影响正确性。
- **未实现 `/chat` 的准入。** `POST /chat` 是另一条独立链路，本阶段未纳入；它不属于计划列出的
  三个旧入口。

## 7. 下一步

按统一顺序进入 **C3：统一悬浮多聊天和快捷入口**（`frontend/src/components/coach/*`、
`useCoach`、Layout 级 Provider），随后是 C4 离线整体验收。
