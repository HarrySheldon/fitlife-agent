# 连接测试业务化：执行与验收

日期：2026-10-18。分支 `codex/model-connection-workflow`。用户已确认单一连接测试并要求直接在当前分支修改；不创建分支／工作树，不提交／合并／推送，不访问真实模型密钥或正式数据库。

## 已实现

- 页面一个「测试连接」按钮，整体成功／连接失败／业务解析失败，技术详情默认折叠；变更失效、取消等待、离页保护不变。
- 内部基础生成＋固定合成 `oats 40 g` 解析，最多两次调用，共享 30 秒，每次128输出 token；生成失败不执行第二次，失败不签发凭证。
- 自定义服务实际 Planner／结构化业务和探测共用普通 JSON 文本＋本地 Pydantic 校验，没有 tools/tool_choice/原生 response_format 要求；实际官方连接保持原生解析。业务模型仍逐次校验、安全审核，没有猜测修复或隐式重试。
- DeepSeek 精确 hostname 使用 max_tokens 作为探测输出限制，不切 URL、不自动换协议／模型。不能据此宣称真实 DeepSeek 已验收。
- 凭证升级 generation-structured-v2，旧工具凭证拒绝；新增 structured_status，tool_status保留历史，不伪造工具通过。旧 active不被自动停用，账户导出白名单包含新状态，不返回密钥／指纹／凭证。

## 实际验证

RED：新增定向套件最初 14 failed / 25 passed，原因是缺 probe_structured 和旧凭证仍被接受，并非外网问题。实施后同组加既有协议契约 50 passed，4.20 秒。

| 检查 | 实际结果 |
| --- | --- |
| 新旧协议、探测／凭证、工作区／API闭环、导出、安全投影、超时 | 110 passed，17.03 秒，exit 0；`.tmp/connection-business-check-focused-20261018.xml` |
| 复审补充的地址分流／官方 native 探测及相关协议凭证套件 | 57 passed，2.35 秒，exit 0；`.tmp/connection-business-check-review-matrix-20261018.xml`；仅新增测试，不改变被全量测试的实现 |
| 前端全量 | 42 files / 278 passed，30.04 秒，exit 0 |
| 中断后重新确认 TypeScript／Vite 构建 | exit 0，Vite 14.37 秒，既有超过500kB包体警告 |
| 配置优先级独立分组 | 6 passed，1.83 秒，exit 0；`.tmp/connection-business-check-config-20261018.xml` |
| 后端修订后完整业务分组 | 2026 passed，877.76 秒（14分37秒），exit 0，1项既有 Starlette/httpx 弃用警告；`.tmp/connection-business-check-full-20261018.xml` |
| 独立只读复审 | 未发现可确认的 P1/P2 缺陷；提出的非阻断覆盖缺口已补充并经再次只读核对关闭，无新增发现 |

后端完整测试使用新的 `.tmp/connection-business-check-full-20261018` 合成目录、SQLITE_DATABASE_PATH空覆盖、LLM_ENABLED=false，并覆盖样本生成器DATA_DIR；配置分组在独立进程移除DATA_DIR/SQLite覆盖。测试 SDK／DNS 采用合成注入；没有启动正式服务、读取真实账户配置、调用用户密钥或迁移正式库。前一版全量成绩只作历史。

审查仅阅读源码、测试和文档，不运行测试、不读取敏感配置或数据。补充矩阵覆盖 actual official/provider 与第三方地址分流、custom 官方地址、DeepSeek 精确 hostname及相似域名不匹配；两个协议 native probe 明确走同一 parse_structured，校验128限额和 contextvar恢复。矩阵在全量收集后添加，因此分别报告，不将重叠套件数字累加为总成绩。

## 交付状态

本地实现与离线验收完成，`git diff --check` 通过。保持在当前开发分支，未提交、合并、推送或部署；用户无关文件未修改。启动当前代码需用户重新执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1`，脚本会重建前后端。真实 DeepSeek 仍需用户显式点击测试；此次自动化不能证明真实供应商验收通过。

## 边界

探测不是完整业务质量或医疗安全证明，所有业务结果继续独立校验；复杂任务可能仍失败。凭证、文件CAS和限流仍为当前单进程部署设计。真实 SDK／供应商尚未验收；本机未安装openai SDK的事实仍保留，Docker依赖按requirements安装。本轮不自行安装新依赖或消费真实模型费用。
