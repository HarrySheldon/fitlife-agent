import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../../i18n'
import { mealApi } from '../../services/mealApi'
import type { FoodCatalogItem } from '../../types/meals'
import { FoodCatalogPane } from './FoodCatalogPane'

vi.mock('../../services/mealApi', () => ({
  mealApi: {
    searchFoods: vi.fn(),
    setFavorite: vi.fn(),
  },
}))

const rice: FoodCatalogItem = {
  id: 'food-tfda-A0550601',
  owner_user_id: null,
  source: 'public',
  source_name: 'Taiwan FDA Food Nutrient Database',
  source_record_id: 'A0550601',
  dataset_version: '2025-12-22',
  name: '米饭',
  basis_type: 'per_100g',
  basis_amount: 100,
  unit: 'g',
  calories: 182,
  carbs: 41,
  protein: 3.1,
  fat: 0.3,
  license: 'Taiwan Government Open Data License 1.0',
  attribution: 'Taiwan Food and Drug Administration',
  provenance: {},
  content_hash: 'rice-hash',
  active: true,
  aliases: ['白飯', '白饭', 'Cooked rice'],
  is_favorite: false,
  use_count: 0,
  last_used_at: null,
  rank_group: 3,
}

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en-US')
  vi.mocked(mealApi.searchFoods).mockResolvedValue([rice])
})

describe('FoodCatalogPane', () => {
  it('renders the Mainland name returned for a legacy search term', async () => {
    render(
      <FoodCatalogPane
        selectedCatalogIds={[]}
        onAddCatalogFood={vi.fn()}
        onAddCustomFood={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('Search foods'), {
      target: { value: 'Cooked rice' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))

    expect(await screen.findByText('米饭')).toBeInTheDocument()
    expect(mealApi.searchFoods).toHaveBeenCalledWith('Cooked rice')
  })
})
