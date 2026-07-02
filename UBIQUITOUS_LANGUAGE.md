# Ubiquitous Language

## Core Product

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **FitLife Agent** | The whole open-source application for fitness and diet analysis, planning, RAG, evaluation, backend APIs, and frontend UI. | FitLife, 健身助手, 项目 |
| **FitLife Coach Agent** | The single MVP agent that interprets user questions, chooses tools or retrieval, validates outputs, and writes final answers. | Chatbot, 问答机器人, 大模型接口 |
| **Demo User** | The single local user represented by sample data in the MVP. | Account, customer, member |
| **User Profile** | Structured personal context used for analysis and planning, including body metrics, goal, training frequency, preferences, restrictions, and targets. | 用户画像, profile json, preferences |
| **Goal** | The user's primary fitness direction: fat loss, muscle gain, or maintenance. | target, objective, 目标体重 |

## Input Data

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Meal Record** | One CSV row describing a meal item with date, meal type, food, amount, calories, protein, carbs, and fat. | diet record, food row |
| **Workout Record** | One CSV row describing a training activity with date, type, exercise, muscle group, sets, reps, weight, and duration. | training record, exercise row |
| **Knowledge Document** | One Markdown file in the curated fitness and nutrition knowledge base. | doc, note, article |
| **Knowledge Chunk** | A retrievable section produced from a knowledge document with source metadata. | fragment, paragraph |
| **Evaluation Case** | One test question with expected tool, source document, output format, and keywords. | eval question, test prompt |

## Metrics

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Daily Calories** | Total calories consumed on a calendar day from meal records. | calorie intake, today calories |
| **Daily Macros** | Daily protein, carbs, and fat totals from meal records. | macros, nutrition summary |
| **Weekly Average Calories** | Average daily calories across the selected week. | weekly calories |
| **Weekly Average Protein** | Average daily protein across the selected week. | weekly protein |
| **Training Frequency** | Number of workout days or sessions in a selected week. | workout count, exercise frequency |
| **Training Duration** | Total minutes spent training in a selected week. | workout time |
| **Strength Volume** | Strength workload calculated as `sets * reps * weight` for strength records. | volume, load |
| **Undertrained Muscle Group** | A muscle group that appears too rarely in the selected training window. | weak part, missed muscle |

## Agent Architecture

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Intent** | The planner's structured classification of what the user wants. | user type, route, category |
| **Planner** | The graph node that turns a user question into intent, required tools, retrieval need, and output expectation. | router, classifier |
| **Profile Loader** | The graph node that loads and normalizes the user profile. | profile tool, user loader |
| **Data Analyzer** | The graph node that calls deterministic meal and workout tools. | analyzer agent, Python agent |
| **Retriever** | The graph node that retrieves relevant knowledge chunks from the knowledge base. | RAG, searcher |
| **Plan Generator** | The graph node that drafts diet and workout plans. | planner, generator |
| **Validator** | The graph node that checks generated outputs against safety, preference, and structure rules. | evaluator, checker |
| **Report Writer** | The graph node that composes the final Markdown response from profile, tool results, retrieved sources, and validation output. | answer writer, response generator |
| **Tool** | A deterministic function the agent can call to analyze data or load context. | node, endpoint, helper |
| **Trace** | Machine-readable metadata describing intent, tools called, retrieved sources, validation result, and final route. | log, debug info |

## User-Facing Outputs

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Dashboard Summary** | A structured API response powering metric cards and charts on the dashboard. | dashboard data, overview |
| **Agent Answer** | The final Markdown message returned to the chat UI. | response, completion |
| **Weekly Report** | A structured weekly review combining meal metrics, workout metrics, main issues, next-week suggestions, and an action checklist. | summary, report |
| **Generated Plan** | A structured next-week diet and workout plan produced for the demo user. | plan, recommendation |
| **Validation Result** | The validator's pass/fail status, warnings, and repair suggestions for generated content. | eval result, check result |
| **Evaluation Result** | Aggregate and per-case metrics from running the evaluation cases. | validation result, test result |

## Relationships

- A **Demo User** has exactly one **User Profile** in the MVP.
- A **User Profile** supplies targets and restrictions for **Meal Record** analysis, **Generated Plan** creation, and **Validation Result** checks.
- A **Meal Record** contributes to **Daily Calories**, **Daily Macros**, **Weekly Average Calories**, and **Weekly Average Protein**.
- A **Workout Record** contributes to **Training Frequency**, **Training Duration**, and **Strength Volume**.
- A **Knowledge Document** is split into multiple **Knowledge Chunks**.
- The **Retriever** returns **Knowledge Chunks**, not full documents.
- The **FitLife Coach Agent** owns the graph route and produces one **Agent Answer** per chat request.
- The **Planner** selects required **Tools**, but **Tools** remain deterministic functions, not agents.
- The **Validator** produces a **Validation Result** for generated plans and safety-sensitive answers.
- An **Evaluation Case** compares expected behavior with the **Trace** and **Agent Answer**.

## Example Dialogue

> **Dev:** "用户问'我这周蛋白质吃够了吗'，这是直接让 **FitLife Coach Agent** 生成计划吗？"
>
> **Domain expert:** "不是。这个问题的 **Intent** 是 meal analysis，**Planner** 应该让 **Data Analyzer** 调用 meal 工具，读取 **User Profile** 里的 daily protein target。"
>
> **Dev:** "那需要走 **Retriever** 吗？"
>
> **Domain expert:** "可以不走。只有当回答需要解释规则或替代建议时才检索 **Knowledge Chunk**。这类数值判断优先依赖 **Meal Record** 和工具结果。"
>
> **Dev:** "如果用户问'我不想吃鸡胸肉，有什么替代'呢？"
>
> **Domain expert:** "这是 knowledge QA 或 mixed intent。**Retriever** 应该查 meal templates，最终 **Agent Answer** 引用来源，并让 **Validator** 检查是否违反偏好或限制。"

## Flagged Ambiguities

- "Agent" must mean **FitLife Coach Agent** unless the text explicitly says graph node or tool. Avoid calling every node an agent.
- "Planner" is ambiguous because it can mean graph planner or fitness plan generator; use **Planner** for intent routing and **Plan Generator** for diet/workout plans.
- "RAG" is a technique, not a component. Use **Retriever** for the graph node and **Knowledge Document** or **Knowledge Chunk** for retrieved content.
- "Validation" and "Evaluation" are different. **Validation Result** checks one answer or plan before returning it; **Evaluation Result** measures system behavior across many cases.
- "Tool" and "Node" are different. A **Tool** performs deterministic work; a graph node decides when and how to call tools.
- "Profile" and "Preferences" are not interchangeable. **User Profile** contains preferences, restrictions, goals, and body metrics.
