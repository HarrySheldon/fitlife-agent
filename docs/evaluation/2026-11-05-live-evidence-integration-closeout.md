# 统一教练、真实模型验收入口与 C1–C4 集成收尾

本次按用户明确授权，将 `codex/live-evidence-integration` 整体提交并合并到 `main`，随后推送 `origin/main`。此前各项记录的“未提交/合并”描述对应当时状态，以本次收尾记录为后续状态依据。

## 纳入范围

- 真实模型评估的受控父进程网关、子进程隔离、预算/授权绑定、操作命令、合成场景及审阅产物。
- 统一教练检索证据编号与来源绑定、发布前后引用校验及原预算内有限修正。
- Today 日期/异步响应一致性、完整且可读的计划差异、原生模态交互、显式逐轮读取范围和缺失权限提示。

不切换默认引擎，不退役 legacy，不迁移数据库，不调用真实 Provider，不将引用编号合法性或 mock 验证描述为事实正确性或真实模型质量验收。

## 主数据库保护

主 checkout 解析的活动数据库为 `D:\code\vibe-coding\fitlife-agent\backend\data\fitlife.sqlite3`。合并前通过主 checkout 的解释器和 `scripts/backup_sqlite.py` 使用 SQLite backup API 备份：

- 路径：`.local-backups/before-live-evidence-merge-20261105-173550.sqlite3`
- SHA256：`dbbdc129158d7bbaadeb335fddcd4f414bbb5a66bed4037df8e6a940f355ebce`
- `PRAGMA integrity_check`：`ok`
- 校验清单与备份同目录保存，均被 Git 忽略。

本次仅合并代码，保留主数据，不合并工作树的 SQLite 内容，也不清理工作树或开发数据。

## 合并前验证

获取远端后，`main...origin/main` 为 `0 0`，主 checkout 干净。使用项目解释器验证 pytest 9.1.1；相关后端回归覆盖 unified_coach、plan_diff、coach_conversation_api，以及 task_evaluation 的 operator/live_integration/cli/runner：**197 passed、1 skipped**，277.88 秒。测试设置隔离 `.tmp` 数据目录和 `LLM_ENABLED=false`，不设置指向主库的 SQLITE_DATABASE_PATH。保留既有 Starlette/httpx 弃用告警。

前端首次合并前全量为 332 项通过、1 项失败：既有 `SmartEntry.mixedTraining` 的训练确认请求未在测试默认等待窗口内被观测到。该套件独立重跑 7 项通过（3.02 秒）；先前 C1–C4 收口全量也曾 333 项通过。没有据此宣称消除了间歇失败，也没有修改产品代码或放宽断言；后端回归结束后另行单独全量复验。

最终前端独立全量：**52 文件、333 项通过**，160.00 秒，exit 0。TypeScript 检查及生产构建通过，Vite 构建 12.30 秒；保留大于 500 kB 的既有分块告警。`git diff --check` 通过。合并后验证另行记录。

## 尚未完成的验收

真实浏览器人工检查（包括原生模态背景交互、窄屏和 200% 缩放）此前因工具连接超时未完成；真实 Provider 质量、成本及延迟验收仍由受控操作入口另行执行。代码集成不代表上述验收已通过。

## 合并后验证

`main` 从 `0df22e2` 快进到实现提交 `e27f931`，没有合并冲突。在主 checkout 再次验证 pytest 9.1.1，使用主目录独立的 `.tmp/postmerge-verification-data` 合成数据，读取授权、计划差异及引用发布回归 **15 项通过**（3.77 秒）。这 15 项与合并前回归有重叠，不累计样本数。

主目录前端 TypeScript 检查和生产构建通过，Vite 构建 11.77 秒；产物摘要与工作树构建一致，保留既有分块告警。实现提交后的本次文档补记不改变源码。主数据库和工作树数据未迁移，工作树与开发分支保留。
