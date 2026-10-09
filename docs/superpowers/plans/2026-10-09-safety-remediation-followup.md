# 2026-10-09 安全计划补齐验证

## 范围与状态

基线 `15c877c`，分支 `codex/agent-runtime-refactor`。本次改动尚未提交或推送。
修复前三项计划的生产接线遗漏，不实施第四项统一安全架构重构，不更改 off / legacy 默认配置。

1. graph 正式入口复用已解析且符合 StructuredModelGateway 的模型连接；显式 override 优先。无需调用方另行传入私有参数即可开启审核和证据模式。
2. run_structured_agent 创建工作流时固定审核模式；结构化结果先执行规则审核，随后通过 Runtime 调用语义审核。shadow 只记录；enforce 拒绝不返回候选对象；普通 Provider 故障保持规则处置；Runtime 终止信号由共享 collector 原样传播。
3. 普通回答的审核模型看到规则处理后的文本，但 enforce 重新审核原始草稿，避免重复追加免责声明。shadow 返回第一次规则结果，不二次处理正文。
4. 原有 60 条 reviewer、45 条 grounding 合成样本已在基线提交中存在，本次保留并随全套测试验证。

## 回归证据

解释器：`D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe`；已先验证 pytest 9.1.1。
工作目录：`D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor`。
测试不调用真实模型。由于此前沙箱临时目录权限问题，本次测试获准在沙箱外执行。

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests/test_safety_public_wiring.py -q -p no:cacheprovider --tb=short
```

修复前：5 failed, 1 passed，退出码 1。失败分别对应 shadow 没发请求、enforce 无模型连接、evidence 无模型连接、结构化 shadow 没审核、结构化 enforce 未拒绝。

修复后与已有 review_entry / review_integration 联跑：32 passed，退出码 0。

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests -q -p no:cacheprovider --tb=short
```

结果：1498 passed, 1 warning in 458.06s，退出码 0。警告为既有 Starlette/httpx 弃用提醒。
全套收集后又增加两条 Provider 故障回归，因此新增文件最终单独重跑为 8 passed（退出码 0）；不将这两条虚报为该次全套统计的一部分。生产代码在全套开始后未再修改。

独立只读复核：三个目标符合范围，未发现实现缺陷。额外覆盖建议包括显式 override 优先级和结构化入口的终止信号集成测试；已有共享 collector 测试覆盖终止传播，本次未宣称穷尽测试。

## 尚未执行

- 真实 Provider 评测、费用/延迟测量、真实模型误拒率/漏检率。
- enforce / evidence 的生产灰度启用。
- Git 提交、推送或合并。

因此可交付结论是：本次核查发现的三个代码缺口已修复并通过回归；不是“整个安全系统完备”或“真实模型达到发布门槛”。真实模型调用需用户确认费用与数据发送，部署开关保持不变。
