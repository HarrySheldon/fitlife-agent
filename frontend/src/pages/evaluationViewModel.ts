import type { EvalResult } from '../types'

const GROUP_LABELS: Record<string, string> = {
  by_expected_tool: 'Expected tool',
  by_retrieval_requirement: 'Retrieval requirement',
  no_retrieval_expected: 'No retrieval expected',
  requires_retrieval: 'Requires retrieval',
  none: 'No specific tool',
}

export function formatRate(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function formatGroupKey(key: string): string {
  if (GROUP_LABELS[key]) return GROUP_LABELS[key]
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function summarizeFailures(result: EvalResult): string {
  const failed = result.failed_cases.length
  if (failed === 0) return `All ${result.total_tests} cases passed`
  return `${failed} of ${result.total_tests} cases failed`
}
