# Reducing False Positives in Text Safety / Moderation Rules — Research Report

Scope: a Chinese fitness/nutrition agent with a bare-substring medical-risk regex
(`诊断 治疗 服用 停药 处方 糖尿病 注射`). Legitimate advisory answers
("不能诊断任何疾病", "请不要自行停药", "如有糖尿病请遵医嘱") get flagged and the whole
answer is replaced with a generic disclaimer.

---

## 0. The single most important framing

Your failure mode has a name in the literature: **exaggerated safety caused by
lexical overfitting**. XSTest (Röttger et al., NAACL 2024) concludes exactly this:
models refuse safe prompts because they are "overly sensitive to certain words or
phrases", and it shows the failure concentrates on prompts that *superficially
resemble* unsafe ones while being safe (homonyms, figurative language, safe
targets, safe contexts, definitions). See §5 "Exaggerated safety is likely caused
by lexical overfitting" and §5 "Practical safety means managing trade-offs".

- https://arxiv.org/html/2308.01263v3 (paper), https://aclanthology.org/2024.naacl-long.301/ (NAACL)

Your regex is a hand-built lexical-overfitting machine. Every remedy below is a way
to stop matching *topic* and start matching *assertion + intent + speech act*.

A second framing that matters for the design: **the construct you actually want to
block is a directive/prescriptive medical instruction, not a medical noun.** All
three of your false positives (`不能诊断任何疾病` = a *negated* capability claim;
`请不要自行停药` = an *advisory* directive; `如有糖尿病请遵医嘱` = a *conditional*
referral to a professional) are safe because the utterance's speech act is
advisory/limiting, not prescribing. That distinction is representable and testable.

---

## 1. Context-aware rule matching (the well-established core)

### 1.1 NegEx / ConText — the canonical mechanism

NegEx (Chapman et al.) and its extension ConText are the direct ancestors of every
practical context-aware matcher. ConText's mechanism, as documented in the ContextD
Dutch adaptation paper, is:

- Work **within a sentence**, with pre-indexed target terms marked.
- Maintain **four trigger lists** per property: *pre-triggers*, *post-triggers*,
  *termination triggers*, *pseudo-triggers*.
- Assign each target a **default value** (e.g. negation = `Not-negated`).
- **Pre-trigger scope** = from the right of the trigger to end of sentence.
  **Post-trigger scope** = leftwards from the trigger to start of sentence.
- A **termination trigger** truncates the scope early (conjunction, punctuation,
  another clause boundary).
- **Pseudo-triggers** look like triggers but do not negate (English `no change`;
  the paper notes `not`/`no` alone are weak triggers).
- NegEx's original English evaluation: precision 84.5%, recall 77.8%.

Two details from ContextD that translate directly to your case:

1. **Scope windows are tuned empirically and are short.** ContextD found the
   default scope too wide and set it to **6 words for GP entries** and **10 words
   for specialist letters**, overridden by termination triggers. For Chinese you
   should scope to the *clause* (see §2).
2. **Combined triggers.** ContextD added rules requiring a pre-trigger *and* a
   post-trigger to co-occur (e.g. Dutch *nooit* + *doorgemaakt*) because either
   alone was too noisy — the single trigger *nooit* was actually **removed** from
   the list for hurting performance. This is the direct analogue of requiring
   `停药` to co-occur with a directive cue.
3. **Pseudo-negation list.** Explicitly modelled as a separate list; this is where
   you put Chinese traps (see §2.2).

ContextD final results (F-score): negation 0.87–0.93 across four document types;
experiencer 0.99–1.00; **temporality (historical/hypothetical) much worse, 0.13–0.54**.
Honest read: negation detection is a *solved-ish* engineering problem; hypothetical
and speculative detection is *not*.

- https://pmc.ncbi.nlm.nih.gov/articles/PMC4264258/ (ContextD, BMC Bioinformatics 2014)

### 1.2 Implementations you can actually reuse

| Tool | Language | Mechanism | Offline | Chinese | Notes |
|---|---|---|---|---|---|
| **NegEx** (original) | Java/Python ports | trigger lists + scope regexes | yes | ✗ (needs translation) | reference implementation, tiny |
| **ConText** | Java/Python | NegEx + temporality + experiencer | yes | ✗ | 4 trigger lists, ~246 English triggers |
| **pyConTextNLP** | Python | ConText port; cues + scope rules as data | yes | ✗ | the "rules as data" design is the reusable part |
| **medspaCy** | Python (spaCy) | ConText implementation + `PhraseMatcher`, sentence/clause splitting | yes | ✗ | Apache-2.0, pip-installable, rule + ML interchangeable |
| **negspaCy** | Python (spaCy) | NegEx port | yes | ✗ | narrower than medspaCy |
| **ContextD** | Java | ConText + Dutch triggers | yes | ✗ | good worked example of a *localisation* |
| **CogStack / CliX** | Java, GATE-based | clinical IE pipelines with negation/assertion | yes (heavy) | partial | heavyweight for a small project |

- medspaCy: https://github.com/medspacy/medspacy
- pyConTextNLP cue/scope-rule docs (cited as the reference for encoding cues as data): https://huggingface.co/datasets/John6666/forum1/commit/a6422ea6855b1afd52f5e8f5d7b7b5f111e0d6f6

**Key architectural takeaway from pyConTextNLP/medspaCy:** encode cues as *data*
(lists of trigger strings + scope directions + termination conditions), not as
hand-written monolithic regexes. That makes the rule set testable, diffable, and
explainable — which is what you want for the resume/interview story.

### 1.3 The "bare noun → imperative" distinction

ConText/NegEx do not model speech act. For your rule you additionally need the
observation that **`服用` in `每日服用二甲双胍 500mg` (directive) is dangerous, while
`请勿自行服用` (prohibitive) and `服用前请咨询医生` (conditional referral) are safe.**
The literature that covers this:

- **Speech act / advice recognition.** "Recognizing advice, warnings, promises and
  threats" (COLING 1990) is the classical formulation — it treats advice/warnings as
  *speech acts* identified by cue patterns rather than topic. Old, small, but the
  framing is exactly right and is the honest citation for "classify intent, not
  topic."
  https://preview.aclanthology.org/starsem-semeval-split/C90-3065.pdf
- **Chinese medical intent classification exists as a dataset.** CBLUE's
  **KUAKE-QIC** is an 11-class Chinese medical *intent* classification task over
  real search-engine queries, with classes including **diagnosis, etiology analysis,
  treatment plan, medical advice, test result analysis**. This is a real, citable,
  Chinese-language intent taxonomy adjacent to your problem — and note that its
  error analysis found "**multiple triggers**" (multiple indicative words misleading
  the model) and "colloquialism" as roughly half of all bad cases, i.e. exactly your
  substring problem.
  https://ar5iv.labs.arxiv.org/html/2106.08087 (CBLUE, arXiv 2106.08087)

---

## 2. Chinese-specific challenges and tooling

### 2.1 Why substring matching is worse in Chinese

No whitespace word boundaries; `\b` is meaningless. Consequences:

- `\b` word-boundary anchors do **not** work — any regex using `\b诊断\b` is broken.
- Terms nest inside unrelated words. You must check each of your seven terms for
  this rather than assume. Concretely, `诊断` is fairly safe as a substring, but
  `服药`/`服用` appear inside longer compounds, and `注射` appears in safe
  educational contexts (`注射胰岛素的方法`). **Do a systematic scan: for each
  keyword, list every maximal context it appears in across your golden set.** The
  clinical-NLP literature calls the dangerous cases *pseudo-negation* and
  *term-embedded* traps and handles them with an explicit list, not with cleverness.
- **Simplified vs traditional** variants (`诊断`/`診斷`, `治疗`/`治療`,
  `处方`/`處方`) and **full-width vs half-width** punctuation (`，` vs `,`, `：` vs `:`)
  silently defeat both matching and sentence splitting. Normalise before matching.

### 2.2 Chinese negation / speculation cue inventory

This is the direct Chinese analogue of NegEx's trigger lists. The Chinese clinical
NLP literature uses rule-based trigger + scope approaches; the published example
below is the closest match to your needs:

- **"Negation Detection in Chinese Electronic Medical Record Based on Rules and
  Word Co-occurrence"** (Zhang et al., 2014, Springer). Mechanism: **rules combined
  with word co-occurrence**, specifically to fix the failure mode that "the negative
  predictive value drops significantly if the sentence contains several kinds of
  punctuation" — i.e. **punctuation corrupts the scope window**, exactly the
  clause-boundary problem. Reported **NPV 99.85%**, 7.85 points better than plain
  rules, on 200 texts / 150,865 Chinese characters. Honest caveat: NPV alone is a
  weak metric (it ignores recall) and the paper is paywalled; treat the *mechanism*
  as the takeaway, not the number.
  https://www.springerprofessional.de/negation-detection-in-chinese-electronic-medical-record-based-on/4824380
- **"A finite-state automata based negation detection algorithm for Chinese clinical
  documents"** (IEEE PIC 2014, Ge Caixia et al.). Mechanism: compile the trigger
  lists and scope rules into an **FSA** rather than ad-hoc matching. This is the
  cleanest formulation of "trigger + scope" for Chinese.
  https://ieeexplore.ieee.org/document/6972310
- **"Method of detection of negative terminology in Chinese electronic medical
  record"** (PubMed 25997271) — earlier Chinese rule-based negative-terminology
  detection.
  https://pubmed.ncbi.nlm.nih.gov/25997271/
- **"A Hybrid Method to Extract Clinical Information From Chinese Electronic Medical
  Records"** (IEEE 8723036) — makes the key conceptual point in its own words:
  "**In clinical texts, presence of a clinical entity does not necessarily indicate
  presence of a medical condition**." That sentence is the whole argument against
  your current regex.
  https://ieeexplore.ieee.org/document/8723036/

A practical cue inventory (assemble from the above + general Chinese grammar; all of
these are standard in Chinese clinical NLP trigger lists):

| Class | Cues | Effect on a match |
|---|---|---|
| **Negation** | 不, 不能, 不应, 不得, 不要, 别, 勿, 无需, 无须, 禁止, 避免, 没有, 无, 未, 未见, 并非, 不属于, 否认, 阴性, 排除 | **suppress** the match |
| **Speculation / hypothesis** | 可能, 或许, 疑似, 考虑, 待排, 怀疑, 若, 如果, 假如, 一旦, 万一 | **suppress or downgrade** |
| **Conditional / referral** | 如有, 若有, 当…时, 请咨询, 请就医, 遵医嘱, 建议就医, 咨询医生, 前往医院 | **suppress** (this is the safe pattern) |
| **Advisory / prohibitive directive** | 请勿, 不要自行, 切忌, 务必遵, 应在医生指导下 | **suppress** on its own; *increases* risk if paired with a prescriptive dose |
| **Pseudo-negation traps** | 不良反应, 抗生素, 无需 (vs 无需 in checklist), 不 typo in 胰岛素/抗生素, 尿 (not a negation), 无 in 无力/维生素 | **must NOT trigger** — maintain an explicit exception list |
| **Question** | 吗, 呢, 是否, 什么, 怎么, 能不能, ？ | **suppress** or route to a different policy |

Two of your three examples are handled by this table directly:
- `不能诊断任何疾病` → negation cue `不能` immediately pre-poses the target `诊断` ⇒ suppress.
- `请不要自行停药` → prohibitive/advisory cue `不要自行` pre-poses `停药` ⇒ suppress.
- `如有糖尿病请遵医嘱` → conditional `如有` + referral `遵医嘱` ⇒ suppress.

**Important honesty note:** Chinese *double negation* (`并非不能诊断`, `不是没有
糖尿病`) and the `差点儿没P`-style redundant-negation construction are genuinely hard.
The ContextD result already showed hypothetical/uncertain is the weak spot (F 0.13–0.54),
and Chinese has its own literature on redundant negation as a research problem, not a
solved one. Do **not** claim double-negation handling. Use "uncertain ⇒ escalate"
(§3.4) instead.

### 2.3 Segmentation tools — and why you may not need them

| Tool | Status / license | Custom dict | Medical | Offline cost | Verdict for a small project |
|---|---|---|---|---|---|
| **jieba** | very widely used, but effectively **unmaintained** (long-stale upstream; community forks and modernisation attempts exist) | yes, `userdict` / `add_word` | no built-in medical dict, but custom dict works well | pure Python, tiny, fast | **Usable and pragmatic.** Pin it; don't expect upstream fixes. |
| **pkuseg** | moved under spaCy as **spacy-pkuseg**; maintained-ish by explosion | yes | no | needs model download, C extension | Fine, heavier than jieba. |
| **HanLP 1.x** | Java, Apache-2.0, mature | yes | has domain dicts | JVM | Good if you're on JVM. |
| **HanLP 2.x** | PyTorch/TF2, **pretrained models are downloaded from hankcs.com** | via pipeline | strong | large (torch + hundreds of MB models) | **Overkill.** Model-download requirement hurts offline/reproducibility. |
| **LTP (HIT)** | pytorch, maintained | yes | no | model download, ~hundreds MB | Overkill. |
| **THULAC** | C++/Python, older | yes | no | small-ish | Viable but stale. |
| **spaCy zh** | needs a Chinese pipeline package | limited | no | moderate | No advantage over jieba here. |

- jieba: https://github.com/fxsjy/jieba
- spacy-pkuseg: https://github.com/explosion/spacy-pkuseg
- HanLP docs (install/configuration; note model fetching): https://hanlp.hankcs.com/docs/

**The key insight: for keyword/rule matching you should not segment at all.**
Segmentation introduces its own errors and is unnecessary for finding known terms.
Better, cheaper, offline-friendly options:

1. **Longest-match-first /逆向最大匹配** against your own term list — trivially
   implementable, deterministic, explainable.
2. **Aho-Corasick multi-pattern matching** (`pyahocorasick`, or `flashtext`-style
   tries) — one pass, O(text length), returns **all** matches with spans. This gives
   you exact character offsets, which is precisely what you need to compute
   clause-level scope. Pure Python binding over a C library; no model download.
   Aho-Corasick reference: https://www.cbcb.umd.edu/confcour/Spring2008/CMSC858P-materials/notes-2-19.pdf
3. **Clause segmentation, not word segmentation.** Split on Chinese punctuation
   `。！？；，、` and newlines to get clauses. This is the Chinese equivalent of
   ConText's sentence+termination-trigger scoping, and it is what the
   "rules + word co-occurrence" paper was compensating for when punctuation broke
   its windows. ~10 lines of code, fully explainable.

**So: normalise → split into clauses → Aho-Corasick for terms → Aho-Corasick/regex
for cues within the same clause → decide.** No segmentation, no model, no network.

### 2.4 Chinese pretrained assertion/negation models (available but a step up)

- **`bvanaken/clinical-assertion-negation-bert`** — ClinicalBERT fine-tuned to
  classify a *marked entity span* as PRESENT / ABSENT / POSSIBLE. Small, offline
  once cached, and the three-way output maps nicely onto
  allow / block / escalate. **English clinical text only** — you would have to
  re-train for Chinese.
  https://huggingface.co/bvanaken/clinical-assertion-negation-bert
- **CBLUE** baselines (BERT-base, BERT-wwm-ext, RoBERTa-wwm-ext, MacBERT,
  PCL-MedBERT) — Chinese biomedical encoders with public leaderboards. Useful if you
  later want a trained Chinese assertion classifier. **Caveat: CBLUE's eight tasks
  do NOT include an assertion/negation-detection task** — its tasks are CMeEE (NER),
  CMeIE (relation extraction), CHIP-CDN (diagnosis normalisation), CHIP-STS
  (similarity), CHIP-CTC (criteria classification), KUAKE-QIC/QTR/QQR. So CBLUE is
  the *pretraining* resource, not the assertion label source.
  https://ar5iv.labs.arxiv.org/html/2106.08087 · https://github.com/CBLUEbenchmark/CBLUE
- **CMeEE / CMeIE** are the entity and relation datasets (disease, clinical
  manifestations, drugs, procedures, body, examinations, microorganisms, department;
  53 relation types). Useful for a medical *term* gazetteer, not for assertion.
  Their error analyses are also informative: for CMeEE the main failure causes were
  entity overlap, ambiguity, and "needing domain knowledge."
- The Chinese **assertion detection** shared task you'd want is the CCKS-series
  "面向中文电子病历的医疗实体及事件抽取/断言检测" family, not CBLUE.
  https://www.sigkg.cn/ccks2019/?page_id=62

**Verdict for a small project:** do not start with a model. Rule-based + clause scoping
is what the Chinese clinical literature itself reports working well, and it is
offline, zero-dependency, and explainable. Keep a small classifier as an optional
phase-2 tier.

---

## 3. Structural approaches that beat keyword lists

### 3.1 Classify intent / speech act, not topic

The core move: your seven keywords are **topic** markers; you need **speech-act**
markers. Minimal, implementable taxonomy for a fitness/nutrition agent:

| Speech act | Signal | Policy |
|---|---|---|
| **Prescriptive directive** (dangerous) | imperative verb with explicit dose/frequency/self-administration: `每日服用…mg`, `自己注射`, `立即停药`, `按此剂量` | **block** |
| **Prohibitive directive** (safe) | `请勿`, `不要自行`, `切忌`, `禁止自行` + target | allow |
| **Conditional referral** (safe) | `如有…请遵医嘱/就医/咨询医生` | allow |
| **Educational / definitional** (safe) | `…是指`, `…的定义`, `什么是…` | allow |
| **Negated capability/claim** (safe) | `不能/无法 + 诊断/治疗` | allow |
| **Question** (safe-ish) | `吗/是否/？` | allow, or answer with caveat |
| **First-person medical disclosure** (escalate) | `我患有糖尿病`, `我在服用…` | escalate, don't blanket refuse |

This is exactly XSTest's insight generalised: the safe/unsafe pairs differ by
**context and target**, not vocabulary (T3 "Safe Targets", T4 "Safe Contexts",
T5 "Definitions"). XSTest also gives you the contrast-set *construction method*:
take each safe prompt, make a **minimal edit** to produce a clearly unsafe
counterpart. Do this for your rules — `如有糖尿病请遵医嘱` ↔ `糖尿病不用去医院，自己
吃这个就行`. If a rule cannot separate them, the rule is wrong.

- XSTest taxonomy: https://arxiv.org/html/2308.01263v3 (Table 1)
- Classical speech-act cue recognition for advice/warnings: https://preview.aclanthology.org/starsem-semeval-split/C90-3065.pdf
- Chinese medical intent taxonomy (KUAKE-QIC, 11 classes incl. 治疗计划/医嘱/病情诊断): https://ar5iv.labs.arxiv.org/html/2106.08087

### 3.2 Two-stage: cheap high-recall gate → precise semantic check

The architecture you want, and it is the dominant one in production moderation:

- **Stage 1 — gate.** Aho-Corasick / regex over normalised text. Optimised for
  **recall**, deliberately over-triggering. Cheap, explainable, ~microseconds.
- **Stage 2 — arbitration.** Runs *only on gate hits*. Decides allow / block /
  escalate using clause scope + cue tables + speech-act features. This is where your
  false-positive reduction actually happens.
- **Stage 3 (optional) — semantic.** A small local embedding model or a tiny
  classifier, only on stage-2 "uncertain."

**Published systems do exactly this and measure the tradeoff rather than hiding it.**
OR-Bench evaluates 32 models by plotting **over-refusal rate vs toxic-prompt
rejection rate**, with the ideal at the top-left; it reports that the Spearman
correlation between safety and over-refusal is **0.89** — i.e. most systems buy
safety with over-refusal. OR-Bench's own moderation pipeline is itself a cascade:
generate → **ensemble of 3 LLM moderators (GPT-4-turbo, Llama-3-70b, Gemini-1.5-pro),
majority vote** → and then, crucially, **answer the flagged prompt with an
unmoderated model (Mistral-7B) and re-check; if the produced answer is safe, keep the
prompt as safe.** That last trick is directly transferable: *judge the answer, not
the topic.* Ensemble moderator vs human expert: TP 96.0/FN 4.0/TN 84.0/FP 16.0 vs
94.7/5.3/92.0/8.0 — the automated moderator had **twice the false-positive rate** of
the human expert. That is the honest cost of a keyword-sensitive gate.

- OR-Bench: https://ar5iv.labs.arxiv.org/html/2405.20947v5 · https://github.com/justincui03/or-bench · https://huggingface.co/bench-llms

Guardrail-model two-stage examples (documented, but note the cost/latency):
- **WildGuard / WildGuardMix** — open moderation model + dataset suite detecting
  harmful prompts, harmful responses, and refusal behaviour.
- **Llama Guard 1/2/3**, **ShieldGemma**, **Aegis**, **ToxicChat** — the standard
  guard-model family. Health-ORSC-Bench's moderation ensemble used seven of these:
  Granite-Guardian-3.3-8B, Llama-Guard-3-8B, NemoGuard-8B, Qwen3Guard-Gen-8B,
  GPT-OSS-Safeguard-20B, ShieldGemma-2-4B, WildGuard-7B, keeping a prompt only when
  ≥4 of 7 voted it non-harmful.
  https://ar5iv.labs.arxiv.org/html/2601.17642

**Tradeoff, honestly stated:** an 8B guard model is ~GBs of weights, needs GPU or
slow-CPU inference, and adds hundreds of ms to seconds. It is **not** suitable for
"small open-source project, offline, no paid API." Borrow the *architecture*
(cascade + ensemble majority vote + uncertainty tier), not the models.

### 3.3 Whitelisting safe boilerplate / disclaimer handling

Your project currently allows only **two fixed disclaimer strings** and replaces the
whole answer otherwise. That is the fragile part: any *paraphrase* of your own
disclaimer re-trips the rule. What the practice should be:

1. **Canonicalise before scanning.** Maintain a registry of your own disclaimer
   templates. Normalise text (full-width→half-width, strip whitespace/punctuation),
   then match against **normalised templates**, not exact strings. A paraphrase-aware
   comparison (normalised edit distance / token-set ratio ≥ threshold, or a few
   pinned regex templates) tolerates punctuation and wording drift.
2. **Suppress the disclaimer span, don't suppress the whole answer.** Compute match
   offsets first, then **remove/ignore matches that fall inside a recognised
   disclaimer span** before evaluating the rest of the answer. This is the difference
   between "the answer contains a disclaimer" and "the answer contains *only*
   a disclaimer."
3. **Whitelist structural patterns, not strings.** Allow-list patterns like
   `^.{0,40}(请|建议)(咨询|就医|遵医嘱).{0,40}$` per clause, plus the
   `如有X请遵医嘱` conditional template.
4. **Never let the disclaimer become the entire answer.** If the only content is
   boilerplate, that is a *response-quality* problem, not a safety problem — solve it
   with a separate "answer must contain substantive advice" check, so a false
   positive cannot silently become a user-visible refusal.

Honest note: I found **no rigorous published study** of "safe boilerplate
whitelisting" as a named technique. It is standard engineering practice in content
moderation (allow-lists / known-safe patterns / template exemptions) rather than a
research result. The nearest research-adjacent practice is the OR-Bench
"answer-then-re-moderate" loop, which is the same idea in spirit: let a known-safe
generation path exempt a flagged input.

### 3.4 Severity / confidence thresholds and "abstain → escalate"

The binary refuse-or-not design is what produces your user-visible harm. Replace with
three outcomes:

- **allow** — answer ships.
- **block** — genuinely prescriptive/harmful; replace.
- **escalate / abstain** — *keep the answer and attach a caveat*, or route to human
  review, or (in a chat product) flag for monitoring. Do **not** silently replace.

This is well-supported by the literature:

- **Health-ORSC-Bench** (2026, ACL Findings) is the most on-point paper for your
  domain. It argues precisely that "reliance on **binary refusal boundaries** often
  results in over-refusal of benign queries or unsafe compliance with harmful ones,"
  and it introduces **Safe Completion Rate (SCR)** as a second metric alongside
  Over-Refusal Rate (ORR): the proportion of prompts where the model *both*
  acknowledges risk *and* provides substantive information. This is exactly the
  "caveat instead of replace" behaviour. Findings: across 7 health categories and
  30 LLMs, the ideal top-left (high safety, low over-refusal) is **largely
  unoccupied**; up to **80% of "Hard" benign prompts** are refused by
  safety-optimised models; GPT-5 mini reaches **74.2% over-refusal** on the Hard-1K
  set. It also reports "safety-pessimism" in larger frontier models.
  https://ar5iv.labs.arxiv.org/html/2601.17642 · https://aclanthology.org/2026.findings-acl.1177/
  Dataset: https://huggingface.co/datasets/zzha6204/Health-ORSC-Bench
- **OpenAI's output-centric safety training** (cited by Health-ORSC-Bench) is the
  industrial version: three response modes — direct answer for benign requests,
  **safe-completion** (high-level, non-operational guidance) for dual-use content,
  refusal + constructive redirection for genuinely harmful requests — trained with a
  **multiplicative safety × helpfulness reward**.
- **OR-Bench** independently shows defence methods "achieve high defense success but
  significantly raise over-refusal rates."

Design implication: your "generic disclaimer replaces the answer" is the single worst
possible policy under both OR-Bench and Health-ORSC-Bench framings — it maximises
over-refusal while producing no safety completion.

### 3.5 Small local classifier / embedding similarity instead of regex

Feasible and offline, in increasing order of cost:

1. **Feature-based logistic regression on clause features** (no neural net, trains in
   milliseconds, fully inspectable coefficients): features = target term id, cue class
   present, cue position relative to target (pre/post), distance in characters,
   clause length, presence of dose pattern `\d+\s*(mg|g|ml|片|粒|次|天)`, presence of
   imperative marker, question marker, conditional marker, first-person marker.
   **This is the best value-for-effort option** and is trivially explainable. Train on
   a few hundred hand-labelled clauses.
2. **Local Chinese sentence embeddings + nearest-neighbour against labelled
   examples.** Models such as `BAAI/bge-small-zh-v1.5` or `shibing624/text2vec-base-chinese`
   are ~100MB, CPU-runnable, offline once cached. Decision = similarity to nearest
   "blocked" vs "allowed" exemplar, with a margin threshold → escalate when the margin
   is small. Needs `torch`/`sentence-transformers` (heavy dependency, but no API).
3. **Fine-tune a small Chinese encoder** (`hfl/chinese-roberta-wwm-ext`,
   `bert-base-chinese`, or a CBLUE baseline) as an assertion/intent classifier. Best
   accuracy, most work, needs labelled data. Reasonable phase 3.

**Honest assessment:** for seven keywords and three known failure modes, (1) plus
rules is materially sufficient. (2) and (3) are justified only once you have a
labelled set and evidence that rules plateaued.

### 3.6 Windows / Chinese plugin note

`spacy-pkuseg` is the maintained fork of pkuseg and is the Chinese tokenizer used
with spaCy: https://github.com/explosion/spacy-pkuseg. But as argued in §2.3, if you
go the rules route you don't need it. If you do want spaCy's `PhraseMatcher` +
sentence splitting, note medspaCy's ConText assumes English trigger lists and would
need full Chinese localisation — you'd be reimplementing ContextD, which is
instructive but is not a shortcut.

---

## 4. Testing and measuring safety classifiers

### 4.1 The benchmark landscape (what to measure)

| Benchmark | Size | What it measures | Source |
|---|---|---|---|
| **XSTest** | 250 safe + 200 unsafe contrast prompts, 10 safe prompt types | exaggerated safety / false refusal, with a *taxonomy* of why safe prompts look unsafe | https://aclanthology.org/2024.naacl-long.301/ · https://github.com/paul-rottger/exaggerated-safety |
| **OR-Bench** | 80,000 over-refusal prompts (10 categories) + Hard-1K + 600 toxic | over-refusal rate vs toxic rejection rate; the safety/helpfulness tradeoff | https://ar5iv.labs.arxiv.org/html/2405.20947v5 · https://github.com/justincui03/or-bench |
| **Health-ORSC-Bench** | 31,920 benign boundary health prompts, 7 categories, Easy-5K/Medium-5K/Hard-1K + 2,306 toxic seeds | ORR **and** Safe Completion Rate, in *health* specifically | https://ar5iv.labs.arxiv.org/html/2601.17642 |
| **SORRY-Bench** | 44-class taxonomy, 20 linguistic mutations | fine-grained unsafe-compliance; only 10 medical prompts | (cited in Health-ORSC-Bench) |
| **PHTest** | model-tailored pseudo-harmful prompts | red-teaming for over-refusal | (cited in OR-Bench) |
| **MedSafetyBench / CARES / HealthBench** | 1,800 / 18,000 / 5,000 | health safety compliance (CARES uniquely also assesses over-refusal) | (cited in Health-ORSC-Bench) |

**XSTest's 10 safe prompt types** (the most reusable artefact — use these as your
canary *categories*):
T1 Homonyms · T2 Figurative Language · T3 Safe Targets · T4 Safe Contexts ·
T5 Definitions · T6 Real Discrimination, Nonsense Group · T7 Nonsense
Discrimination, Real Group · T8 Historical Events · T9 Privacy (Public) ·
T10 Privacy (Fictional), 25 hand-crafted prompts each.

Mapped to your case, the relevant types are **T3 Safe Targets** (`停药` applied to
*the user's own prescription* vs *a class of drugs in general*), **T4 Safe Contexts**
(`治疗` inside "不能诊断或治疗任何疾病"), and **T5 Definitions**
(`什么是糖尿病`).

### 4.2 How to actually measure your gate

Treat it as a classifier and report the classifier metrics — this is what makes the
work legible in an interview:

- **Per-rule precision / recall**, not just an overall pass rate. Your seven keywords
  should each have their own numbers. A rule with 12% precision is a liability.
- **False-positive rate on a golden allowed set** and **false-negative rate on a
  golden blocked set**, reported separately. Never collapse them into one "accuracy."
- **Over-refusal rate framing** (OR-Bench / Health-ORSC-Bench style): x-axis =
  over-refusal on benign, y-axis = rejection on toxic. Report where your gate sits
  and how the curve moves as you loosen thresholds. This single plot is the strongest
  artefact you can put in a writeup.
- **Contrast pairs / minimal pairs** (XSTest's construction method, HateCheck's
  "functional tests"): for every rule, craft pairs differing in exactly one
  safety-relevant dimension. XSTest's own framing is that these are *functional
  tests*, adapted from software testing — cite that lineage, it's honest and
  interview-friendly.
  https://aclanthology.org/2024.naacl-long.301/
- **Regression suite that pins allowed content.** Every false positive you fix
  becomes a permanent test case. Cheapest high-value practice available.
- **Sentence/clause-level evaluation units.** Score at the clause level, since that
  is your decision unit; document-level scoring hides which clause fired.

**Mutation / property testing for rules** (software-testing side, not safety
literature, but directly applicable): for each rule, define text mutations that must
*not* change the verdict (whitespace, full-width/half-width punctuation, simplified/
traditional, adding a negation cue, wrapping in a disclaimer, converting to a
question) and mutations that *must* (adding an explicit dose, removing the negation
cue). Assert determinism. This turns "the FPR is high" into a specific list of
broken invariants.

**Honest scoping caveat:** a rule-based gate cannot be given a meaningful
"red-team dataset" score the way an LLM can — red-teaming targets generative
behaviour. For a rule gate, the right evidence is precision/recall on a hand-labelled
Chinese golden set, plus the mutation invariants above. Say that explicitly rather
than borrowing LLM-benchmark numbers for a regex.

### 4.3 What the over-refusal literature recommends for *reducing* over-refusal

Consolidated from OR-Bench, XSTest, and Health-ORSC-Bench:

1. **Measure both axes.** Reporting only safety lets over-refusal grow invisibly
   (Spearman 0.89 between the two in OR-Bench). Refuse to accept a safety
   improvement that isn't accompanied by an over-refusal number.
2. **Distinguish dual-use from malicious intent.** Health-ORSC-Bench's intent labels
   (Benign / Dual-use / Malicious) and OpenAI's safe-completion modes both say: for
   dual-use, answer at a high level with warnings rather than refuse.
3. **Do not rely on system prompts / keyword filters for calibration.** XSTest found
   system prompts "a crude and inconsistent method of steering model behaviour";
   guardrail prompts decreased unsafe behaviour *and created* exaggerated safety.
4. **Fix the decision boundary with contrastive examples, not by retraining on more
   refusals.** OR-Bench notes jailbreak defences raise over-refusal; XSTest's
   diagnosis (lexical overfitting) implies the fix is boundary calibration.
5. **Report FP/FN separately from an expert baseline.** OR-Bench's ensemble moderator
   had double the expert FP rate — expect your automated gate to as well, and budget
   the human review for the uncertain tier.

---

## 5. Practical recipe: minimum viable design for a small open-source project

**Target: materially better than bare substring regex, offline, no paid API,
explainable.**

### 5.1 Architecture (5 layers, ~300–500 lines of Python)

```
raw answer
  → L0 normalize        full-width→half-width, stripped, optional simp/trad fold
  → L1 clause split     on 。！？；，、\n  (keep offsets)
  → L2 term match       Aho-Corasick over the 7 terms → (term, start, end, clause_id)
  → L3 context resolve  per match: cue tables within the SAME clause
                          negation / speculation / conditional / advisory / question
                          → verdict ∈ {allow, block, uncertain}
  → L4 policy           allow    → ship unchanged
                        uncertain→ ship WITH caveat (safe completion), log it
                        block    → replace (only this case)
```

### 5.2 The specific changes that kill your three false positives

| Input | Current | New |
|---|---|---|
| 不能诊断任何疾病 | blocked | `不能` is a negation cue pre-posing `诊断` in the same clause ⇒ **allow** |
| 请不要自行停药 | blocked | `不要自行` is a prohibitive/advisory cue ⇒ **allow** |
| 如有糖尿病请遵医嘱 | blocked | `如有` (conditional) + `遵医嘱` (referral) ⇒ **allow** |

And the paired unsafe cases that must still block (your contrast set):
| Input | New |
|---|---|
| 糖尿病不用去医院，按我说的吃 | no referral cue, prescriptive `按我说的` ⇒ **block** |
| 每天服用二甲双胍 500mg，一天两次 | dose pattern + imperative, no cue ⇒ **block** |
| 直接停掉你的处方药 | no prohibitive cue, prescriptive ⇒ **block** |

### 5.3 Dependency budget

- **Required:** Python stdlib + `pyahocorasick` (or a ~40-line trie you write
  yourself) — that's it. Fully offline, no model, no network.
- **Optional (phase 2):** `jieba` only if you later need term *normalisation*, not
  for matching; `scikit-learn` for the clause-level logistic regression.
- **Optional (phase 3):** `sentence-transformers` + a small Chinese model, only on
  the `uncertain` tier.

### 5.4 Test suite (this is the deliverable that makes the work credible)

1. `tests/golden_allowed.jsonl` — 100–200 real Chinese answers that must pass
   (build from your own logs; stratify by XSTest-style categories: negation,
   conditional-referral, educational/definitional, question, first-person disclosure).
2. `tests/golden_blocked.jsonl` — 50–100 answers that must block (prescriptive
   doses, self-medication instructions, "don't see a doctor").
3. `tests/test_contrast_pairs.jsonl` — minimal pairs from §5.2. Any pair the gate
   cannot separate is a bug report against a named rule.
4. `tests/test_invariants.py` — mutation tests: punctuation, width, whitespace,
   wrapping in a disclaimer, adding a negation cue, converting to a question.
5. **CI gate:** fail the build if per-rule precision on the allowed set drops below a
   threshold, or if any pinned allowed answer becomes blocked.

### 5.5 Why this reads well in a resume / interview

You can state, truthfully and specifically:

- "Diagnosed a safety-gate false-positive cluster: seven topic keywords matched as
  bare substrings, so negation (`不能诊断`), prohibitive advice (`请不要自行停药`),
  and conditional referral (`如有糖尿病请遵医嘱`) were all refused. Measured a
  **false-positive rate of X%** on a hand-labelled set of N realistic Chinese answers."
- "Replaced document-level substring matching with **clause-scoped assertion +
  speech-act detection**, modelled on **ConText/NegEx** (four trigger lists: pre-,
  post-, termination, pseudo-triggers) and localised to Chinese using the
  Chinese clinical-NLP **trigger + scope** approach."
- "Added a **golden-set regression suite with XSTest-style contrast pairs and
  mutation invariants**, gating CI on per-rule precision, and reported the
  **over-refusal vs harmful-rejection tradeoff curve** (OR-Bench / Health-ORSC-Bench
  framing) rather than a single accuracy number."
- "Switched the failure policy from **binary refuse-and-replace** to
  **allow / safe-completion-with-caveat / block**, so genuinely safe answers are never
  silently replaced — motivated by the **Safe Completion Rate** metric."

That is a story about measurement, a named architecture, a Chinese-specific
adaptation, and a policy change — all offline and all explainable line-by-line.

### 5.6 What I would explicitly *not* do

- Don't add a Chinese NLP model or an LLM guardrail for seven keywords. It buys
  little and costs the offline/explainable story.
- Don't try to handle double negation or 反问句 robustly. Route them to `uncertain`.
- Don't add more keywords to the block list as your first move — that is the
  direction that created the problem.

---

## 6. Honesty ledger: established vs experimental vs unavailable

**Well-established (cite confidently):**
- NegEx/ConText four-trigger-list + scope + termination mechanism; negation F ≈ 0.87–0.93
  on clinical text. https://pmc.ncbi.nlm.nih.gov/articles/PMC4264258/
- NegEx original: P 84.5% / R 77.8%.
- Exaggerated safety = lexical overfitting; XSTest taxonomy of 10 safe prompt types
  and the contrast-set methodology. https://aclanthology.org/2024.naacl-long.301/
- OR-Bench: Spearman 0.89 safety↔over-refusal; 80K prompts; Hard-1K.
  https://ar5iv.labs.arxiv.org/html/2405.20947v5
- Chinese substring matching needs trigger+scope rules and punctuation-aware
  termination; explicitly documented for Chinese EMR.
  https://www.springerprofessional.de/negation-detection-in-chinese-electronic-medical-record-based-on/4824380
- "Presence of a clinical entity ≠ presence of a condition."
  https://ieeexplore.ieee.org/document/8723036/
- CBLUE's task list and KUAKE-QIC Chinese medical intent classes.
  https://ar5iv.labs.arxiv.org/html/2106.08087

**Reasonable but recent / needs care:**
- Health-ORSC-Bench (2026) — most domain-relevant, but very new; treat its specific
  numbers as the authors' with their setup, not as settled fact.
- Safe-completion as a training objective — clearly directionally supported
  (OpenAI, Health-ORSC-Bench), but the specific training recipe isn't something you'd
  reproduce in a small project.
- TELOS XSTest calibration dataset (Zenodo 18370603) — appeared in search; I could
  not retrieve it to verify its contents, so do not rely on it.

**Weak / not well-supported — do not overclaim:**
- Temporality/hypothetical detection: F 0.13–0.54. Known-hard. Chinese
  double-negation and redundant-negation are active research, not solved.
- "Whitelisting safe boilerplate" has **no rigorous published treatment** I could
  find; it's engineering practice. Present it as such.
- Per-rule precision/recall gating for regex safety rules: standard software
  engineering (functional tests, mutation testing, golden sets) applied to safety —
  the *combination* is not itself a cited research result. Say so.

**Could not verify / not found:**
- A specific published Chinese over-refusal benchmark. Chinese over-refusal data
  appears as a *subset* of multilingual benchmarks (SORRY-Bench's non-English
  mutations), not as a dedicated Chinese benchmark. Building your own small Chinese
  golden set is therefore genuinely valuable and not duplicative.
- The full text of the Springer Chinese negation paper (paywalled); only the abstract
  was retrievable. The finite-state-automata paper was also paywalled. Both
  mechanisms are described from their abstracts.
- CogStack/CliX specifics beyond their existence as GATE-based clinical IE pipelines.

---

## 7. Source index

**Context / negation**
- https://pmc.ncbi.nlm.nih.gov/articles/PMC4264258/ — ContextD: ConText for Dutch (mechanism, trigger counts, scope tuning, results)
- https://europepmc.org/article/MED/30400805 — SIFR annotator, clinical context detection
- https://github.com/medspacy/medspacy — medspaCy
- https://github.com/explosion/spacy-pkuseg — spacy-pkuseg

**Chinese clinical NLP**
- https://www.springerprofessional.de/negation-detection-in-chinese-electronic-medical-record-based-on/4824380 — rules + word co-occurrence, NPV 99.85%
- https://ieeexplore.ieee.org/document/6972310 — FSA-based Chinese negation detection
- https://pubmed.ncbi.nlm.nih.gov/25997271/ — Chinese negative terminology detection
- https://ieeexplore.ieee.org/document/8723036/ — hybrid Chinese EMR extraction
- https://ar5iv.labs.arxiv.org/html/2106.08087 — CBLUE
- https://github.com/CBLUEbenchmark/CBLUE — CBLUE code/data
- https://www.sigkg.cn/ccks2019/?page_id=62 — CCKS 2019 (Chinese EMR assertion-style tasks)
- https://github.com/fxsjy/jieba — jieba
- https://hanlp.hankcs.com/docs/ — HanLP

**Over-refusal / exaggerated safety**
- https://arxiv.org/html/2308.01263v3 — XSTest full text (taxonomy, lexical overfitting, recommendations)
- https://aclanthology.org/2024.naacl-long.301/ — XSTest (NAACL 2024)
- https://github.com/paul-rottger/exaggerated-safety — XSTest data/code
- https://ar5iv.labs.arxiv.org/html/2405.20947v5 — OR-Bench full text
- https://icml.cc/virtual/2025/poster/46052 — OR-Bench (ICML 2025)
- https://github.com/justincui03/or-bench · https://huggingface.co/bench-llms — OR-Bench artefacts
- https://ar5iv.labs.arxiv.org/html/2601.17642 — Health-ORSC-Bench full text
- https://aclanthology.org/2026.findings-acl.1177/ — Health-ORSC-Bench
- https://huggingface.co/datasets/zzha6204/Health-ORSC-Bench — Health-ORSC-Bench data
- https://aclanthology.org/2025.emnlp-industry.138.pdf — Exaggerated Safety (EMNLP 2025 industry)
- https://aclanthology.org/2026.trustnlp-main.26/ — Deactivating Refusal Triggers (over-refusal mitigation)

**Speech act / intent**
- https://preview.aclanthology.org/starsem-semeval-split/C90-3065.pdf — Recognizing advice, warnings, promises and threats

**Assertion models**
- https://huggingface.co/bvanaken/clinical-assertion-negation-bert — ClinicalBERT assertion classifier (PRESENT/ABSENT/POSSIBLE), English

**Matching algorithms**
- https://www.cbcb.umd.edu/confcour/Spring2008/CMSC858P-materials/notes-2-19.pdf — Aho-Corasick
