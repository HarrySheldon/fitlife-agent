import type { UnitSystem } from '../types'

const POUNDS_PER_KILOGRAM = 2.2046226218
const CENTIMETERS_PER_INCH = 2.54
const MILES_PER_KILOMETER = 0.6213711922

export const kgToLb = (value: number) => value * POUNDS_PER_KILOGRAM
export const lbToKg = (value: number) => value / POUNDS_PER_KILOGRAM
export const kmToMi = (value: number) => value * MILES_PER_KILOMETER
export const miToKm = (value: number) => value / MILES_PER_KILOMETER

export function cmToFeetInches(value: number): { feet: number; inches: number } {
  const totalInches = value / CENTIMETERS_PER_INCH
  const feet = Math.floor(totalInches / 12)
  return { feet, inches: round(totalInches - feet * 12, 1) }
}

export const feetInchesToCm = (feet: number, inches: number) => (feet * 12 + inches) * CENTIMETERS_PER_INCH
export const displayWeight = (valueKg: number, units: UnitSystem) => round(units === 'imperial' ? kgToLb(valueKg) : valueKg, 1)
export const metricWeight = (value: number, units: UnitSystem) => round(units === 'imperial' ? lbToKg(value) : value, 4)
export const weightUnit = (units: UnitSystem): 'kg' | 'lb' => units === 'imperial' ? 'lb' : 'kg'

function round(value: number, digits: number): number {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

