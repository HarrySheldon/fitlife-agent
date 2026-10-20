# 连接测试业务化 Implementation Plan

> **For agentic workers:** Use executing-plans in the current branch. 用户已确认单一测试连接交互并要求直接实施，不创建分支／工作树、不提交、不调用真实密钥。

**Goal:** 用基础生成和最小业务 JSON 校验替代原生工具调用准入，只向用户展示整体连接结果。

**Architecture:** 保留 active/draft、CAS、15 分钟配置绑定凭证和可终止探测进程。新增 structured 状态；tool_status 只作为旧记录历史字段，不再被标为通过。凭证版本升级为 generation-structured-v2，旧凭证拒绝，已启用连接不被自动停用。自定义兼容服务的结构化业务和探测共用 JSON 文本＋本地 Pydantic 校验；既有官方原生解析路径保留，不因失败自动回退。DeepSeek 精确 hostname 配置使用 max_tokens；不改 URL、不换模型、不重试。

**Tech Stack:** FastAPI/Pydantic/pytest、React/TypeScript/Vitest。

## 用户已确认的设计与范围

仅删除工具门槛会漏检 Planner／录入依赖；继续展示两种能力增加用户理解负担。因此采用一个「测试连接」按钮，内部最多两次合成请求，30 秒共享期限，128 输出 token／请求。第二次提取固定合成文本 `oats 40 g`，校验对象字段、类型及值；不发送真实健康信息。普通页面只显示整体成功／连接失败／业务解析失败，折叠详情保留阶段、耗时、脱敏错误码。测试通过不保证所有业务质量，每次业务仍独立校验和安全审查。

原生严格协议不是自定义服务准入要求。为避免探测与业务不一致，兼容服务通过同一 parse_structured 方法使用普通生成接口、提示 schema 和本地验证。官方连接保持既有原生解析；不把第三方地址因 provider=openai 而误当官方。运行时 JSON 类型校验沿用既有业务模型规则，不新增类型猜测、输出修复或模型额外调用。探测 schema 使用 strict/extra=forbid 拒绝错误和多余字段。

## 执行检查点

- [x] 1. 添加失败测试：无 tools/tool_choice/原生 response_format 也可完成业务探测；坏 JSON、错误字段／类型／值拒绝；DeepSeek 使用 max_tokens；实际兼容 Planner 与结构化业务共用解析；旧工具凭证拒绝。
  Files: backend/tests/test_model_connection_probes.py、tests/infrastructure/test_model_verification.py。
  Run: `.venv\Scripts\python.exe -m pytest --version` 后运行上述套件。Fake SDK，不访问外网。
- [x] 2. 实现共享最小业务 probe schema、协议 JSON 兼容路径和明确的 factory 配置；将 settings 进程操作改为 structured，更新凭证、状态、导出。保留旧工具 API 仅供内部旧契约，不用于新启用流程。
  Files: backend/domain/model_connection_probe.py（新）、infrastructure/model_gateway/structured_json.py（新）、两个 Adapter、factory.py、preview_process.py、model_connection_preview.py、model_connection_workspace.py、model_connection.py、model_verification.py、export_account_data.py、settings.py。
- [x] 3. 更新前端 result 类型、hook 和统一结果 UI、折叠详情、zh/en 文案。失败不能启用，变更失效／取消等待规则不变。
  Files: frontend/src/types/index.ts、hooks/useModelSettings.ts、pages/settings/ModelSettings.tsx、对应测试及 i18n 资源。
  Run: `npm --prefix frontend test -- src/pages/settings/ModelSettings.test.tsx src/hooks/useModelSettings.test.tsx`。
- [x] 4. 同步 API／导出／离线验收 Fake，运行后端定向及全量隔离回归、配置独立分组、前端全量与构建、git diff --check。更新 README、任务契约、原设计与执行记录；原验收成绩只作历史。

## 最终结果

2026-10-18 本地实现和离线验收完成：后端完整业务2026项、配置独立分组6项、前端278项通过，生产构建通过；独立复审无遗留发现，补充的工厂／原生解析矩阵及相关协议凭证套件57项通过（与全量分别记录，不累加）。证据见 `docs/evaluation/2026-10-18-connection-business-check.md`。未提交、合并、推送或部署；真实供应商仍未实测。

验证环境 DATA_DIR 使用新的忽略 .tmp 子目录，SQLITE_DATABASE_PATH 空覆盖允许旧 fixture 隔离；样本生成器先覆盖其 DATA_DIR 常量；LLM_ENABLED=false。配置测试单独进程移除 DATA_DIR/SQLite 环境，不读用户密钥、不修改正式数据库。没有生产 schema migration，不要求用户重填已有连接。上线仍需用户重新构建及显式实测，Mock 不作为真实供应商验收。
