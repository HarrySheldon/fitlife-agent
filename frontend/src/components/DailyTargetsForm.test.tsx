import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { DailyTargetVersion, TargetPreview } from '../types'
import { DailyTargetsForm } from './DailyTargetsForm'


const currentTarget: DailyTargetVersion = {
  id: 'target-1',
  user_id: 'user-1',
  profile_version_id: 'profile-1',
  overall_goal_version_id: 'goal-1',
  calories: 2172,
  carbs: 291,
  protein: 126,
  fat: 56,
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  rationale: {},
  effective_from: '2026-07-23T09:00:00Z',
  created_at: '2026-07-23T09:00:00Z',
}

const baseProps = {
  currentTarget,
  preview: null,
  restriction: null,
  history: [],
  historyLoading: false,
  historyError: null,
  stalePreview: false,
  saving: false,
  calculating: false,
  confirming: false,
  onCalculate: vi.fn(),
  onConfirm: vi.fn(),
}

const manualPreview: TargetPreview = {
  profile_version_id: 'profile-1',
  overall_goal_version_id: 'goal-1',
  targets: { calories: 2172, carbs: 291, protein: 126, fat: 56 },
  source: 'manual',
  formula_version: null,
  warnings: [],
  requires_confirmation: false,
  preview_token: 'a'.repeat(64),
}

const deterministicPreview: TargetPreview = {
  ...manualPreview,
  source: 'deterministic_calculation',
  formula_version: 'mifflin_st_jeor_v1',
  preview_token: 'b'.repeat(64),
}

describe('DailyTargetsForm', () => {
  it.each(['saving', 'calculating', 'confirming'] as const)(
    'locks manual controls while %s is busy',
    async (busyState) => {
      const user = userEvent.setup()
      const { rerender } = render(<DailyTargetsForm {...baseProps} />)

      await user.click(screen.getByLabelText('Set targets manually'))
      rerender(<DailyTargetsForm {...baseProps} {...{ [busyState]: true }} />)

      expect(screen.getByLabelText('Set targets manually')).toBeDisabled()
      expect(screen.getByLabelText('Calories (kcal)')).toBeDisabled()
      expect(screen.getByLabelText('Carbohydrate (g)')).toBeDisabled()
      expect(screen.getByLabelText('Protein (g)')).toBeDisabled()
      expect(screen.getByLabelText('Fat (g)')).toBeDisabled()
    },
  )

  it('invalidates a clean manual preview when a deterministic preview replaces it', async () => {
    const user = userEvent.setup()
    const recalculatedManualPreview = {
      ...manualPreview,
      preview_token: 'c'.repeat(64),
    }
    const onCalculate = vi.fn().mockResolvedValue(recalculatedManualPreview)
    const { rerender } = render(
      <DailyTargetsForm {...baseProps} onCalculate={onCalculate} />,
    )

    await user.click(screen.getByLabelText('Set targets manually'))
    rerender(
      <DailyTargetsForm {...baseProps} preview={manualPreview} onCalculate={onCalculate} />,
    )
    expect(screen.getByRole('button', { name: 'Confirm daily targets' })).toBeEnabled()

    rerender(
      <DailyTargetsForm {...baseProps} preview={deterministicPreview} onCalculate={onCalculate} />,
    )
    expect(screen.queryByRole('button', { name: 'Confirm daily targets' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Review manual targets' }))
    expect(onCalculate).toHaveBeenCalledWith(manualPreview.targets)
    rerender(
      <DailyTargetsForm
        {...baseProps}
        preview={recalculatedManualPreview}
        onCalculate={onCalculate}
      />,
    )
    expect(screen.getByRole('button', { name: 'Confirm daily targets' })).toBeEnabled()
  })
})
