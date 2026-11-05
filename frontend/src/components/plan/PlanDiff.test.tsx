import { render, screen } from '@testing-library/react'
import { beforeEach, expect, it } from 'vitest'
import i18n from '../../i18n'
import { PlanDiff } from './PlanDiff'

beforeEach(async()=>{await i18n.changeLanguage('en-US')})
it('shows deterministic location and units while keeping raw paths in collapsed details',()=>{
  render(<PlanDiff candidate={{candidate_id:'candidate',digest:'digest',round:0,expires_at:null,
    diff:[{domain:'training',path:'workout_plan.days.0.exercises.0.sets',old_value:3,new_value:4,
      context:['Monday','Bench press'],change_kind:'changed',source:'validated_candidate'}]}} />)
  expect(screen.getByText(/Monday \/ Bench press \/ Sets/)).toBeInTheDocument()
  expect(screen.getByText('3 sets')).toBeInTheDocument()
  expect(screen.getByText('4 sets')).toBeInTheDocument()
  expect(screen.getByText('workout_plan.days.0.exercises.0.sets').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText(/No changes/)).toBeInTheDocument()
})
it('does not omit unknown fields or added objects',()=>{
  render(<PlanDiff candidate={{candidate_id:'candidate',digest:'digest',round:0,expires_at:null,
    diff:[{domain:'training',path:'workout_plan.custom',old_value:null,new_value:{new_rule:'keep visible'},
      change_kind:'added',source:'validated_candidate'}]}} />)
  expect(screen.getByText('Added')).toBeInTheDocument()
  expect(screen.getByText('Other field: new_rule')).toBeInTheDocument()
  expect(screen.getByText('keep visible')).toBeInTheDocument()
})
