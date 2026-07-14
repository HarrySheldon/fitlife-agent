import type { EvalResult } from '../types'

const EVALUATION_LABEL_KEYS: Record<string, string> = {
  by_expected_tool: 'evaluation.labels.expectedTool',
  by_retrieval_requirement: 'evaluation.labels.retrievalRequirement',
  no_retrieval_expected: 'evaluation.labels.noRetrievalExpected',
  requires_retrieval: 'evaluation.labels.requiresRetrieval',
  none: 'evaluation.labels.noSpecificTool',
  analyze_meals: 'evaluation.labels.analyzeMeals',
  analyze_workouts: 'evaluation.labels.analyzeWorkouts',
  retrieve_knowledge: 'evaluation.labels.retrieveKnowledge',
  generate_weekly_report: 'evaluation.labels.generateWeeklyReport',
  generate_next_week_plan: 'evaluation.labels.generateNextWeekPlan',
  validate_plan: 'evaluation.labels.validatePlan',
  tool_call: 'evaluation.labels.toolCall',
  retrieval: 'evaluation.labels.retrieval',
  keywords: 'evaluation.labels.keywords',
  answer_format: 'evaluation.labels.answerFormat',
  validator: 'evaluation.labels.validator',
}

export function formatRate(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function evaluationLabelKey(value: string): string | null {
  return EVALUATION_LABEL_KEYS[value] ?? null
}

export function failureSummary(result: EvalResult): {
  key: 'evaluation.allPassedSummary' | 'evaluation.failedSummary'
  values: { failed: number; total: number }
} {
  const failed = result.failed_cases.length
  return {
    key: failed === 0 ? 'evaluation.allPassedSummary' : 'evaluation.failedSummary',
    values: { failed, total: result.total_tests },
  }
}
