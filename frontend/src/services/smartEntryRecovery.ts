const generations = new Map<string, number>()
const listeners = new Set<(owner: string) => void>()
export function recoveryOwner(key: string): string | null {
  return /^(?:fitlife:)?smart-entry:([^:]+):/.exec(key)?.[1] ?? null
}
export function recoveryGeneration(owner: string | null): number {
  return owner ? generations.get(owner) ?? 0 : 0
}
export function onSmartEntryLogout(listener: (owner: string) => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
export function clearSmartEntryRecovery(owner: string) {
  generations.set(owner, recoveryGeneration(owner) + 1)
  try {
    const keys = Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index))
    keys.forEach((key) => { if (key && recoveryOwner(key) === owner) localStorage.removeItem(key) })
  } catch { /* Browser storage is optional. */ }
  listeners.forEach((listener) => listener(owner))
}
export function removeRecovery(key: string) {
  try { localStorage.removeItem(key) } catch { /* Browser storage is optional. */ }
}
export async function commandFingerprint(value: unknown): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(value))))
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]))
  return value
}
