import type { EvalResult } from '../types'
import { evaluationLabelKey, failureSummary, formatRate } from './evaluationViewModel'

// Included by tsconfig as a lightweight compile-time contract for Evaluation v2 fields.
const sample: EvalResult = {
  total_tests: 2,
  pass_rate: 0.5,
  tool_call_success_rate: 1,
  retrieval_hit_rate: 0.5,
  structured_output_success_rate: 1,
  preference_compliance_rate: 0.5,
  validator_pass_rate: 1,
  group_metrics: {
    by_expected_tool: {
      analyze_meals: { total: 1, pass_rate: 1 },
      retrieve_knowledge: { total: 1, pass_rate: 0 },
    },
    by_retrieval_requirement: {
      no_retrieval_expected: { total: 1, pass_rate: 1 },
      requires_retrieval: { total: 1, pass_rate: 0 },
    },
  },
  failed_cases: [
    {
      question: 'What can replace chicken breast?',
      expected_tool: 'retrieve_knowledge',
      expected_retrieval_doc: 'meal_templates.md',
      passed: false,
      tool_ok: true,
      retrieval_ok: false,
      structured_ok: true,
      keywords_ok: false,
      validator_ok: true,
      checks: [
        {
          name: 'retrieval',
          passed: false,
          expected: 'meal_templates.md',
          observed: ['fitness_rules.md'],
          reason: 'Expected retrieval source meal_templates.md but observed fitness_rules.md.',
        },
      ],
      failure_reasons: ['Expected retrieval source meal_templates.md but observed fitness_rules.md.'],
      trace: { tool_calls: ['retrieve_knowledge'], retrieved_sources: ['fitness_rules.md'] },
    },
  ],
  cases: [],
}

const passRateText: string = formatRate(sample.pass_rate)
const groupLabel: string | null = evaluationLabelKey('requires_retrieval')
const summary = failureSummary(sample)

void passRateText
void groupLabel
void summary
