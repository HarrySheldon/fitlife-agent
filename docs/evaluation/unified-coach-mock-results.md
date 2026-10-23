# 统一教练隔离 Mock 回放逐样本记录

2026-10-22；28/28 达到场景预期。来源：开发 checkout `.tmp/task-evaluation/unified-coach-source/report.json`，最后一次执行退出码 0。此报告生成于最终 legacy 词义兼容修复之前；该修复不改变 unified 路由，完整最终源码回归另见[验收记录](unified-coach-acceptance.md)。

以下耗时仅为本机 Mock 流程观测，不是 Provider 延迟、价格、真实缓存命中率或新旧提速。processing_ms 最近秩分位数 P50=462.9 ms、P95=988.06 ms；elapsed_ms 包含隔离进程开销，不与之混用。多个 run 的计数按报告汇总；取消中断场景可能无最终工具事件，不能解释成完整物理调用计费。已知字符估算 token 小计 102916，2项未知；无真实 Provider usage/付费成本。

| 场景 | 达预期 | 决策 | 工具尝试 | 执行 | 拒绝 | 目录命中 | 上下文峰值字符 | processing ms | elapsed ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unified-original-chest | 是 | 3 | 2 | 2 | 0 | 0 | 8412 | 592.2 | 7915 |
| unified-colloquial | 是 | 3 | 2 | 2 | 0 | 0 | 8400 | 613.46 | 7852 |
| unified-specific-question | 是 | 1 | 0 | 0 | 0 | 0 | 5702 | 476.63 | 8636 |
| unified-en | 是 | 1 | 0 | 0 | 0 | 0 | 5728 | 456.84 | 7745 |
| unified-explicit-language | 是 | 1 | 0 | 0 | 0 | 0 | 5713 | 479 | 7660 |
| unified-complete-plan | 是 | 2 | 1 | 1 | 0 | 0 | 6587 | 530.32 | 7758 |
| unified-brief | 是 | 1 | 0 | 0 | 0 | 0 | 5704 | 396.65 | 7885 |
| unified-multiturn | 是 | 2 | 0 | 0 | 0 | 0 | 5776 | 735.75 | 7722 |
| unified-owner-injection | 是 | 2 | 1 | 0 | 1 | 0 | 6102 | 456.7 | 7723 |
| unified-foreign-user | 是 | 2 | 1 | 0 | 1 | 0 | 6101 | 458.49 | 7450 |
| unified-diet-not-granted | 是 | 2 | 1 | 0 | 1 | 0 | 6135 | 461.46 | 7520 |
| unified-field-not-granted | 是 | 2 | 1 | 0 | 1 | 0 | 6096 | 478.41 | 7371 |
| unified-path-escape | 是 | 2 | 1 | 1 | 1 | 0 | 6063 | 462.9 | 7347 |
| unified-unknown-tool | 是 | 2 | 1 | 0 | 1 | 0 | 6048 | 458.15 | 7604 |
| unified-forged-confirmation | 是 | 2 | 1 | 0 | 1 | 0 | 6096 | 468.84 | 7393 |
| unified-indirect-injection | 是 | 3 | 2 | 1 | 1 | 0 | 6720 | 527.52 | 7280 |
| unified-invalid-protocol | 是 | 2 | 0 | 0 | 0 | 0 | 5786 | 388.2 | 7418 |
| unified-duplicate-call-id | 是 | 3 | 2 | 1 | 1 | 0 | 7383 | 533.84 | 7414 |
| unified-budget-stop | 是 | 10 | 10 | 1 | 0 | 9 | 17681 | 988.06 | 8665 |
| unified-oversize-output | 是 | 1 | 0 | 0 | 0 | 0 | 5702 | 417.25 | 7348 |
| unified-coach-stop-cleanup | 是 | 1 | 0 | 0 | 0 | 0 | 5824 | 2570.61 | 9647 |
| unified-coach-chat-deleted | 是 | 0 | 0 | 0 | 0 | 0 | 0 | 177 | 7179 |
| unified-coach-account-deleted | 是 | 0 | 0 | 0 | 0 | 0 | 0 | 259.05 | 7141 |
| unified-coach-retention-90d | 是 | 1 | 0 | 0 | 0 | 0 | 5824 | 416.14 | 7411 |
| unified-live-domain-revocation | 是 | 2 | 1 | 1 | 0 | 0 | 6285 | 406.39 | 7387 |
| unified-repeat-metadata | 是 | 3 | 2 | 1 | 0 | 1 | 8358 | 521.57 | 7637 |
| unified-review-unavailable | 是 | 1 | 0 | 0 | 0 | 0 | 5702 | 689.34 | 8071 |
| unified-authentication-required | 是 | — | — | — | — | — | — | 103.64 | 8519 |
