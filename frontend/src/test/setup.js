import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// Every test uses fake API fixtures. Make an un-stubbed network call a hard
// failure so a regression can never silently hit a real backend / provider.
if (!globalThis.fetch || !vi.isMockFunction(globalThis.fetch)) {
  globalThis.fetch = vi.fn(() => {
    throw new Error('unexpected fetch() in a test - stub it with vi.fn()')
  })
}

afterEach(() => {
  cleanup()
  try {
    window.localStorage.clear()
  } catch {
    /* jsdom always has it, but stay defensive */
  }
})
