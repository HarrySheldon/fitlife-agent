# C0–C4 离线交付记录

日期：2026-10-20。分支：`main`，提交：`df6fd98`，远端 `origin/main` 同为 `df6fd98`。
本记录对应主计划 `docs/superpowers/plans/2026-10-18-coach-conversation-experience.md`
的「完成判据」第 230 行与第 234 行。

## 为什么各阶段共用同一个 SHA

C0–C4 的实现从 2026-10-18 起一直留在未提交工作区，**从未按阶段分别提交**。
因此不存在"每阶段一个 SHA"的历史事实。全部内容在用户显式授权后一次性提交为 `df6fd98`，
共 169 个文件、+14257 / −650。这里如实记录"共用同一提交"，不伪造分阶段 SHA。

`df6fd98` 之前的相关提交：

| 提交 | 说明 |
| --- | --- |
| `032731c` | docs: design explicit catalog release migration |
| `f7e2318` | fix(catalog): publish localized releases without rewriting upstream versions |
| `aa63c77` | docs: record verified catalog rollout and pending remote publication |

## 分阶段对照

| 阶段 | 证据文档 | 代码 SHA | 测试报告 | 数据隔离 |
| --- | --- | --- | --- | --- |
| C0 回答契约与语言一致 | `2026-10-18-c0-answer-contract.md` | `df6fd98` | 全量 `c4-full-20261020b.xml`（2237） | 每个 fixture 独立 `tmp_path` SQLite |
| C1 持久会话／90 天／输入投影 | `2026-10-18-c1-coach-persistence.md` | `df6fd98` | 同上 | 同上 |
| C2 准入／单槽／真实取消 | `2026-10-19-c2-turn-admission.md`、`2026-10-19-c2-closeout-c3-foundation.md` | `df6fd98` | 同上 | 同上 |
| C3 统一悬浮多聊天与快捷入口 | `2026-10-19-c3-coach-experience.md` | `df6fd98` | 前端 46 文件/299；浏览器 64/64 | 浏览器用内存假数据，不连真实账户 |
| C4 离线整体验收与 S3 交接 | `coach-conversation-acceptance.md` | `df6fd98` | 16 场景 16/16；专项 33 passed | 独立评估 worker + 每场景独立 SQLite |

统一回归（2026-10-20）：

- 后端业务组 `2237 passed / 0 failed`，1596.72s，`.tmp/c4-full-20261020b.xml`
- 配置独立组 `6 passed`，`.tmp/c4-config-20261020b.xml`
- 前端 `46 文件 / 299 passed`；`VITE_COACH_CONVERSATIONS_ENABLED` true/false 两种构建均通过
- 真实 Chrome + CDP `64/64`，`.tmp/c3-browser/results.json`
- `git diff --check` exit 0，仅既存 CRLF 提示

## 风险与待授权动作

| 项 | 状态 |
| --- | --- |
| 前后端开关 | `COACH_CONVERSATIONS_ENABLED` / `VITE_COACH_CONVERSATIONS_ENABLED` 默认 false |
| 部署 | 未部署 |
| 真实模型 | 未调用；无 live 报告 |
| 正式库迁移 | 未执行 |
| 物理键盘缩放 | 未取得，仅有 CDP 指标模拟 |
| OS 中文输入法 | 未取得，仅有 composition 组件回归 |
| 真实屏幕阅读器 | 未取得 |
| S3 / S4 / S5 | **未开始**（分别 44 / 26 / 19 项未勾） |

## 已交付但默认关闭：如何查看

教练新布局（统一悬浮窗口、多聊、草稿隔离、来源、停止与重试）已完整交付并通过验收，
但**默认关闭是有意设计**（见主计划第 122、165、182 行：C0 修复不依赖换入口、保留旧入口回退、
部署归 S5 授权）。因此合并后界面不会自动变化。

不改变任何默认值的查看方式：

```powershell
docker compose -f docker-compose.yml -f docker-compose.coach.yml up --build -d
```

`VITE_*` 为构建期注入，必须带 `--build`；且需登录后才会挂载教练浮窗。详见 README 的
"Try the unified coach window" 一节。

S3–S5 不会自动翻转这些默认值：S3 会新增 `plan_adjustment_tasks_enabled=False`，
S4 默认 `reference`，S5 明确"不另给 C 提前安排生产启用"。可见性属于独立的发布决策。

## 对早期记录中"未提交"表述的更正

C0、C1、C2、C3、C4 的验收文档在撰写时都写有"未提交、未推送、未部署"，那是当时的事实。
**2026-10-20 起已更正**：代码随 `df6fd98` 提交并推送到 `origin/main`。
"未部署""未调用真实模型""未迁移正式库"三项仍然成立。
