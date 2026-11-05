# C1–C4 正确性问题修补记录

范围为问题清单第 1 组的四项，而非仅 C1。位置：`codex/live-evidence-integration` 隔离工作树；基线 `main/0df22e2`。保留工作树中原有 Agent、引用和真实模型评估改动，本次没有提交、合并或推送。

## C1：Today 日期和异步响应一致

切换日期立即隐藏旧日期结果，失效请求不得覆盖新日期的数据、错误或加载状态。同日刷新保留已有结果并明确提示刷新/失败状态。教练动作与页面选定日期一致。详见 [C1 回归记录](2026-11-05-today-date-consistency.md)。这是忽略失效响应，不是取消网络传输。

## C2：计划差异完整且可理解

原先按 `zip` 遍历训练天数/餐食，遗漏数组增加和删除，也没有覆盖计划根级设置。新的确定性差异函数递归比较全部获准领域，包括数组长度变化、对象字段新增/删除、类型变化及根级设置；区分缺失值与显式 null，不读取未授权领域。

前端按领域、日期/项目名称、字段显示修改前后值，已知字段使用本地化名称和确定的单位。未知字段继续显示原名和值，避免隐藏尚未建立展示映射的变更。新增、删除、空值分别呈现；原始路径和 JSON 保留在折叠技术信息里。此展示不增加营养或训练计算，也不替代业务校验。

## C3：计划操作使用真正的模态窗口

新增共用 `Modal`，通过 portal 和原生 `dialog.showModal()` 进入浏览器顶层。原生模态负责背景不可交互；组件负责初始焦点、Tab/Shift+Tab 循环、Escape 关闭、滚动锁及关闭后恢复焦点。Escape 不再传播到外层教练窗口。打开、关闭窗口不改变执行确认与幂等语义。

DOM 测试使用仅测试环境的 dialog polyfill，验证焦点和事件行为，包括技术详情 summary 参与循环且内部 Tab 保持自然顺序；不以此声称验证了浏览器顶层或背景 inert。尝试启动本地合成数据预览，但浏览器工具连接超时，已停止预览服务。真实浏览器键盘操作、窄屏和 200% 缩放仍需人工验收。

## C4：权限缺失可恢复，不靠关键词阻断任务

统一教练聊天新增每轮明确的读取范围：基本目标档案、训练、饮食。默认没有勾选，发送显式空列表，不授予任何私有字段权限；公开知识、技能及不需要私有数据的建议仍可用。历史聊天内容仍属于当前对话上下文，界面说明此边界。

权限字段经过 HTTP schema、会话服务、运行命令一直传到可信执行主体。客户端不能设置身份或服务端策略。显式范围替代关键词推断；明确排除仍收紧权限。档案字段按所属领域校验和投影，例如训练经验只需训练授权，基本目标需要档案授权，营养目标需要饮食授权。

工具需要额外权限时，执行器在访问数据前返回 `READ_PERMISSION_REQUIRED`。工作流生成本地化说明，要求用户选择读取范围或继续获得通用建议；仍经过输出审核，不调用私有读取处理器、不自动增加权限、不授权正式写入。新的重试采用当前选择，不复用旧请求的授权。首次能力探测完成前禁用发送/重试，避免探测竞态遗漏显式范围。

兼容边界：服务端通过 `active-turn.capabilities.explicit_read_scope` 宣告是否启用此契约。统一模式支持；旧引擎拒绝携带显式范围的请求，不静默忽略。旧客户端未传字段时保留原有推断行为；本次没有切换全局默认引擎，也不声称所有旧入口已经采用逐轮授权。

## 验证过程与范围

测试使用项目 `.venv` 解释器、隔离临时数据和 mock 网关；没有读取正式数据库或调用真实模型。

- 修改过程中，jsdom 缺少 `showModal` 导致测试失败，增加测试专用 polyfill；原始 JSON 引号断言改为可读展示断言。
- 双 worker 全量曾出现既有 SmartEntry 混合训练输入时序失败；该套件单独 7 项通过，后续改用单 worker 全量。
- 收口回归发现新测试在会话选定前点击授权，随后会话切换按设计清空选择；已让测试先等待对应会话标题。另一新测试遗漏英文按钮中的 `a`，已修正。
- 后端既有注册表断言仍要求饮食字段额外授权 profile；已按字段归属契约改为参数化检查，覆盖单领域及跨领域组合，并保留实际字段投影/未授权禁止调用的行为测试。
- 全量运行期间补充 summary 焦点用例，使该轮出现测试新版本与先前缓存组件版本不一致的失败；定向重新启动后通过。最终证据采用停止修改代码后重新启动的完整回归。
- 只读独立审查复核了显式空范围、字段归属、重试和能力探测边界，未发现具体缺陷；审查不代替测试。

最终后端：统一教练全套、计划差异和教练会话 API，**137 项通过、1 项跳过**，123.76 秒。保留既有 Starlette/httpx 弃用告警。

最终焦点/授权定向：Modal 与 CoachWindow **2 文件、8 项通过**，6.29 秒。

最终前端全量：**52 文件、333 项通过**，155.80 秒，exit 0。TypeScript 检查和 Vite 生产构建通过，构建 11.39 秒；保留大于 500 kB 的既有 bundle 告警，未把本次正确性修补扩展为拆包工程。

`git diff --check` 通过；主 checkout `main` 保持干净。上述后端与前端数字属于各自最后一次回归，不累加重叠用例。

未完成的验收仅为上述真实浏览器人工检查及真实模型端到端体验，不将它们计为已通过。主 checkout 保持干净，不合并工作树数据。

## 复验命令

以下命令从隔离工作树运行，不启动服务，也不调用真实模型：

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\live-evidence-integration'
$env:DATA_DIR = Join-Path (Get-Location).Path '.tmp/correctness-recheck-data'
Remove-Item -LiteralPath Env:SQLITE_DATABASE_PATH -ErrorAction SilentlyContinue
$env:LLM_ENABLED = 'false'
& 'D:/code/vibe-coding/fitlife-agent/.venv/Scripts/python.exe' -m pytest --version
if ($LASTEXITCODE -ne 0) { throw 'pytest unavailable' }
& 'D:/code/vibe-coding/fitlife-agent/.venv/Scripts/python.exe' -m pytest backend/tests/unified_coach backend/tests/domain/test_plan_diff.py backend/tests/test_coach_conversation_api.py -q --basetemp=.tmp/correctness-recheck
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
Set-Location -LiteralPath frontend
node node_modules/vitest/vitest.mjs run --maxWorkers=1
if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
```
