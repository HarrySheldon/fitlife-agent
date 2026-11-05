# 真实模型验收交接 Implementation Plan

**Goal:** 操作者可在隔离工作树准备批次、检查本地事实，明确确认后隐藏输入密钥并运行；能够看到实际回答作人工判断。

**Architecture:** 复用现有准入、父进程Broker、合成worker和报告；不建立第二套模型调用路径。操作工具只负责编排与一次性批次授权；显式审阅采集单独落本地文件，不扩大标准报告内容。

**Tech Stack:** Python argparse/getpass/Pydantic、现有task_evaluation、pytest、PowerShell操作命令。

- [x] 核查原live入口与标注协议，识别临时数据清理后无法审阅回答的缺口。
- [x] 增加单场景probe及六场景初步验收集，全部合成，无脚本化模型答案；确定性断言只检查流程，语义标签默认unknown。
- [x] 增加prepare/check/run操作入口；只有显式 `run --confirm-live` 才创建绑定manifest的授权，密钥不落盘，同批次不重复消费。
- [x] 显式capture_review纳入manifest，收集primary合成账户已发布问答并写独立审阅文件，标准报告继续只含脱敏计量。
- [x] 完成假Provider闭环回归、独立只读审查与可复制命令，记录证据：相关59项通过；最新交接组7项通过；prepare/check PowerShell smoke通过。[交接记录](../../evaluation/2026-11-05-live-evaluation-handoff.md)。
- [ ] 操作者执行真实probe，人工核对任务完成、安全与引用；之后再选择六场景验收预算。本会话不执行真实调用。

本批评价当前统一Agent的真实生成/工具使用/可检查引用；教练检索仍固定hashing，不能标记真实语义embedding验收完成。RAG语义模型替换及独立embedding基准不混入本批。
