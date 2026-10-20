# 模型连接改造：执行与验证记录

> 本文记录首版 generation/tool 方案的历史成绩。用户后续批准业务化连接测试，最新实现及回归见 [2026-10-18 验收记录](2026-10-18-connection-business-check.md)，不能把本文 2012 项后端结果视为修订后成绩。

## 2026-10-17 开始执行

用户已授权开始实施，采用当前会话逐项推进。起点 HEAD `aa63c77`。用户随后明确选择“本项不涉及数据库，不用备份创建分支即可”；按此例外在原目录创建 `codex/model-connection-workflow`，没有创建工作树、提交、推送或变更正式数据库。此例外不取消未来分支默认备份规则。

仅使用已有项目解释器 `.venv/Scripts/python.exe`，pytest 版本 `9.1.1`。测试使用 `.tmp/model-connection-baseline-20261017` 合成 DATA_DIR，显式配置同目录 SQLite 路径及 LLM_ENABLED=false；通过覆盖既有样本生成器 DATA_DIR 生成合成记录，没有直接运行其默认写 backend/data 的入口。

## 本轮基线

| 检查 | 实际结果 |
| --- | --- |
| 模型设置 API、用例、协议适配、端点策略、加密存储、S2 模型可用性六个套件 | 47 passed，36.89 秒；exit 0 |
| 前端全量测试 | 39 files / 267 passed，62.72 秒；exit 0 |
| 前端 TypeScript／Vite 构建 | exit 0，Vite 25.62 秒；既有超过 500 kB 包体警告 |

后端报告：`.tmp/model-connection-baseline-20261017.xml`。一次既有 Starlette/httpx 弃用警告，不是断言失败。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_api.py backend/tests/application/test_model_settings.py backend/tests/test_model_protocol_adapters.py backend/tests/infrastructure/test_model_endpoint_policy.py backend/tests/infrastructure/test_model_connection_storage.py backend/tests/test_s2_model_availability.py -q -p no:cacheprovider --junitxml=.tmp/model-connection-baseline-20261017.xml
npm --prefix frontend test
npm --prefix frontend run build
```

上述命令的配置隔离按实施计划 Task 0 设置。基线阶段未进行真实 Provider 测试、未读取或使用用户模型密钥，也未运行全量后端；Fake 网关及合成密钥测试不能证明真实模型质量。后续最终全量结果见下文，没有把此前通过数量算作本次成绩。

## 改造前行为（历史基线，不代表当前实现）

- 获取模型／测试仍然只使用已保存连接，而非当前表单。
- 现有连接测试只有工具探测，没有独立基础生成探测。
- 现有启用路径尚无双项验证凭证门槛。
- 五步表单、active/draft 隔离及服务商预设注册机制尚未实现。

上述为开始执行时的历史基线，当前完成状态以最终验收结果为准。

## 2026-10-18 实施与当前验收

已实现服务商预设注册、schema 2 active/draft JSON 工作区、版本 CAS、当前表单预览、两种协议双项探测、15 分钟签名摘要凭证、强制验证启用及五步设置页。沿用现有业务网关，不添加原生协议或业务数据库表；旧启用记录继续可用但不伪造双项已通过。

### 测试先行的实际证据

- 首个工作区隔离测试先因缺少 ModelConnectionWorkspace 失败，再实现并通过；服务商注册先 2 项缺模块失败，随后通过。
- 双协议探测先 16 项失败，暴露缺基础生成及只检查工具名称，随后与既有协议测试合计 27 passed。
- 凭证、当前表单预览、启用闭环分别先因缺实现失败，再逐项实现并通过。
- 前端迟到结果测试先因不存在 patch 失败，实现后通过；完整页面测试覆盖当前表单、变更失效、手填回退、无隐式调用。
- 自检复现长中文配置签发 16401 字符 token、超出自身 4096 上限；改为 canonical 配置绑定摘要后，篡改／有效期／配置变化及长文本共 15 项相关测试通过。
- 模型列表 404 分支先错误归一成 MODEL_PROTOCOL_ERROR；独立失败测试复现后修正，明确返回 MODEL_LIST_UNAVAILABLE，且不披露供应商正文。

### 当前实际验证结果

| 检查 | 结果 |
| --- | --- |
| 复审修正后前端全量 | 42 files / 276 passed，28.50 秒，exit 0 |
| 复审修正后 TypeScript／Vite 构建 | exit 0；Vite 10.23 秒；既有大于 500 kB 包体警告 |
| 复审修正后配置优先级独立分组 | 6 passed，1.23 秒，exit 0；`.tmp/model-connection-reviewed-config-20261018.xml` |
| 离线完整设置／导出／启用／业务 resolver／账户删除 | passed；安装 socket 网络阻断，SDK 和 DNS 均为合成注入 |
| 复审修正前后端全量业务分组 | 2007 passed，797.65 秒，exit 0；`.tmp/model-connection-final-20261018.xml` |
| 复审修正后后端全量业务分组 | 2012 passed，787.35 秒（13 分 7 秒），exit 0；`.tmp/model-connection-reviewed-final-20261018.xml` |

首次诊断全量为 1983 passed / 9 failed，363.04 秒。原因是运行命令显式指定一个 SQLite 路径，而上传及智能录入旧 fixture 只切换 DATA_DIR，导致它们共享并污染同一合成数据库。只清空全局 SQLITE_DATABASE_PATH 后，四个受影响套件 39 passed，51.46 秒；没有修改这些业务断言。最终全量使用新的合成 DATA_DIR（`.tmp/model-connection-reviewed-final-20261018`）、SQLITE_DATABASE_PATH 空覆盖和 LLM_ENABLED=false；配置优先级用例仍单独执行，不混用环境。后端有一项既有 Starlette/httpx 弃用警告，无断言失败。

旧接口设置测试的启用假设已按新契约修订，认证、加密、用户隔离、错误脱敏断言保留，并补充“旧 PUT 无凭证不得启用”的公开接口测试。全量测试期间新增和修改的行为均需最终回归覆盖，不能将早期局部通过数累加为总数。

### 发布与风险

没有真实 Provider 调用、没有正式数据库／账户配置迁移、没有提交／合并／推送，也没有重启正式 Docker 服务。用户已明确允许只读独立审查；首轮发现一项 Important（同步 SDK 慢流可越过总期限）和三项 Minor（历史后退、取消等待、导出字段）。原审查者已复核修正，确认四项均关闭，未发现新的 Critical／Important／Minor。审查仅阅读源码、测试与 diff，未访问真实数据或运行测试；父会话另行完成上述最新全量回归，代码复审不替代执行证据。

修正采用设置专用 spawn 子进程执行外网探测，父进程可强制终止；DNS 也在子进程内校验。合成持续慢流（读间隔小于 read timeout）测试验证截止终止及无遗留子进程；对应端点策略／进程／预览／API 定向组 30 passed，7.47 秒。导出与账户删除组 61 passed，11.93 秒。前端新增历史后退拒绝／确认导航及卸载 AbortSignal 测试通过。分组结果不累加为全量成绩。

本机虚拟环境尚未安装 openai SDK，项目依赖文件已声明；只读检查 Docker 容器 SDK 版本时 daemon 未运行。没有因此安装依赖、启动正式服务或消费真实密钥。SDK 对接仅通过合成 SDK／协议契约验证，实际供应商双项能力仍需用户显式测试，不能以 Mock 通过声称 live 验收完成。

保留现有限制：配置 CAS 与探测限流只保证单进程；不支持内网／本地模型端点，不宣称解决 DNS rebinding；双项探测不代表业务质量或完整结构化输出能力已验证。浏览器到本地后端沿用当前部署通道，远程部署必须配置 HTTPS，不能把提供商 HTTPS 检查误认为整个应用已具备端到端 TLS。

结论：M 阶段本地实现与离线验收完成；最新后端 2012 项、独立配置 6 项、前端 276 项及生产构建通过，独立复审无遗留发现，`git diff --check` 通过。尚未提交、合并、推送或部署；真实 SDK／供应商验收未执行，不能称为生产发布完成。原有无关未跟踪文件保持不变。
