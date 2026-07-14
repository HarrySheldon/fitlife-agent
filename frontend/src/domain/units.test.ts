import { describe, expect, it } from 'vitest'

import { cmToFeetInches, feetInchesToCm, kgToLb, kmToMi, lbToKg, miToKm } from './units'


describe('unit conversions', () => {
  it('round-trips kilograms and pounds without changing the metric source', () => {
    expect(lbToKg(kgToLb(72))).toBeCloseTo(72, 5)
  })

  it('round-trips centimeters and feet/inches', () => {
    const display = cmToFeetInches(175)

    expect(display).toEqual({ feet: 5, inches: 8.9 })
    expect(feetInchesToCm(display.feet, display.inches)).toBeCloseTo(175, 1)
  })

  it('round-trips kilometers and miles', () => {
    expect(miToKm(kmToMi(10))).toBeCloseTo(10, 5)
  })
})
