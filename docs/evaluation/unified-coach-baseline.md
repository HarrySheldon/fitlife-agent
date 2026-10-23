# 统一教练 U0 基线

日期：2026-10-22。主 checkout：`main/a042ed9`。开发 checkout：`.worktrees/unified-coach-agent`，分支 `codex/unified-coach-agent`。

## 备份与隔离

先从主配置解析：主数据目录 `D:\code\vibe-coding\fitlife-agent\backend\data`，业务库 `fitlife.sqlite3`，独立运行库 `agent_runtime.sqlite3`。

| 备份（主 checkout 的忽略目录） | 验证 |
| --- | --- |
| `.local-backups/unified-coach-main-20261022-01.sqlite3` | `integrity_check=ok`；SHA256 `13bad17a4599b81440e3c767f95eac385e49421cc6e415fa38e7548e95e634f8` |
| `.local-backups/unified-coach-runtime-20261022-01.sqlite3` | `integrity_check=ok`；SHA256 `8c1918a00cc0159f445c7c9a5622f567b7c90ff54a6295e93a19200643287ee6` |

业务库通过主解释器执行 `scripts/backup_sqlite.py --output <上述绝对路径>`；运行库通过 SQLite backup API 取得一致快照，不复制 live SQLite。确认 `.worktrees` 和 `.local-backups` 已被忽略后创建开发分支。快照复制到开发 checkout 的 `.dev-data`，该目录也已忽略；本次不启动使用私密快照的应用，不调用其中模型配置。

所有应用测试与评估另外使用合成数据、假凭据、独立临时 SQLite；没有用 `.dev-data` 里的真实账户做测试。主库和运行库未做 schema 迁移或数据合并。若以后使用私密开发副本启动应用，必须先配置与该副本匹配的账户密钥，不能直接把真实配置放入 Git。

## 原始问题的 RED

`backend/tests/unified_coach/test_scope_regression.py`：4/4 断言失败，均为 `needs_clarification=True`，不是导入失败。

- 教练你好，我需要今天练胸，给出一份完整的训练计划。
- 给出一份完整的训练计划。
- 教练你好，安排训练计划。
- Hi coach, I want a complete chest workout today。

修复后，同文件＋原业务范围/安全 guard 契约：**41 passed**。显式范围外与已有攻击/混合请求回归没有通过取消安全检查来“修复”。新 unified 模式不使用旧语法准入判断，legacy 模式保留其有限保守规则用于兼容。

## 原版本全量基线

主解释器 `.venv/Scripts/python.exe`，先验证 pytest 9.1.1。主 checkout 保留原有两处未提交修改：`async_coach_gateway.py` 及其 transport 测试，未覆盖或提交。故该基线是保留用户工作区的真实基线，不伪装为纯 HEAD；新工作树未搬运这两处修改。

```powershell
$env:DATA_DIR = 'D:\code\vibe-coding\fitlife-agent\.tmp\u0-main-baseline-e'
$env:SQLITE_DATABASE_PATH = ''
$env:LLM_ENABLED = 'false'
& .venv\Scripts\python.exe -m pytest backend/tests --ignore=backend/tests/test_config.py -q -x --basetemp=.tmp/pytest-baseline-u0-e --junitxml=.tmp/u0-main-baseline-e.xml
```

结果：**2238 passed，1 warning，958.32 秒**。运行前已在该 DATA_DIR 生成合成样本；真实 Provider 未启用。日志/XML 位于主 checkout 的 `.tmp/u0-main-baseline-e.*`。

首次受限进程的 pytest 无法创建 Windows sandbox 临时目录，产生 setup errors；它不是可信功能基线，未计入通过数。改用显式仓库内 basetemp 和获准离线执行后重新取得上述结果。后续测试一直使用明确 basetemp，不擅自修改系统 ACL。

## 指标解释

原练胸请求的“旧版零模型调用/误拒”不能与新版正常执行的耗时直接比较为性能提升。新 Agent 在无需事实查询时可以直接回答，也可能因 Skill/工具需要更多轮调用。U 只建立可观测计数；真实 token、费用、缓存命中与 P50/P95 留给获准的 S4/S5，不预填百分比。
