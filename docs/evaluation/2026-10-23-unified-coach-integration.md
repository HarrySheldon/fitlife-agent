# 统一教练 U0–U6 主线集成记录

日期：2026-10-23。用户明确授权提交、合并并推送；不包含生产启用、真实模型调用或工作树清理。

## 代码与数据边界

- 功能提交：`93e09a4683f9fd7c3b9541cdaf50aa6afec7ab0b`，从 `codex/unified-coach-agent` 快进合入本地 `main`。合并前主线为 `a042ed9`。
- 合并前 fetch 确认主线相对 origin/main 为 ahead 2 / behind 0；两条已有文档提交随本次主线推送同步，不属于新增功能。
- 主工作区原有 `async_coach_gateway.py` 和其 transport 测试修改单独保留，未纳入功能提交。原未跟踪方案文档已移入 ignored `.local-backups/unified-coach-main-docs-20261023-122147/`，没有丢弃原稿。
- 仅合并代码，不合并或替换 SQLite 数据。开发工作树及其数据保留。没有重启服务或启用 `COACH_AGENT_MODE=unified`，也没有改变默认安全审核模式。
- 远端目标为 `origin/main`。只有 push 成功且 `git rev-list --left-right --count main...origin/main` 返回 `0 0` 才算提交同步；本记录不代替远端核验。

## 合并前备份

主数据路径：`backend/data/fitlife.sqlite3`；Runtime 路径：`backend/data/agent_runtime.sqlite3`。使用主 checkout 解释器、原配置备份；运行库使用 SQLite backup API，不普通复制 live DB。两份备份 `integrity_check=ok`，均在 ignored `.local-backups/` 下：

| 备份 | SHA256 |
| --- | --- |
| `unified-coach-premerge-20261023-122147.sqlite3` | `13bad17a4599b81440e3c767f95eac385e49421cc6e415fa38e7548e95e634f8` |
| `unified-coach-runtime-premerge-20261023-122147.sqlite3` | `8c1918a00cc0159f445c7c9a5622f567b7c90ff54a6295e93a19200643287ee6` |

## 本轮新鲜验证

- 提交前：82 passed / 1 skipped，42.67秒；与原开发验收源码哈希快照一致。日志位于开发 checkout `.tmp/premerge-20261023.{log,xml}`。
- 合并后主线完整后端：**2299 passed / 1 skipped / 1 warning，1167.91秒，退出码0**。命令为 `pytest backend/tests --ignore=backend/tests/test_config.py -q`，使用主 `.venv/Scripts/python.exe`；先验证 pytest 9.1.1。
- DATA_DIR 为全新合成样本 `.tmp/unified-merge-seed-20261023`，SQLITE_DATABASE_PATH 为空，LLM_ENABLED=false，OPENAI_API_KEY 为空；不是主 data 或开发私有副本。basetemp 为 `.tmp/pytest-unified-main-20261023`，日志/JUnit 为 `.tmp/unified-main-20261023.{log,xml}`。
- 独立配置组：**6 passed，1.38秒**，独立进程移除测试覆盖变量；JUnit `.tmp/config-main-20261023.xml`。
- 前端：**46文件 / 299测试通过**，生产构建通过（21.79秒）。日志 `.tmp/unified-main-frontend-{test,build}-20261023.log`；保留现有大于500kB构建分块警告。
- 唯一skip为Windows账户无创建链接权限；后端warning为现有Starlette/httpx弃用提示，均没有伪装为验证通过。

原[验收记录](unified-coach-acceptance.md)中的28/28 Mock和源码字节哈希是2026-10-22开发工作树证据。本次没有重跑该28场景整套CLI，不把历史结果标为本轮执行。Git在Windows checkout中可能转换LF/CRLF，原清单不是主工作区原始字节的承诺；本次按Git提交及合并后的实际完整测试验证。

## 后续边界

U0–U6代码集成不等于真实模型质量、临床安全或性能提升已验证。S3正式计划任务闭环、S4同质量/同安全性能对照、S5受控真实模型验收仍待实施。本轮不为简历增加未经测量的提速、召回率或攻击防御率数字。
