# 真实模型验收包交接记录

本批从2026-11-04开始，跨日至2026-11-05完成验证。基于 `codex/live-evidence-integration` 的既有未提交接线继续实施，未新建分支、迁移数据库、推送或执行真实Provider。

## 交付内容

- `python -m backend.task_evaluation.operator prepare/check/run`：前两步不读取密钥或创建授权，最后显式 `--confirm-live` 后才产生绑定批次的控制台授权。隐藏输入密钥，结束恢复环境；独占run标记阻止重复消费同一批次。
- 单场景 `live_probe.json` 与六场景 `live_acceptance.json`，全部合成，无脚本化模型答案，人工标注初始unknown。
- 显式capture_review纳入配置指纹，保存primary账户的已发布问答以及受控turn状态/错误码；原脱敏计量报告不带回答正文。
- [完整PowerShell命令与人工判定清单](live-model-operator-guide.md)。首次先执行单场景，再由操作者决定是否批准六场景预算。
- 发现并修复detailed训练建议输出额度超过RPC上限的问题：代理使用不超过8192的实际额度，并绑定指纹；输入预算仍包含固定指令/schema。

## 验证与边界

pytest 9.1.1，使用主checkout现有解释器，在隔离工作树 `.tmp` 合成目录运行。初次47项中2项失败：一个揭示详细请求RPC额度不兼容，另一个为测试错误地认为默认脚本列表为None；修正后46项通过、1项因Windows默认GBK读取UTF8测试文件失败，已显式指定UTF8。保留失败过程，不将其写成全绿。

最终相关回归 **59 passed，1 warning，212.77秒，exit 0**。命令为 `pytest backend/tests/task_evaluation/test_operator.py backend/tests/task_evaluation/test_live_integration.py backend/tests/task_evaluation/test_cli.py backend/tests/task_evaluation/test_runner.py`。之后增加来源映射后，operator组再验 **7 passed，21.06秒，exit 0**，包括真实知识工具与假模型串联的引用发布/审阅闭环。两组有重叠，不合计为独立样本数；本批未重跑全项目或前端测试。

PowerShell命令实际执行prepare/check smoke通过：无密钥、无authorization、无run标记、Provider调用0。只读独立审查未发现新的确定重要问题；未读真实配置或数据库，不替代运行证据。

文档链接及 `git diff --check` 通过。主checkout仍为干净main，所有新增改动保留在隔离工作树，未提交或合并。

本批只交接当前统一Agent的真实模型生成、工具使用、业务边界及引用行为评估。教练检索仍为hashing，不标记真实语义embedding或S5完整真实验收完成。应用默认切换、legacy退役和正式迁移仍在后续阶段。
