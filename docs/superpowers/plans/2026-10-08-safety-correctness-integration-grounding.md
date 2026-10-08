# 安全处置正确性、模型审核接入与数值证据校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 经用户明确选择后，也可使用 superpowers:subagent-driven-development。Steps use checkbox (`- [ ]`) syntax for tracking. 本环境技能名称可能不带 `superpowers:` 前缀，应使用实际安装的对应技能。

**Goal:** 修复附加审核失败时丢失既有安全处置的问题，完成可配置、可观测的羞辱语义审核接入，并以具备指标、单位和时间语义的证据替代裸数字集合匹配。

**Architecture:** 保留现有安全检测、YAML 策略、Runtime 和公开响应协议。阶段 A 统一执行已确定的安全动作；阶段 B 在现有工作流内通过 Runtime 调用独立语义审核；阶段 C 为数值分析引入证据目录和内部结构化回答，关键数字由确定性代码渲染。三个阶段分别测试、验收和提交，不进行第四项“统一安全执行架构”的重构。

**Tech Stack:** Python、Pydantic、pytest、现有 OpenAI Responses / Chat Completions Adapter、AgentRuntime、YAML 规则包；不新增 Guardrails 框架或数据库迁移。

---

## 0. 文档状态与执行边界

- 日期：2026-10-08。
- 基线提交：`448d5df`，分支：`codex/agent-runtime-refactor`。
- 工作树：`D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor`。
- 本文是待执行计划，不表示代码已经修复，也不表示测试已经通过。
- 本次仅创建文档。执行计划须另获用户授权；实际提交、联网模型评测和部署也须遵守用户授权范围。
- 不修改主仓库中的 `.tmp_lexicon_terms.txt`、`research-false-positive-safety-classifiers.md`、`research-safety-risk-gating.md` 或其他用户改动。
- 下文文件路径均相对上述工作树；PowerShell 命令在上述工作树根目录执行。
- 三个独立交付单元：A 处置修复；B 审核接入；C 数值证据。B 依赖 A；C 可独立开发，但最终集成须使用 A 修复后的输出处置。

### 不在本次范围

不重构所有工作流的强制安全入口；不更换完整 Repository 为只读 Adapter；不扩展上下文扫描范围；不实现外链/DLP、后台任务或人工接管；不训练安全模型；不承诺医学事实核查。不得顺手实施这些项目。

### 阅读代码时发现的相邻风险

当前 `FitLifeWorkflow._writer` 记录 `writer_payload`，但调用 `gateway.write_answer(state)`；两个生产 Adapter 又调用 `writer_payload(state)` 重新组装数据。应单独核验实际请求是否使用了清理后的载荷。此项属于第四类集成/执行约束问题，不在本文修复范围，不能因完成本文就宣称上下文注入防护完整。阶段 C 新增证据载荷必须测试真实 Adapter 的发送内容，不能复制这种“检查一份、发送另一份”的模式。

## 1. 问题与可验证目标

| 编号 | 当前证据 | 修改后必须满足 |
| --- | --- | --- |
| A | `backend/safety/gate.py::review_output` 的 reviewer 异常分支在 severity < 6 时直接返回 draft，跳过后续动作分派；同时只取 `_with_caveat(...)[0]`，可能丢掉更新后的 verdict | 审核失效不得取消确定性策略的 mask/disclose/refuse/escalate；正文与 verdict 一致 |
| B | `backend/agent/graph.py::_LazyFitLifeWorkflow.execute` 未注入 reviewer；`backend/safety/review.py` 定义了模型审核契约，但生产 Adapter 未提供 `judge_review` | 生产入口可配置开启，Mock 可复现调用，真实模型调用受 Runtime 预算/截止时间限制，并能确认 disabled/shadow/enforce 状态 |
| C | `backend/safety/groundedness.py::supporting_values` 收集所有数字并枚举两两和差与百分比；`check_groundedness` 不核对指标、日期、单位 | 体重 70 不能支撑蛋白质 70g；跨日数据不能冒充今日；缺记录不等于摄入为零；未经授权的跨指标计算不能作为依据 |

验收分为“程序契约测试”与“真实模型效果评测”。前者通过不能代替后者；报告不得把 Mock 的通过率描述为模型安全率。

## 2. 修改文件地图

### 阶段 A

- 修改 `backend/safety/gate.py`：去除 reviewer 失败后的提前放行，共用已有动作处理出口。
- 修改 `backend/tests/test_safety_model_review.py`：覆盖失败、非法返回、确定性动作不降级。
- 修改 `backend/tests/test_safety_actions.py`：低严重度自定义策略与正文/verdict 一致性。

### 阶段 B

- 修改 `backend/config.py`：增加审核模式配置。
- 修改 `backend/safety/review.py`：增加严格的审核输出模型和结构化网关 Adapter；保留已有 reviewer 契约兼容性。
- 新增 `backend/agent/semantic_review.py`：异步调用编排、模式处理和固定结果 Adapter；不承担规则检测。
- 修改 `backend/agent/graph.py`、`backend/agent/workflow.py`、`backend/agent/structured_workflow.py`：传递模式并接入。
- 修改 `backend/agent/runtime.py`、`backend/agent/persistence.py`：受控工具名与审核诊断字段。
- 修改 `backend/tests/test_safety_model_review.py`、`backend/tests/test_configuration.py`。
- 新增 `backend/tests/test_safety_review_integration.py`。

### 阶段 C

- 新增 `backend/safety/evidence.py`：证据类型、目录与合法派生计算。
- 新增 `backend/agent/grounded_answer.py`：内部回答模型、引用解析、固定标签渲染和受限回退。
- 修改 `backend/agent/state.py`、`backend/agent/model_payloads.py`、`backend/agent/workflow.py`：证据传递、受控 Writer 分支、渲染后审核。
- 修改 `backend/infrastructure/model_gateway/openai_responses.py`：共享的 grounded Writer 指令；两种 Provider 复用已有 `parse_structured`。
- 修改 `backend/safety/groundedness.py`：明确旧检查为 legacy heuristic，生产证据路径不再使用任意两两派生。
- 新增 `backend/tests/test_safety_evidence.py`、`backend/tests/test_grounded_answer.py`。
- 修改 `backend/tests/test_safety_groundedness.py`，新增 `backend/tests/test_grounded_answer_integration.py`。
- 新增 `backend/tests/fixtures/safety/grounding_cases.json`、`backend/tests/fixtures/safety/reviewer_cases.json`：合成且不含真实用户信息的评测样本。

### 最终文档

- 更新 `docs/SAFETY_LAYER_DESIGN.md`：实际启用状态、数字验证覆盖、故障语义。
- 新增 `docs/superpowers/plans/2026-10-08-safety-remediation-verification.md`：执行时填写原始命令、退出码、计数、失败和限制；本次不提前创建成功报告。

## 3. 基线与 Windows 命令约定

主仓库 `.venv\Scripts\python.exe` 已确认存在；工作树当前没有独立 `.venv`。使用该解释器运行工作树中的测试，不修改或安装主仓库环境依赖。解释器共享不等于源码共享，测试前验证实际导入路径。

```powershell
Set-Location -LiteralPath 'D:\code\vibe-coding\fitlife-agent\.worktrees\agent-runtime-refactor'
$projectPython = 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe'
git status --short --branch
git rev-parse HEAD
& $projectPython -m pytest --version
& $projectPython -c "import backend.safety.gate as g; print(g.__file__)"
```

预期：pytest 可加载，模块路径位于当前工作树。解释器缺包或导入主仓库时先停止定位，不换用裸 `python`，不擅自安装依赖。

- [ ] 保存基线输出与 HEAD。
- [ ] 定向运行现有安全测试；记录既有失败，不将其归为新修改。

```powershell
& $projectPython -m pytest backend/tests/test_safety_actions.py backend/tests/test_safety_model_review.py backend/tests/test_safety_groundedness.py backend/tests/test_safety_context_wiring.py backend/tests/test_safety_guard_contract.py backend/tests/test_safety_write_invariant.py -q
```

- [ ] 确认测试配置不会访问真实用户数据库或真实 Provider；真实模型评测另行授权。
- [ ] 如临时目录权限失败，使用新建的工作树内专用临时目录，不删除已有 `.pytest_tmp*` 或 `.tmp_pytest` 目录。

## 4. 阶段 A：审核失败不能丢失确定性处置

### Task A1：增加最小失败用例

**Files:** `backend/tests/test_safety_model_review.py`、`backend/tests/test_safety_actions.py`。

- [ ] 增加以下核心回归测试。这里用 monkeypatch 固定判定，是为隔离“处置流程”，不依赖词库是否命中某句话。

```python
import pytest
from backend.safety import gate
from backend.safety.models import Verdict

class BrokenReviewer:
    def review(self, question, draft):
        raise OSError("review service unavailable")

@pytest.mark.parametrize("action", ["mask", "disclose", "refuse", "escalate"])
def test_review_failure_preserves_low_severity_action(monkeypatch, action):
    verdict = Verdict(
        detected=True, filtered=True, action=action, severity=3,
        concern="clinical_territory", modifiers=(), evidence_spans=((0, 2),),
    )
    clean = Verdict(False, False, "allow", 0, None, (), ())
    decisions = iter(((clean, None), (verdict, "generic")))
    # 第一次是问题侧检查，第二次才是草稿处置。
    monkeypatch.setattr(gate, "_decide", lambda *args: next(decisions))
    if action in {"refuse", "escalate"}:
        with pytest.raises(gate.SafetyRefusal):
            gate.review_output("普通问题", "原始草稿", reviewer=BrokenReviewer())
    else:
        result = gate.review_output("普通问题", "原始草稿", reviewer=BrokenReviewer())
        assert result.verdict.action == action
        assert result.text != "原始草稿"
```

该测试只固定两次 `_decide` 的返回，不替换实际 mask/disclose 实现。现有词库端到端用例继续保留，避免所有测试都只验证假判定。

- [ ] 增加 `allow`、`annotate` 保持正文用例；增加 severity=6 审核失败保持拒绝用例。
- [ ] 增加 reviewer 返回 dict、非法 category、`rewrite` 的契约用例：不支持的语义审核动作视作 invalid，不得被静默当 allow。
- [ ] 增加 groundedness 触发提示时正文与 verdict 同步更新用例。
- [ ] 运行以下命令，预期新回归用例在修改前因“未遮盖/未提示/未拒绝”失败，而不是 import 错误。

```powershell
& $projectPython -m pytest backend/tests/test_safety_model_review.py backend/tests/test_safety_actions.py -q
```

### Task A2：删除异常分支的提前返回

**Files:** `backend/safety/gate.py`。

- [ ] 将异常分支的低严重度 `return ReviewResult(...)` 删除，让控制流进入已有统一动作分派。
- [ ] 将 `if decision.outcome == "refuse"` 移入审核成功的 `else`，避免异常后使用未赋值的 decision。
- [ ] 保持输入前置拒绝和高严重度审核不可用拒绝，不修改 YAML 阈值。

保留 try 中现有严格重建与受控字段校验，将 except/else 改成以下代码；其后保留现有统一动作分派：

```python
except Exception:
    if verdict.severity >= REVIEWER_FAILCLOSED_SEVERITY:
        unavailable = Verdict(
            True, False, "refuse", verdict.severity, "review_unavailable",
            verdict.modifiers, verdict.evidence_spans,
            rule_version=verdict.rule_version,
            matched_patterns=verdict.matched_patterns,
            source="review_unavailable",
        )
        raise SafetyRefusal(
            unavailable, question, notice=active_messages.notice("*")
        ) from None
else:
    if decision.outcome == "refuse":
        raised = Verdict(
            True, True, "refuse", max(verdict.severity, 3), verdict.concern,
            verdict.modifiers, verdict.evidence_spans,
            rule_version=verdict.rule_version,
            matched_patterns=verdict.matched_patterns,
            source="review", review_category=decision.risk_category,
        )
        raise SafetyRefusal(raised, question, notice=active_messages.notice("*"))
```

在原 try 的严格校验之后增加 `if decision.outcome not in {"allow", "refuse"}: raise ValueError("Unsupported reviewer outcome")`，使不支持的 rewrite 进入既有故障处置。没有必要为这次修复创建新的策略框架。

- [ ] 复跑 A1 命令，预期全部通过；不得以删除原有高风险用例达到通过。
- [ ] 回归 `backend/tests/test_agent_safety.py` 和结构化安全测试，确认拒绝错误协议未改变。
- [ ] 检查 diff 仅影响异常处置与测试。建议提交：`fix(safety): preserve deterministic actions when review fails`。

**阶段 A 验收：** reviewer 缺失、失败、非法返回或 allow 都不能放松已有动作；追加提示后 verdict 与正文一致；错误正文和密钥不泄露。

## 5. 阶段 B：正式接入受 Runtime 管理的语义审核

### 行为决策

1. 配置 `safety_review_mode: Literal["off", "shadow", "enforce"] = "off"`。默认 off 保持部署费用兼容；正式接入通过 shadow/enforce 配置验收，不能用“默认关闭”掩盖未接线。
2. 第一版复用用户已配置的结构化模型连接，不新增凭据，不支持用户通过提问关闭审核。
3. 审核范围仅为羞辱/贬低用户；不宣称其核对医学事实。结构化建议也审查序列化候选对象，但不能用散文替换对象。
4. shadow：记录 would_allow/would_refuse，不改变业务输出；enforce：refuse 收紧处置。
5. 普通 Provider 故障使用阶段 A 的规则降级；Runtime 取消、总超时、预算耗尽必须原样传播，不能伪装成“审核不可用后放行”。
6. 缺少结构化能力：off 不调用；shadow 记录 unsupported；enforce 在模型调用前返回 `CONFIGURATION_INVALID`，不静默跳过。

### Task B1：建立结构化审核 Adapter

**Files:** `backend/safety/review.py`、`backend/tests/test_safety_model_review.py`。

- [ ] 新增模型输出类型，限定只有两种合法配对，不直接让模型填写完整 SafetyDecision。

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator

class ReviewVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    outcome: Literal["allow", "refuse"]
    risk_category: Literal["low", "harassment"]

    @model_validator(mode="after")
    def check_pair(self):
        if (self.outcome, self.risk_category) not in {
            ("allow", "low"), ("refuse", "harassment")
        }:
            raise ValueError("Invalid review verdict pair")
        return self
```

- [ ] 在同文件增加 `StructuredReviewAdapter`，使用现有 `StructuredModelGateway.parse_structured`；输入用 `json.dumps({"question": question, "draft": draft}, ensure_ascii=False)`，instructions 使用现有 `REVIEW_INSTRUCTIONS`。返回 `StructuredModelResult`，由调用方读取 usage 和 output。
- [ ] Fake gateway 验证 response_model 为 ReviewVerdict、instructions 独立于 draft；测试额外字段、rewrite、错误类型、错误配对被拒绝。
- [ ] 运行 `test_safety_model_review.py`，先红后绿。保持原 `ModelSafetyReviewer` 测试继续可用，不强制所有 ModelGateway 新增方法。

### Task B2：编排一次受预算约束的审核调用

**Files:** 新增 `backend/agent/semantic_review.py`；修改 Runtime 工具白名单与 persistence 受控字段。

- [ ] 新增内部 `ReviewObservation`：mode、status（disabled/allow/refuse/unavailable/unsupported）、decision（可空）。不保存原始问题、草稿或异常文本。
- [ ] 新增 `async collect_review(context, gateway, mode, question, draft)`。off 直接返回 disabled；其他模式先消耗实际 JSON 输入和审核指令的估算预算，再经以下方式调用：

```python
result = await context.tool(
    "safety_review_model", "safe",
    lambda: adapter.review(question, draft),
)
context.consume_output(result.output.model_dump_json())
```

- [ ] Adapter 的结构化输出验证位于受控调用内；实际 usage 可用于诊断，预算沿用现有估算语义，不重复扣除 Provider usage。
- [ ] 捕获顺序固定为先重抛 `RunCancelled/RunTimedOut/BudgetExceeded`，再将其他 Provider 异常转换为 unavailable。不得在同步 `gate.review_output` 内直接启动网络调用。
- [ ] 将 `safety_review_model` 添加到 Runtime 和 persistence 工具名 allowlist；添加受控的 `review_mode`、`review_status` 字段验证。继续拒绝任意字符串和原始异常。
- [ ] 增加单元测试：off=0次、shadow/enforce=1次逻辑审核；重试次数按 Runtime 策略计入 model_calls；总预算不足不发请求；取消/超时不会返回成功。
- [ ] 执行 `backend/tests/test_safety_review_integration.py`，检查 token/tool/model 计数与事件，不只检查最终字符串。

### Task B3：接入生产入口与两条工作流

**Files:** config、graph、workflow、structured_workflow、semantic_review、配置测试与集成测试。

- [ ] 配置加入 Settings 并测试合法三值与非法值拒绝。mode 在一次工作流开始时固定，不能每一步重新读环境变量。
- [ ] graph 创建 FitLifeWorkflow 时显式传入 mode；`run_structured_agent` 创建 StructuredSuggestionWorkflow 时也传入 mode。
- [ ] 普通输出 `_review` 先确定性审核并得到有效草稿：原策略已拒绝则不调用模型；之后 `collect_review`；enforce 时用一个只返回固定 decision 的同步 Adapter 接入现有 gate，unavailable Adapter 只抛受控异常以复用 A 的降级语义。shadow 不影响最终处置。
- [ ] 同一回答避免重复追加免责声明：第二次 gate 使用原始 draft 和原始问题重新计算，禁止把第一次已经加过提示的文本再次当原始草稿。审核模型看到的是第一次规则处置后的可发布文本。
- [ ] 结构化输出继续先类型验证；规则要求 rewrite 时仍拒绝，不拼接文本；enforce 拒绝同样抛 SafetyRefusal。
- [ ] 入口集成测试必须调用 graph/run_structured_agent，并在 Fake Provider 上断言审核请求实际发生，禁止仅实例化 FitLifeWorkflow 直接注入假 reviewer 当作接入证明。
- [ ] 确认 Mock/evaluation 可显式 off；测试用例声明其模式，避免全局默认变化导致网络访问。

最低测试矩阵：

| 路径 | mode / 返回 | 预期 |
| --- | --- | --- |
| 普通问答 | off | 无审核请求，有 disabled 状态 |
| 普通问答 | shadow/refuse | 保留规则审核结果，记录 refuse |
| 普通问答 | enforce/refuse | 拒绝，分类 harassment |
| 普通问答 | enforce/allow | 原 mask/disclose 不丢失 |
| 普通问答 | Provider 失败 | 普通风险按 A 降级，不泄露异常 |
| 任一路径 | Runtime 超时/取消/预算耗尽 | 对应运行终态，不降级成功 |
| 结构化建议 | enforce/refuse | 不返回候选对象，不写业务数据 |
| 缺能力网关 | enforce | CONFIGURATION_INVALID |

```powershell
& $projectPython -m pytest backend/tests/test_safety_model_review.py backend/tests/test_safety_review_integration.py backend/tests/test_configuration.py backend/tests/test_safety_actions.py -q
```

- [ ] 建议分别提交 Adapter、Runtime 编排、生产接入三个小提交；不要一起调整危险内容策略。

**阶段 B 验收：** 两种 Provider 通过现有 parse_structured 工作；两条工作流均有入口级证据；配置与诊断可区分“没开启”和“开启但失败”；不产生额外业务写入。

## 6. 阶段 C：指标证据，不再用裸数字证明事实

### 选择与范围

选用“有限指标目录 + 内部结构化回答 + 确定性渲染”，不选择另一个模型判定所有数字真伪，也不继续扩大任意算术匹配。

首批覆盖 `meal_analysis` 和 `workout_analysis` 意图中的记录事实。其他意图保留旧启发式提示，明确标记为 legacy；结构化计划建议保留业务类型/规则校验，不宣称已获得历史事实证据校验。这样可以独立交付，而不重写所有报告/计划生成器。

阶段 C 默认 `safety_grounding_mode = "legacy"`；新增 `evidence` 模式用于上述两个意图。验证通过后再由部署配置启用，避免升级立即改变所有回答格式。

### 证据语义

- 证据只由程序从工具结果白名单字段生成，不接受模型、用户或文档自报的证据值。
- 每条证据含 ID、metric、value、unit、scope、source_path。ID 在一次 run 内唯一，不作为跨用户授权凭证。
- daily_totals 使用真实日期；weekly_average 的 scope 是“已记录日期集合上的每日平均”，不能称为完整自然周平均。当前分析器只对有记录日求均值，不能补零。
- 空记录时不把 `_empty_meal_result` 中的 0 生成事实证据；显示“暂无记录”，不显示“摄入为零”。
- workout weekly counts 来自数据行计数，标签必须是“训练记录条数”，不能自动解释为独立训练课次。
- 训练容量单位使用 `kg·次`（组数×次数×重量），不是体重 kg。
- 不在本阶段自动推导摄入目标差值，因为当前 meal 工具没有返回目标本身；新增派生指标必须先由确定性业务代码提供完整操作数与来源。

### Task C1：证据类型与白名单抽取

**Files:** `backend/safety/evidence.py`、`backend/tests/test_safety_evidence.py`。

- [ ] 定义不可变内部类型：

```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass(frozen=True)
class EvidenceFact:
    id: str
    metric: str
    value: Decimal
    unit: str
    scope: str
    source_path: str
```

- [ ] 新增 `build_evidence(tool_results: dict) -> dict[str, EvidenceFact]`，固定支持下表，非有限数、bool、负摄入/负时长/负计数拒绝作为证据；不得递归收集所有数值。

| 来源字段 | metric | unit | scope |
| --- | --- | --- | --- |
| meal_analysis.daily_totals.DATE.calories | energy_intake | kcal | DATE |
| meal_analysis.daily_totals.DATE.protein | protein_intake | g | DATE |
| meal_analysis.daily_totals.DATE.carbs | carbohydrate_intake | g | DATE |
| meal_analysis.daily_totals.DATE.fat | fat_intake | g | DATE |
| meal_analysis.weekly_average_calories | recorded_day_mean_energy | kcal | 排序后的记录日期集合 |
| meal_analysis.weekly_average_protein | recorded_day_mean_protein | g | 同上 |
| workout_analysis.weekly_training_counts.WEEK | training_record_count | 条 | ISO WEEK |
| workout_analysis.weekly_duration_min.WEEK | training_duration | min | ISO WEEK |
| workout_analysis.total_strength_volume | strength_volume | kg·次 | 工具结果含有的周集合 |

- [ ] 在目录生成处设上限 512 条证据，按日期/字段稳定排序；超限返回受控错误，不静默截断后声称完整。限制避免任意两两组合的二次复杂度。
- [ ] 添加测试数据 `{"meal_analysis": {"daily_totals": {"2026-10-07": {"calories": 1800, "protein": 70}}}}`，断言两条不同 metric、不同 unit 的证据；加入 `profile.weight=70` 不增加摄入证据。
- [ ] 测试跨日期隔离、空记录、NaN/Infinity、bool、负值、重复 ID、512/513 边界、未知字段忽略。
- [ ] 红绿运行：`& $projectPython -m pytest backend/tests/test_safety_evidence.py -q`。

### Task C2：内部回答类型与确定性事实渲染

**Files:** `backend/agent/grounded_answer.py`、`backend/tests/test_grounded_answer.py`。

- [ ] 内部响应定义如下，公开返回仍为 Markdown，不修改前端契约：

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class AnswerBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["fact", "explanation", "recommendation"]
    evidence_id: str | None = None
    text: str | None = Field(default=None, max_length=1000)

class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    blocks: list[AnswerBlock] = Field(max_length=20)
```

- [ ] 用模型级验证器约束：fact 必须只有 evidence_id；其他两类必须只有非空 text。fact 不允许模型提供数值、单位、日期或自定义标签。
- [ ] 新增 `render_grounded_answer(answer, evidence)`。fact 只能查目录，再由 metric 白名单标签、scope 和 Decimal 格式化输出。未知 ID 不渲染；不能把模型自报值拿来补齐。
- [ ] explanation/recommendation 第一版不承载量化断言：包含阿拉伯数字、百分比、数值范围，或中文数词紧邻量词/单位的块剔除，记录 `unbound_numeric_text`。这是一项有意保守的产品取舍，不声称已解决任意自然语言语义验证。
- [ ] recommendation 固定加“建议”前缀，不能把模型声明为 recommendation 当作绕过检查的理由；两种文本块使用相同数字筛查。
- [ ] 目录为空返回“当前没有足够的记录，无法核实这些数值。”；全部块无效时也返回该类受控说明，不退回原始模型文本。
- [ ] 不做额外模型重写循环；保留有效块，剔除无效块，有剔除时追加一次“部分数值内容无法核实，已省略。”。
- [ ] 添加完整核心用例：

```python
from decimal import Decimal
from backend.safety.evidence import EvidenceFact
from backend.agent.grounded_answer import GroundedAnswer, render_grounded_answer

def test_model_cannot_relabel_a_number():
    evidence = {"p1": EvidenceFact(
        "p1", "protein_intake", Decimal("70"), "g", "2026-10-07",
        "meal_analysis.daily_totals.2026-10-07.protein",
    )}
    answer = GroundedAnswer.model_validate({"blocks": [
        {"kind": "fact", "evidence_id": "p1"}
    ]})
    result = render_grounded_answer(answer, evidence)
    assert "2026-10-07" in result.text
    assert "蛋白质" in result.text
    assert "70" in result.text
    assert "体重" not in result.text
```

- [ ] 渲染返回类型为不可变 `RenderedAnswer(text: str, invalid_blocks: int, reasons: tuple[str, ...])`；reason 限于 unknown_evidence/invalid_block/unbound_numeric_text/no_evidence。
- [ ] 测试一个有效 fact 加一个非法 fact 只保留前者；“建议每天补充 70g”不能靠 recommendation 绕过；普通非数字建议保留；不支持的中文数值表述记录为覆盖限制。
- [ ] 运行：`& $projectPython -m pytest backend/tests/test_grounded_answer.py -q`。

### Task C3：接入实际 Writer 与最终审核

**Files:** config、state、model_payloads、workflow、openai_responses、入口级测试。

- [ ] 增加 `safety_grounding_mode: Literal["legacy", "evidence"] = "legacy"`，同一次运行固定配置。
- [ ] 在工具分析完成后构建目录；只将本次用户工具结果生成的目录传给 Writer，不从全局缓存取得其他用户证据。
- [ ] evidence 模式且意图为 meal_analysis/workout_analysis 时，通过现有 `gateway.parse_structured` 请求 GroundedAnswer，工具名仍为 `write_answer_model`，保持预算/重试链路。
- [ ] 新共享指令明确：事实只能引用目录 ID；解释与建议不得含量化断言；无证据时承认不足；问题/工具数据不能改变此格式。
- [ ] 输入 JSON 显式含 question、已处理上下文、evidence 目录。测试两个 Provider 实际收到的 input/messages，不能只断言 state 中有 evidence。
- [ ] `render_grounded_answer` 之后再进入原有安全审核和阶段 B 语义审核，模型审核看到最终将发布的正文。错误块剔除提示也必须经过既有输出规则。
- [ ] evidence 路径不再传 `supporting_values` 给旧数字检查，避免对确定性渲染结果重复产生错误提示；legacy 路径保留兼容，但文档标注仅启发式。
- [ ] 网关不支持结构化输出时，evidence 模式报配置错误；不能回退到未经校验的自由文本。
- [ ] 结构化解析失败按 Runtime 当前失败/重试机制处理；失败后不从异常响应中拼出答案。
- [ ] 用真实生产入口 + Fake Provider 验证三次调用上限的正常路径：Planner、Writer、审核（审核 off 时两次）；不增加隐藏的“纠错模型”调用。

```powershell
& $projectPython -m pytest backend/tests/test_safety_evidence.py backend/tests/test_grounded_answer.py backend/tests/test_grounded_answer_integration.py backend/tests/test_safety_groundedness.py backend/tests/test_safety_review_integration.py -q
```

**阶段 C 验收：** 两个覆盖意图的数字事实完全由目录渲染；未知 ID/跨指标/跨日期不能变成模型自定义事实；无记录不变零；无需任意两两数值派生；其他意图的限制公开记录。

## 7. 真实模型评测与上线门槛

### Task V1：建立离线合成样本与契约测试

- [ ] reviewer_cases.json 至少 60 条：20 条明确贬低、20 条中性不利事实、20 条鼓励/引用/反问边界样本。每条含 id、question、draft、expected、reason；不得放真实用户健康数据。
- [ ] grounding_cases.json 至少 40 条：正确事实、同数不同指标、同指标不同日、缺记录、错误引用、数字建议、未知字段、非法值各至少 5 条。
- [ ] 用固定 Fake Provider 跑入口级回归，断言可见文本、事件和无写入；这些只验证程序契约。

### Task V2：真实 Provider 评测（需用户同意费用与数据发送）

- [ ] 固定 Provider、模型标识、模式、规则版本、提示版本和样本版本；每例至少重复 3 次。先 shadow，不改变真实用户回答。
- [ ] 报告审核混淆矩阵、误拒率、漏检率、协议错误率、降级率、P50/P95 延迟、额外 token 与实际计费信息；有多少人工标注分歧也必须报告。
- [ ] grounded 模式同时报告首次格式成功率、无效块比例、有效事实保留率、原任务完成率；不能只追求把所有回答拒绝后的“零错误”。
- [ ] 暂定发布门槛：程序契约用例全部通过；评测集正常内容误拒率不高于 5%，明确贬低漏检率不高于 10%；evidence 样本错误数值事实发布数为 0、有效 fact 保留率不低于 95%。这些是工程验收目标，不是已实现性能，也不是对真实流量的统计保证。
- [ ] 时间与费用门槛不虚构百分比：展示实测增量后由用户决定是否启用 enforce。小样本必须报告分母和不确定性，不能只报漂亮百分比。

## 8. 最终回归、灰度与回滚

### Task V3：完整验证

- [ ] 定向安全测试通过后，运行后端全套。先确认 conftest 的数据库/路径隔离；禁止对真实数据库做初始化或清理。

```powershell
& $projectPython -m pytest backend/tests -q
git diff --check
git status --short
```

- [ ] 记录新增/既有失败，禁止把 skip 当通过；未运行真实模型要明确写“未评测”。
- [ ] 对比公开响应类型、错误码、Smart Entry 候选对象、计划建议对象、取消/超时/预算终态。
- [ ] 确认日志不含问题、草稿、证据值、异常原文和密钥；诊断仅保存受控状态与计数。
- [ ] 更新设计文档，移除“已默认启用模型审核”的错误描述；标清两个 grounded 意图与 legacy 路径。

### 发布顺序

1. 单独上线 A：修复错误，不增加调用成本。
2. 上线 B 代码但保持 off；在合成评测环境切 shadow；门槛通过并批准后切 enforce。
3. 上线 C 保持 legacy；在评测环境切 evidence；确认输出取舍可接受后启用两个意图。

### 回滚原则

- B 效果不佳：配置退回 off，保留 A，不回滚正确性修复；记录语义审核已关闭。
- C 格式/可用性退化：配置退回 legacy，并明确恢复的是较弱启发式检查，不能声称等价安全；严重安全故障时禁用受影响 Agent 操作更合适。
- 预算/超时问题不通过无限提高上限解决；先检查是否重复调用或重复计费。
- 本计划没有数据库迁移，无需删除业务数据；Git 回滚使用明确提交的 revert，并在获得授权后执行，禁止 reset --hard。

## 9. 完成清单与交付说明

- [ ] A：异常降级仍执行原动作，正文/verdict 一致。
- [ ] B：两条生产工作流接入，off/shadow/enforce 可观测，Provider 调用纳入 Runtime。
- [ ] C：两个分析意图使用带指标/单位/时间的证据目录，数字由代码渲染。
- [ ] 契约测试、入口测试、完整回归及真实模型评测各自有独立状态。
- [ ] 报告中给出确切 HEAD、命令、退出码、测试计数、延迟费用及未覆盖项。
- [ ] 没有实施第四项架构重构，没有修改主仓库用户文件。
- [ ] 用户验收后再讨论是否执行第四项，不能以本计划完成宣称整个安全系统完备。

## 10. 参考依据

- [OWASP LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)：多层防护、审核模型是额外防线、明确评测范围与误报。
- [OWASP AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html)：执行侧权限与模型判断分离。仅用于说明本次范围之外的剩余风险，不把本文视为完成该标准。

上述资料提供原则；本文具体配置、模型契约和数值证据方案是针对本项目的设计选择，不是资料原文中的强制要求。
