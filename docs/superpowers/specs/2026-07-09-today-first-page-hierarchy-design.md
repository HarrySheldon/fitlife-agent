# Today-First Page Hierarchy Design

**Status:** Draft for review  
**Date:** 2026-07-09  
**Scope:** Product information architecture and page responsibility boundaries for FitLife Agent v0.2

## 1. Problem

The current UI still reflects the MVP implementation shape. Top-level navigation exposes backend capabilities as separate pages: Dashboard, Records, Chat, Weekly Report, Plan, and Evaluation. This makes the app feel like a framework-built demo because users must understand which technical capability they want before they can complete a daily fitness workflow.

FitLife Agent v0.2 should instead feel like a record-driven product. The page hierarchy must be organized around what the user does every day:

- check today's state;
- record meals and training;
- understand goal gaps;
- review trends and weekly summaries;
- adjust the next plan;
- maintain profile and personalization data.

Agent behavior should be embedded into those workflows. The Agent is a product capability, not the primary information architecture.

## 2. Chosen Direction

Use a **Today-first** model.

The default authenticated entry becomes **Today**, a daily operating desk for the selected date. It brings together:

- daily summary;
- meal and workout records;
- target gaps;
- quick form entry;
- smart natural-language entry;
- contextual Agent explanation and suggestions.

This is preferred over a record-first or plan-first model because it best matches repeat daily use. The user does not open the product to inspect a list of features; they open it to answer "What should I do or record today?"

## 3. Top-Level Navigation

Ordinary users should see this primary navigation:

| Navigation | Primary Job | Current Source |
| --- | --- | --- |
| **Today** | Daily status, selected-day records, quick input, Agent explanation for the day. | Dashboard + Records + Chat |
| **Logbook** | Calendar history, detailed meal/workout records, CSV import, data correction. | Records + Upload |
| **Review** | Weekly report, trend review, deviation analysis, generated insights. | Dashboard + Weekly Report + Chat |
| **Plan** | Current plan, next-week generation, validation warnings, plan adjustments. | Plan + Chat |
| **Profile** | Body state, goal state, experience level, restrictions, target suggestions, account/settings. | Profile + Settings |

Developer-only surfaces should be hidden from ordinary navigation:

| Surface | New Boundary |
| --- | --- |
| Evaluation | Developer page or debug route only. It is a testing harness, not user product surface. |
| Trace | Developer-only diagnostic output. It may be visible in debug mode, not in normal pages. |
| Upload | Not a top-level page. CSV import belongs inside Logbook as an advanced input method. |
| Standalone Chat | Replaced by contextual Coach panels and actions. A debug chat route may remain for development. |

## 4. Page Responsibilities

### Today

Today is the authenticated home page.

It answers:

- What happened today?
- Am I close to my calorie, protein, and training expectations?
- What record should I add next?
- What does the Agent think about today's state?

Required modules:

- selected date control;
- calorie and protein progress against suggested or overridden targets;
- training completion state for the selected date;
- meal list and workout list;
- smart entry box;
- compact meal form;
- compact workout form;
- Coach panel with actions such as "Explain today's gap", "Suggest dinner", and "Adjust today's training".

Today should not show every historical chart. It should be dense enough for daily use but not become a full analytics page.

### Logbook

Logbook is the historical record workspace.

It answers:

- What did I record on previous days?
- Which days are incomplete?
- Can I correct or import records?

Required modules:

- month or rolling calendar;
- selected-day detail;
- meal and workout record lists;
- full create/edit/delete record forms after the MVP form grows beyond append-only;
- CSV import for meals and workouts;
- import status and validation errors.

Logbook owns data maintenance. Today may create records quickly, but Logbook is where the user audits and fixes historical data.

### Review

Review is the analysis and reflection workspace.

It answers:

- What patterns happened this week?
- Why did I miss or exceed targets?
- What should change next week?

Required modules:

- weekly report generation and display;
- calorie, protein, training frequency, and duration trends;
- deviation analysis from targets;
- Agent explanation for the report;
- action checklist derived from the report.

Review should replace the current separate Weekly Report page. Report generation is an action inside Review, not a navigation concept.

### Plan

Plan is the future execution workspace.

It answers:

- What is my current plan?
- What should I do next week?
- Is the generated plan safe and consistent with my profile?
- What needs adjustment based on recent records?

Required modules:

- current plan state;
- next-week plan generation;
- diet plan section;
- workout plan section;
- validation warnings and repair suggestions;
- Agent adjustment action, using recent records and profile context.

Plan remains top-level because future execution is a distinct user job. It should no longer feel like a single "Generate plan" API button.

### Profile

Profile is the personalization and account workspace.

It answers:

- Who is this user in the product model?
- What is their body state, goal state, and experience level?
- Which targets are system-suggested and which are user-overridden?
- What settings affect product behavior?

Required modules:

- account identity;
- experience level: beginner, novice, experienced;
- body state;
- goal state;
- weekly training frequency;
- training preference;
- restrictions/allergies/foods not eaten;
- suggested calorie and protein targets;
- advanced overrides for calorie/protein targets;
- language and model configuration settings.

Profile should also expose the user's position/level as editable data. Onboarding writes into Profile; Profile can later update the same fields.

## 5. Agent Placement

The ordinary product should not depend on a standalone Chat page as the main Agent surface.

Use contextual Coach surfaces:

- Today Coach: explains daily target gaps and parses smart entries.
- Logbook Coach: helps normalize messy records and identify missing days.
- Review Coach: explains weekly report findings and deviations.
- Plan Coach: generates and adjusts future plans with validation.
- Profile Coach: suggests targets from body state, goal, and training frequency.

The backend may still keep a general `/chat` endpoint and a development chat page. The product UI should route most user questions through contextual prompts so the Agent receives clear task context and the user sees why the answer matters.

## 6. Route Mapping

Proposed user-facing route names:

| Route | Page |
| --- | --- |
| `/` | Today |
| `/logbook` | Logbook |
| `/review` | Review |
| `/plan` | Plan |
| `/profile` | Profile |

Compatibility redirects:

| Old Route | Redirect |
| --- | --- |
| `/records` | `/logbook` |
| `/dashboard` | `/` |
| `/report` | `/review` |
| `/upload` | `/logbook` |
| `/chat` | debug-only route or contextual redirect depending on implementation phase |
| `/evaluation` | developer-only route |

## 7. Layout Direction

The UI should feel like a focused productivity product:

- restrained navigation labels;
- fewer page-sized feature explanations;
- page titles based on user jobs, not implementation concepts;
- stable side navigation on desktop;
- responsive bottom or compact navigation on mobile;
- right-side Coach panel on desktop where space allows;
- inline Coach drawer on mobile;
- no marketing hero treatment inside the authenticated app.

Cards should represent actual repeated items or bounded tools. Page sections should be full-width work areas rather than nested decorative cards.

## 8. Product Rules

- Records are the source of truth for dashboards, reviews, and plans.
- Targets are suggested by the system/Agent from profile data, with advanced user overrides.
- Experience level changes information density, Agent answer style, and plan strategy, not the core routes.
- New users and long-inactive users should be guided through profile completion before heavy personalization.
- If profile data is incomplete, Today and Review should still work from records but show clear limitations.
- Evaluation and trace outputs are for development, quality, and resume explanation; they are not ordinary user workflows.

## 9. Implementation Boundary

This design does not require replacing backend contracts immediately. A practical migration can reuse existing endpoints:

- Today can compose `/dashboard/summary`, `/calendar/day`, `/calendar/days`, `/calendar/agent-entry`, `/calendar/meals`, and `/calendar/workouts`.
- Logbook can start from the current Records page and rename/restructure it.
- Review can compose the current Dashboard trends and weekly report endpoint.
- Plan can reuse `/plan/generate` while adding current-plan state later.
- Profile can extend the current profile form and settings page.

The first implementation phase should prioritize navigation and page composition over new analytics. The goal is to make the same working system feel like a coherent product before adding deeper features.

## 10. Acceptance Criteria

The page hierarchy redesign is successful when:

- ordinary navigation no longer exposes Upload, Evaluation, Trace, or standalone Chat as primary product pages;
- `/` opens a Today workspace centered on the selected date;
- users can add meal/workout records from Today and inspect history in Logbook;
- weekly report generation lives inside Review;
- plan generation and validation live inside Plan;
- Profile owns onboarding/profile/settings personalization fields;
- Agent actions appear in context on Today, Review, Plan, and Profile;
- existing backend functionality remains available through the new page organization;
- old MVP routes either redirect or become explicitly developer-only.
