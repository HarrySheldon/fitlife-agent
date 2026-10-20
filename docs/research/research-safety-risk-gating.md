# Safety risk gating for a Chinese-language fitness/nutrition agent — research report

**Scope:** engineering design patterns for input/output safety gating, gathered to fix a regex
`medical` rule that false-positives on negated and prescriptive-safe Chinese text. No legal advice.

**Source labels:** **(a)** established standard / validated instrument / peer-reviewed ·
**(b)** widely-used open-source implementation · **(c)** vendor doc or marketing.
Where only an indexed snippet was reachable (paywall, PDF, 403), that is stated explicitly.

---

## 0. The failure mode has a name and a benchmark

The project's bug is **exaggerated safety / false refusal** — a measured research problem.

- **XSTest** (Röttger et al., NAACL 2024) — https://arxiv.org/abs/2308.01263 — **(a)**.
  250 *safe* prompts across 10 types "that well-calibrated models should not refuse to comply with",
  plus 200 minimally-edited unsafe contrasts. Thesis: "even clearly safe prompts are refused if they
  use similar language to unsafe prompts or mention sensitive topics." Methodological contribution:
  **report false-refusal rate separately from unsafe-compliance rate.**
- **Health-ORSC-Bench** (ACL Findings 2026) — https://aclanthology.org/2026.findings-acl.1177.pdf —
  **(a)**, *snippet only (PDF not parseable)*. Over-refusal as primary axis; contrasts
  **Safe Completion Rate (SCR)** against **Over-Refusal Rate (ORR)**. Binary refusal boundaries are
  named as the root cause of both over-refusal and unsafe compliance.
- **Llama Guard 3 model card** — https://github.com/meta-llama/PurpleLlama/blob/main/Llama-Guard3/8B/MODEL_CARD.md —
  **(c) vendor, unusually candid**. Publishes FPR alongside F1 (English response classification
  F1 0.939 / **FPR 0.040**), and warns deployment "might increase refusals to benign prompts
  (False Positives)". Reference: a well-tuned semantic guard sits ~4% FPR *on its own taxonomy*.

**Takeaway:** the fix is not "tune the regex down". It is (1) add negation/context scoping,
(2) separate *detection* from *action*, (3) make the cheap layer emit *candidates with evidence spans*
rather than verdicts, (4) stand up a false-refusal test set in the classes that actually hurt.

---

## 1. Negation detection / clinical NLP

### 1.1 NegEx — **(a) established standard**
Chapman et al., *J Biomed Inform* 34(5):301–310, 2001, doi:10.1006/jbin.2001.1029.
Full text **not retrieved** (ScienceDirect 403, PubMed blocked); algorithm structure verified
through negspacy, a faithful port.

1. **Targets** are found independently (e.g. `糖尿病`, `停药`).
2. **Four disjoint trigger classes:** `preceding_negations` (before target, bounded window),
   `following_negations` (after target — "…ruled out", "…阴性"), `pseudo_negations`
   (**false triggers** that *cancel* a match — "not only"), `termination` (scope cutters — ".", "but").
3. Order: split at termination → search preceding window → pseudo-negation override →
   following-negation → **default is asserted/not-negated**.
4. **The default matters:** NegEx is open-world *asserted*. The current classifier inverts this —
   absence of a negation check is treated as a violation.

**[negspacy](https://github.com/jenojp/negspacy) — (b)** exposes exactly that config surface, plus
`chunk_prefix` (because "There is no headache" glues "no" onto the entity), with termsets
`en` / `en_clinical` (default) / `en_clinical_sensitive`.

Trigger inventories are **not portable across languages**: a French NegEx adaptation reports
**191 phrases, 11 pseudo-negations, 102 pre-target negations** (https://dl.acm.org/doi/pdf/10.1145/2110363.2110443,
**snippet only**). That ~6% pseudo-negation ratio is the design lesson: **if none of the triggers are
pseudo-negations, false positives exist by construction.**

### 1.2 ConText — **(a) established standard**
Harkema et al., *J Biomed Inform* 42(5):839–851, 2009, doi:10.1016/j.jbi.2009.05.002
(https://www.sciencedirect.com/science/article/pii/S1532046409000744, **403**; abstract verified).
Generalises NegEx from one modifier axis to **negation, experiencer, temporal status**; medspaCy adds
uncertainty. This is the most useful idea in the report — the project's false positives map onto it exactly:

| False positive | Axis | Correct modifier |
|---|---|---|
| 从记录看**不能诊断**任何疾病 | negation | negated → allow |
| 请**不要**自行**停药** | deontic, *not* negation | prescriptive safety instruction → allow |
| **如果**我有糖尿病 | hypothetical | allow with framing |
| **我家人**有糖尿病 | experiencer | third party → allow, different advice |
| 糖尿病**是什么** | definitional | information, not advice → allow |

A bare regex cannot express any of these. ConText's structure can.

### 1.3 medspaCy — **(b) widely-used OSS**
https://github.com/medspaCy/medspacy — `medspacy.context` implements ConText for "negation and
uncertainty", MIT, modular, spaCy-native.

**Critical finding — the README language-support table.** ConText rule packs exist for
**English, French, Dutch only**. Spanish, German, Polish, Portuguese, Italian: **No**.
**There is no Chinese ConText rule pack**, so it cannot be imported. This is acceptable: the Chinese
NegEx inventory is small enough (tens of phrases) to author *and hand-inspect*, which is what an
auditable safety gate needs.

### 1.4 NeMo Guardrails "self check" — **(c) vendor, (b) OSS engine**
https://docs.nvidia.com/nemo/guardrails/v0.23.0/configure-guardrails/guardrail-catalog/self-check
(append `.md` to any NeMo docs URL for clean markdown).

`self_check_input` / `self_check_output` are **prompt-based LLM checks, not rule-based negation logic** —
there is no NegEx-style dialogue negation handling. But three details are directly reusable:

- **Empty output fails closed** (`self_check_facts` returns score `0.0`). Reasoning models need
  `max_tokens` raised above the 1024 default, or the verdict is consumed by the reasoning trace →
  **spurious block**.
- **`self_check_output` receives both `{{ user_input }}` and `{{ bot_response }}`.** A classifier that
  sees only the answer cannot tell that "从记录看不能诊断任何疾病" is *correct* given a question asking
  whether the user has diabetes.
- **Multilingual refusal messages:** built-in Chinese is `抱歉，我无法回应。`, customizable via
  `rails.config.content_safety.multilingual.refusal_messages.zh`, using fast-langdetect
  (~12 µs/request; lite model ~0.9 MB bundled, offline). Pattern to copy:
  **localized, specific refusal** rather than a generic disclaimer.
- Docs self-warn: performance "is strongly dependent on the capability of the LLM to follow the
  instructions… consider a purpose-built input safety model instead."

**Seed Chinese trigger inventory (validate against the corpus):**

- **preceding negation:** 不, 不能, 无法, 不会, 不要, 别, 请勿, 切勿, 禁止, 避免, 没有, 无, 未, 未曾,
  从未, 并非, 不是, 否认, 排除, 缺乏, 不需要, 无需
- **following negation:** 是不可能的, 阴性, 已排除, 风险低
- **pseudo-negation:** 不仅, 不但, 不只, 无论, 不管, 并非唯一 (watch 不可避免 — contains 不 + 避免)
- **termination:** 。！？；, 但, 但是, 不过, 然而, 可是, 只是, 除外
- **deontic (separate axis — fixes 请不要自行停药):** 请, 建议, 务必, 应, 需要, 切勿 + target

---

## 2. Guardrails frameworks: separating taxonomy from action policy

### 2.1 NeMo Guardrails — **(b) OSS + (c) vendor**
Five rail types by *stage*: **input**, **retrieval**, **dialog**, **execution**, **output**.
Content Safety applies to input **and** output.

- **Taxonomy lives in the prompt.** The ShieldGemma example writes a domain carve-out into the
  taxonomy to prevent exactly this class of false positive:
  *"Medical or scientific terms related to human anatomy or sex education are permitted."*
- **Action lives in Colang, as a separate object:**
  ```
  define flow self check input
    $allowed = execute self_check_input
    if not $allowed
      bot refuse to respond
      stop
  ```
  plus `define bot refuse to respond "…"` to override the message.
- **`mask` is a first-class action, not a refusal:** `gliner mask pii on input` replaces spans with
  placeholders (`Hi John` → `Hi [FIRST_NAME]`) under a `threshold: 0.5` confidence knob.

### 2.2 Guardrails AI — **(b) widely-used OSS**
https://guardrailsai.com/guardrails/docs/concepts/validator_on_fail_actions — the cleanest
taxonomy/policy split available: a **Validator** is a pure predicate returning
`PassResult`/`FailResult` (optionally `fix_value`); **`on_fail` is the policy**.

| Action | Behavior |
|---|---|
| `NOOP` | do nothing; failure still logged |
| `FIX` | repair programmatically via `fix_value` |
| `FILTER` | structured data only — drop the failing **field**, return the rest |
| `REASK` | re-prompt with the generated `error_message`; `num_reasks` controls retries |
| `FIX_REASK` | deterministic fix → re-validate → only then reask |
| `REFRAIN` | return nothing — "useful when the generated output is not safe to return" |
| `EXCEPTION` | raise |
| `CUSTOM` | `on_fail(value, fail_result) -> Any` |

And **per-field granularity**: `quantity: int = Field(validators=[MinimumOneRange(min=1, max=10, on_fail="fix")])`.
That is the analogue needed here — policy per **span**, not per **response**.

### 2.3 Llama Guard / Prompt Guard — **(b) open weights, (c) vendor docs**
Llama Guard 3 model card: 14 categories (S1 Violent Crimes … **S6 Specialized Advice**, **S11 Suicide &
Self-Harm** …), aligned to **MLCommons' 13-hazard taxonomy (a)**.

- Output is `safe`/`unsafe` **plus violated category codes**; the decision rule is first-token
  probability + **score thresholding** → *taxonomy and threshold are separate, tunable artifacts*.
- **S6 = "specialized financial, medical, or legal advice"** — note how narrow: it is about *giving*
  specialized advice, not *mentioning* medical words. **S11 explicitly enumerates "(3) disordered eating."**
  Those are the only two categories this product actually occupies.
- The card documents **deliberate false-positive mitigation**: benign multilingual prompt/response data
  was curated, and safe training data chosen "close to the boundary… to minimize false positives on
  such borderline examples."
- [Paper, arXiv 2312.06674](https://arxiv.org/abs/2312.06674) — taxonomy is *prompt-injectable*.
- [Llama Prompt Guard 2](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M) (86M/22M) — small
  binary jailbreak/injection classifier. **Card not retrieved — treat as unverified.**

### 2.4 The standard action tiers, synthesised

| Tier | Semantics | Named in |
|---|---|---|
| 0 | **annotate / log only**, pass through | Azure "annotate only"; Guardrails AI `NOOP` |
| 1 | **mask / redact** a span, keep the rest | NeMo `mask pii`; Guardrails AI `FIX`, `FILTER` |
| 2 | **disclose** — pass content + add a disclaimer line | Anthropic "Disclosure" |
| 3 | **regenerate / reask** with constraints | `REASK`, `FIX_REASK` |
| 4 | **refuse** with a targeted message (scope = the risky claim) | `REFRAIN`; NeMo `bot refuse to respond` |
| 5 | **hard block / error** and/or **escalate to a human** | `EXCEPTION`; Azure HTTP 400 |

**The current implementation has exactly one tier (≈4) at whole-answer granularity, firing at
tier-0/1 severity. That is the entire bug.**

---

## 3. Two-layer / tiered designs, severity → action

### 3.1 OpenAI Agents SDK — **(c) vendor, open-source SDK**
https://openai.github.io/openai-agents-python/guardrails/ — the most explicit published
cheap-gate-before-expensive-model pattern.

- Rationale stated outright: run a guardrail with a **fast/cheap model**; if it detects misuse, raise
  immediately, "saving time and money".
- **Execution modes are the real design decision:**
  - `run_in_parallel=True` (default): concurrent, best latency, but "if the guardrail's tripwire is
    triggered, the agent may have already consumed tokens and executed tools before being cancelled."
  - `run_in_parallel=False` (blocking): completes before the agent starts; "ideal for cost optimization
    and when you want to avoid potential side effects from tool calls."
- **Three outcomes, not two.** Tool guardrails "can skip the call, **replace the output with a message**,
  or raise a tripwire." On output rejection the SDK substitutes a **data-free placeholder**
  (`"Output withheld by an output guardrail."`), configurable via
  `RunConfig.output_guardrail_blocked_message`.
- **Detection and action are separated objects:** the function returns
  `GuardrailFunctionOutput(output_info=…, tripwire_triggered: bool)`; the *runner* decides.

### 3.2 Azure AI Content Safety — severity scales — **(c) vendor, most concrete published mapping**
https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/harm-categories —
categories: **Hate and Fairness, Sexual, Violence, Self-Harm** (+ optional binary classifiers).
**Self-Harm explicitly lists "Eating disorders."**

**Two severity scales exist — know which is being copied:**
- **Guardrails, 4-level:** `Safe` / `Low` / `Medium` / `High`. Threshold: **Off** / **Low** (flags low+,
  least restrictive) / **Medium** / **High** (only most severe, *most* restrictive). And:
  "Content at the **Safe** level is always annotated but never blocked, regardless of threshold setting."
- **Standalone service:** full **0–7**; the image model returns trimmed `0, 2, 4, 6`.

**Severity → action**, from the Foundry content-filter configurability table
(https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/content-filter):

| Severity filtered | Configurable (prompts / completions) | Meaning |
|---|---|---|
| Low, medium, high | Yes / Yes | strictest |
| Medium, high | Yes / Yes | low passes |
| High | Yes / Yes | only most severe filtered |
| **Annotate only** | Yes / If approved | **filter disabled; annotations still returned** |
| No filters | Yes / If approved | nothing blocked or annotated |

Enforcement detail worth copying: prompts at a filtered level → **HTTP 400**; completions →
`finish_reason: "content_filter"` with **partial content possible**. A **fail-open** path is documented:
if the filter service is unavailable, the request "still completes without content filtering".

**Most directly applicable lines**, from the troubleshooting section:
*"If you see too many false positives or negatives: … Adjust from **block** to **annotate** mode to log
without filtering. Review specific attack subtypes triggering false positives. Consider exempting
trusted input sources."* And: *"Check if context is missing that would change the interpretation
(educational, historical, fictional)."*

### 3.3 Azure Prompt Shields — **detection ≠ filtering** — **(c) vendor**
https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection —
two independent booleans:

```json
"content_filter_results": { "jailbreak": { "filtered": false, "detected": true } }
```

`detected: true, filtered: false` is a **legal, first-class state**. Sub-classifications are enumerated
separately; the only *actions* are annotate vs block. Its healthcare scenario: "the application prevents
a model response and **redirects the patient to a healthcare professional**" — escalation as an action
distinct from refusal.

### 3.4 Anthropic Usage Policy — **(c) vendor policy, design-legible**
https://www.anthropic.com/legal/aup — structure: **Universal Usage Standards** →
**High-Risk Use Case Requirements** → **Additional Use Case Guidelines**.

- High-risk extra measures are two concrete engineering requirements: **Human-in-the-loop** ("a qualified
  professional in that field must review the content or decision prior to dissemination") and
  **Disclosure** ("at a minimum at the beginning of each session").
- **The decisive sentence:** *"Wellness advice (e.g., advice on sleep, stress, nutrition, exercise, etc.)
  does not fall under this category."* Nutrition/exercise guidance is explicitly **not** high-risk →
  the prescribed action is *disclose*, not *refuse*.
- The prohibited content in this domain is narrow and **intent-based**: "Facilitate, promote, or glamorize
  any form of suicide or self-harm, **including disordered eating and unhealthy or compulsive exercise**"
  and "promote unhealthy or unattainable body image or beauty standards, such as using the model to
  critique anyone's body shape or size."

**This is the correct taxonomy for the `medical` rule.** The forbidden predicate is *promoting disordered
eating / unhealthy or compulsive exercise / unattainable body standards* — not *mentioning 糖尿病 or 停药*.
Rewriting the rule against this predicate removes the false positives **by definition** rather than by patching.

### 3.5 Constitutional AI — **(a) established method**
https://arxiv.org/abs/2212.08073 — principles list + self-critique + revision + RLAIF. Two transferable
ideas: keep **principles** a separately editable artifact from the **enforcement mechanism**; and the
result is explicitly "a harmless but **non-evasive** AI assistant that engages with harmful queries by
explaining its objections to them." Non-evasive refusal names the specific concern and answers the safe
part — the opposite of a generic disclaimer.

### 3.6 OpenAI moderation — **not retrieved**
`platform.openai.com/docs/guides/moderation` and `developers.openai.com/docs/guides/moderation` returned
**403/Cloudflare**; the announcement URL returned 404. **OpenAI's own category list and thresholds are
unverified here — use the verified Azure tables in §3.2 for severity scales.**

---

## 4. Health-specific products: emergency red flags vs. general health information

### 4.1 OpenEvidence triage evaluation — **(a) peer-reviewed, directly on point**
Jia et al., *Int J Med Inform* 222:106687 (2026),
https://research.bidmc.org/radiology-research/publications/openevidence-errs-safe-side-structured-test-triage-recommendations
(PubMed 42673790). 60 clinician-authored vignettes / 30 scenarios / 21 domains → 960 prompts.

- Clear-case accuracy: **71.3%**.
- **Emergency under-triage: 12.5%** (vs 51.6% for the ChatGPT Health benchmark).
- **Non-urgent "Home" over-triage: 68.0%** (vs 64.8%).
- Objective clinical data **eliminated** emergency under-triage (25% → 0%, p=0.005) and reduced
  non-urgent over-triage (78.7% → 57.8%, p=0.014).
- **65/960 (6.8%)** responses **declined to assign a triage level** — "exclusively in symptom-only
  Home or Routine prompts."
- Conclusion: "errors concentrated in over-triage and evidence-seeking refusal… treat **refusal as a
  distinct output category** whose clinical implications require separate assessment."

**This validates the project's situation on a commercial system.** Over-escalation dominates; refusal is
its own outcome class; more context fixes both directions.

### 4.2 Red flags in online symptom checkers — **(a) peer-reviewed**
Sutaria et al., *BMC Health Serv Res* 25:1263 (2025), doi:10.1186/s12913-025-13353-w
(open-access record: https://discovery.ucl.ac.uk/id/eprint/10214938/).

- 51 vignettes; standard setters judged **14 emergency**, 37 primary-care.
- Emergency triage accuracy: **PCPs 85.7%** vs **OSCs 76.9%**, p=0.299 (no significant difference).
- **Specificity:** **PCPs 91.9%** vs **OSCs 83.3%**, **p=0.024** — checkers significantly **over-triage
  primary-care as emergency**.
- "**OSCs do not seek the majority of red flags.**" For the 37 primary-care vignettes, standard setters
  identified **77 relevant red-flag symptoms to be sought**.

Consequences: over-escalation is the *measurable* dominant failure mode across products — a regex firing
on `糖尿病` is its pathological limit; and **red-flag detection is an elicitation problem, not a
classification problem.** The safe consultation *asks*. Regex over the user's text can never find a red
flag the user did not volunteer.

### 4.3 Infermedica — **(c) vendor, with an (a)-grade certification claim**
https://developer.infermedica.com/ — verified: "certified as a **Class IIb medical device under EU MDR**";
26 languages. Architecture separates **interview types** — Triage ("early symptom assessment and care
navigation"), Intake ("medical data collection"), Follow-up ("symptoms re-evaluation over time") — and two
API surfaces: **Platform API** (pre-built, stateful, validated interviews) vs **Engine API** (stateless:
NLP, Diagnosis, **Triage**, Specialist & Channel Recommender, **Rationale**, **Explain**).

**Design pattern:** triage is a **separate ordered output channel** from diagnosis, with its own endpoint
and interview. `Rationale` / `Explain` are first-class endpoints — **showing the basis is a product
feature.** The exact triage-level enum **could not be retrieved** (docs are JS-rendered), so no specific
level names are asserted.

### 4.4 FDA Clinical Decision Support Software — **(a) regulatory framing, design-legible**
https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software
(Jan 6, 2026 revision supersedes 2022; docket FDA-2017-D-6569). Four Non-Device CDS criteria under
**FD&C Act §520(o)(1)(E)**, verified verbatim via the Covington summary:

1. Not intended to acquire, process, or analyze a **medical image**, a signal from an **in vitro
   diagnostic device**, or a **pattern or signal from a signal acquisition system**.
2. Intended for **displaying, analyzing, or printing medical information** about a patient.
3. Intended for **supporting or providing recommendations to a healthcare professional** about
   prevention, diagnosis, or treatment.
4. Intended to enable the HCP to **independently review the basis** for the recommendations, so that it
   is **not the intent that the HCP rely primarily on any of such recommendations**.

2026 changes as *design* signals: enforcement discretion for **singular recommendations**; stronger
emphasis on **usability** ("prioritizes decision-relevant details and avoids information overload") and on
grounding in "**well-understood and accepted sources**"; **time-critical decision making** moved from
Criterion 3 into Criterion 4. The guidance is **silent on consumer-facing tools and on AI** — "FDA did not
announce any new or clarified policies for consumer-facing tools such as patient decision support, health
chatbots, or symptom checkers." **Not legal advice.** Engineering reading: show your basis, keep the human
in the loop, don't be the sole basis.

### 4.5 EU AI Act Art. 6 / Annex III — **(a) regulation**
https://artificialintelligenceact.eu/article/6/ — high-risk requires (a) intended as a **safety component**
whose failure endangers health and safety **and** (b) third-party conformity assessment, *or* an Annex III
use case (health listed). Chapter III Section 2 obligations map onto engineering artefacts:

| Article | Engineering artefact |
|---|---|
| Art. 9 Risk management system | a living risk register tied to the rule catalog |
| Art. 10 Data and data governance | the eval set; document how it was built |
| Art. 12 Record-keeping | **log every gate decision** (verdict, category, severity, action) |
| Art. 13 Transparency | expose basis and limitations to the user |
| Art. 14 Human oversight | a real escalation path, not a dead-end disclaimer |
| Art. 15 Accuracy, robustness, cybersecurity | measured FPR/FNR on a held-out set |

Entry into force per Art. 113(c): **2 Dec 2027** (Annex III) / **2 Aug 2028** (Annex I).
Engineering reading only, not legal advice.

### 4.6 Ada Health / Babylon — **not retrieved**
`https://ada.com/how-ada-works/` returned **404**. No claims are made about either product's internals.
The transferable pattern is better sourced from §4.1–4.2.

**Takeaway for §4:** split the single `medical` rule into three rules with different actions —
1. **Emergency red flags** (chest pain, syncope, dyspnoea at rest, one-sided weakness, severe bleeding,
   suicidal ideation, rapid unexplained weight loss, exercise syncope) → highest severity →
   **always escalate**. Also an *elicitation* rule: ask, don't only match.
2. **Clinical territory** (diagnosis, medication changes, lab interpretation) → medium → **do not refuse**:
   answer the coaching part, state plainly that diagnosis and medication changes are out of scope, and
   encourage raising it with a clinician. **This is the tier nuking the good answers; it should be at
   most tier 2 (disclose).**
3. **Disordered-eating / unhealthy-or-compulsive-exercise promotion**, body-image denigration → highest →
   refuse the *specific* promotion and offer support resources. **The only rule that needs a hard block.**

---

## 5. Fitness / nutrition: validated screening instruments as a rule basis

**Headline: there is no published "guardrail spec" for fitness/nutrition LLM apps.** What exists is
(i) the generic over-refusal benchmarks in §0, (ii) the vendor policies in §3.4, and (iii) the clinical
instruments below. The instruments are the strongest available basis for a structural reason:
**they are boolean/numeric flag sets with published cut-offs and published false-positive rates**, so the
gate becomes measurable instead of vibes-based.

### 5.1 SCOFF — **(a) validated instrument**
Morgan, Reid, Lacey, *BMJ* 1999;319:1467–8, doi:10.1136/bmj.319.7223.1467
(full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC28290/). The five items, verbatim:

1. Do you make yourself **S**ick because you feel uncomfortably full?
2. Do you worry you have lost **C**ontrol over how much you eat?
3. Have you recently lost more than **O**ne stone in a 3 month period?
4. Do you believe yourself to be **F**at when others say you are too thin?
5. Would you say that **F**ood dominates your life?

Scoring: **one point per "yes"; ≥2 indicates a likely case.** Validation n=116 cases (68 AN / 48 BN),
n=96 controls; **sensitivity 100%** (95% CI 96.9–100%), **specificity 87.5%** (79.2–93.4%). Authors'
framing: "a **false positive rate of 12.5%** is an acceptable trade off for very high sensitivity"; the
tool is "designed to raise suspicion of a likely case rather than to diagnose."

**Takeaway:** five booleans with `sum ≥ 2 → referral pathway` is shippable, testable, explainable. The
authors consciously accepted and documented a 12.5% FPR — do the same: pick a threshold and publish its cost.

### 5.2 EAT-26 — **(a) validated instrument**
https://www.eat-26.com/ and https://www.eat-26.com/eat-26/ (item list rendered by a JS quiz — structure
and scoring verified, **not** the 26 literal item strings):
- 26 items from factor analysis of the EAT-40; subscales **Dieting**, **Bulimia & Food Preoccupation**,
  **Oral Control**; 6-point Likert; **cut-off ≥20** → "individuals who score 20 or more should be
  interviewed by a qualified professional."
- **A three-criteria "referral index", not a single trigger:** (1) total score, (2) **behavioural
  questions**, (3) **BMI**. "Generally, a referral is recommended if a respondent scores 'positively' or
  meets the cut-off on **one or more** criteria."
- Explicit limitations to copy: "**not designed to make a diagnosis**"; "If you have a low score… you
  still could have a serious eating problem"; BED patients can score low.
- Intended settings explicitly include "**athletic programs, fitness centers**."

**Takeaway:** adopt the *multi-signal referral index* shape. A single keyword is one signal with no BMI
and no behaviour — which is why it cannot carry a block decision.

### 5.3 PAR-Q+ / ePARmed-X+ — **(a) established standard — the best action-mapping model found**
https://eparmedx.com/page/3/ (verified in full). **A Chinese translation exists:**
https://eparmedx.com/new-chinese-par-q/ — the instrument is already localized.

1. **All clients complete Page 1 — seven evidence-based General Health Questions.** **NO to all** →
   cleared for unrestricted physical activity. Done.
2. **YES to ≥1 → follow-up Pages 2–3.** **NO to all** → cleared with minimal supervision (**Low Risk**).
   **YES to ≥1** → complete **ePARmed-X+** and/or visit a **Qualified Exercise Professional**.
3. **ePARmed-X+** → one of three:
   - **Low risk:** cleared for unrestricted physical activity.
   - **Intermediate risk:** cleared for **low-to-moderate intensity exercise under consultation and/or
     supervision** of a QEP and/or allied health professional.
   - **High risk:** **low-intensity physical activity until meeting** with a QEP or other health
     professional; **healthcare clearance may be required**.

**Takeaway — the template for the severity → action table.** A three-tier *allow /
allow-with-conditions-and-disclosure / restrict-and-refer* ladder, produced by a **questionnaire**
(elicitation), with an explicit named supervisor and an explicit intensity constraint.

### 5.4 RED-S / IOC REDs CAT2 — **(a) established standard**
2023 IOC consensus: https://bjsm.bmj.com/content/bjsports/57/17/1073.full.pdf (consensus),
https://bjsm.bmj.com/content/bjsports/57/17/1068.full.pdf (CAT2 tool),
https://bjsm.bmj.com/content/bjsports/57/17/1109.full.pdf (validation review; PubMed 37752002).
**Cloudflare-403 PDFs — indexed titles and one table caption only, not full text.** Verified caption:
"**IOC REDs CAT2 Severity/Risk Assessment Tool that implements primary, secondary and potential
indicators into a traffic-light** [system]." Verified structure: **multi-tier indicator model
(primary / secondary / potential)** → **traffic-light severity output**. No specific thresholds asserted.

**Takeaway:** the primary/secondary/potential split is a good model for the `severity` field — a *primary*
indicator (low BMI + menstrual dysfunction + stress fracture) is qualitatively different from a
*potential* one, and collapsing them causes both missed cases and false positives.

### 5.5 Exercise pre-participation / ACSM contraindications — **(a) standard, secondary source only**
ACSM distinguishes **absolute vs relative contraindications to exercise**. Only a secondary adaptation was
verified (https://www.jmir.org/api/download?alt_name=resprot_v14i1e75816_app2.pdf — **snippet only**).
The AHA/ACSM red-flag symptom set (chest pain/discomfort, dizziness or syncope, disproportionate dyspnoea,
palpitations) is the standard basis for the emergency tier; **confirm against the primary ACSM source
before shipping it as medical content.**

The verified design point: **absolute vs relative is a severity scale, not a keyword list.**

### 5.6 Proposed flag set

```
flags = {
  # SCOFF (>=2 → referral) | EAT-26 referral-index shape | ACSM/AHA red flags
  scoff_sick_full, scoff_loss_of_control, scoff_weight_loss_3mo,
  scoff_feels_fat, scoff_food_dominates,
  behavioural_binge, behavioural_purge, behavioural_laxatives,
  behavioural_excessive_exercise, weight_loss_20lb_6mo,
  red_flag_chest_pain, red_flag_syncope, red_flag_dyspnoea_at_rest,
  red_flag_one_sided_weakness, red_flag_rapid_weight_loss,
  promotes_disordered_eating, promotes_compulsive_exercise,
  body_image_denigration,
  medication_change_request, diagnosis_request,
}
severity = f(flags)           # PAR-Q+ / RED-S multi-tier, absolute vs relative
action   = policy[severity]   # Low: answer | Intermediate: answer+disclose+constrain
                              # High: restrict+refer | Emergency: escalate
```

Every entry is a predicate with a published meaning, a threshold, and a known error rate — as opposed to
`if "糖尿病" in text`.

---

## 6. Recommended design

1. **Make `detected` and `filtered` two fields.**
   `{detected, filtered, categories[], severity: 0..6, modifiers[], evidence_spans[]}`. Adopt Azure Prompt
   Shields' `detected & !filtered` as first-class. This alone stops "whole answer replaced."
2. **Fix negation scoping first** (§1): four Chinese trigger classes + clause terminators +
   pseudo-negation override + asserted-by-default + ConText modifier axes. A 40–80 entry inventory is
   reviewable by a domain expert in an hour.
3. **Pass the user's question into the output check** (§1.4).
4. **Two-layer gate with candidate hand-off** (§3.1). Layer A: deterministic, blocking-mode, always-on
   red-flag scorer → candidates + evidence spans, **never a block**. Layer B: small-model semantic check
   **only on candidates**, given span + clause + user's question. Caps LLM cost at "only on candidates."
5. **Route by severity, not category** (§2.4, §3.2). ≤1 annotate/log · 2 disclose · 3 mask the span ·
   4 reask · 5 refuse the *specific claim*, non-evasively · 6 escalate.
   **Never replace a whole answer below severity 5.**
6. **Use the vetted outcome vocabulary** — `NOOP/FIX/FILTER/REASK/FIX_REASK/REFRAIN/EXCEPTION` and
   "skip / replace with message / tripwire". `FILTER` at field granularity → `mask` at span granularity.
7. **Base rules on instruments, not vocabulary** (§5): SCOFF ≥2, EAT-26 referral index, PAR-Q+ three-tier
   ladder, RED-S primary/secondary/potential, ACSM absolute vs relative.
8. **Build `xstest_zh_fitness` and report three numbers.** Safe classes that must not be refused:
   (a) negation/denial, (b) prescriptive safety advice (请不要自行停药), (c) definitional/educational,
   (d) hypothetical (如果我有…), (e) third-party (我家人有…), (f) quoted/attributed, (g) screening-question
   phrasing, (h) neutral body/weight talk — plus unsafe contrasts (promoting disordered eating, encouraging
   unsupervised 停药, extreme calorie restriction). Report **false-refusal rate**, **under-triage rate**,
   **over-triage rate** separately. Today none are visible because the regex has one output.
9. **Log every verdict** (category, severity, action, evidence spans, the user's next turn) — Art. 12/13/15-shaped
   *and* the only way to find the next false positive. Roll out in **annotate-only** mode.
10. **Refusal copy: localized and specific** (NeMo's zh default `抱歉，我无法回应。` vs a generic disclaimer).
    Name the specific concern, answer the safe part, give a next step.

---

## 7. Source classification

**(a) Established standards / validated instruments / peer-reviewed:** NegEx (Chapman 2001) · ConText
(Harkema 2009) · MLCommons hazard taxonomy · SCOFF (BMJ 1999) · EAT-26 (Garner) · PAR-Q+/ePARmed-X+ ·
IOC REDs CAT2 (2023) · ACSM contraindications & AHA/ACSM red flags · FDA CDS §520(o)(1)(E) · EU AI Act
Art. 6 + Annex III + Arts. 9/12/13/14/15 · XSTest (NAACL 2024) · Health-ORSC-Bench (ACL Findings 2026) ·
OpenEvidence triage evaluation (IJMI 2026) · red flags in OSCs (BMC HSR 2025) · Anthropic Usage Policy ·
Azure severity scales (vendor, but the most concrete published mapping).

**(b) Widely-used OSS:** negspacy · medspaCy (**en/fr/nl rules only, no Chinese**) · NeMo Guardrails
engine · Guardrails AI · OpenAI Agents SDK · Llama Guard 3 weights + taxonomy · Llama Prompt Guard 2
(card unverified).

**(c) Vendor docs:** Infermedica (Class IIb EU MDR claim; exact triage enum not retrieved) ·
NVIDIA content-safety catalog · Azure Foundry content-filter semantics · Ada Health and Babylon
(**not retrieved** — no claims made).

**Could not retrieve — do not treat as read:** full text of NegEx 2001 and ConText 2009
(ScienceDirect 403 / PubMed blocked; structure verified via negspacy/medspaCy) · French NegEx adaptation
and German clinical negation paper (snippet-only) · IOC REDs CAT2/consensus full text (BJSM Cloudflare 403)
· ACSM contraindication appendix (snippet-only) · **OpenAI Moderation API docs (403) — category list and
thresholds unverified; use the verified Azure tables** · Llama Prompt Guard 2 model card (fetch failed) ·
Health-ORSC-Bench details (snippet-only) · Anthropic constitution page (not fetched).
