import { describe, it, expect, beforeEach } from 'vitest'
import {
  applyRowEdit,
  buildCreatePayload,
  deriveFromParts,
  deriveFromTotal,
  emptyRow,
  isPollingStatus,
  isTerminalStatus,
  llmBlockedReasons,
  loadActiveJobId,
  orderQuestions,
  parseCeiling,
  parseCount,
  pricingWarnings,
  retryableSlots,
  rowNumbers,
  saveActiveJobId,
  startBlockers,
  stripJobMetadata,
  SEVEN_PUBLIC_FIELDS,
  syncJobIdToUrl,
  totalLlmRequested,
  validateRow,
} from './examGen.js'

describe('parseCount', () => {
  it('treats an empty box as 0', () => {
    expect(parseCount('')).toEqual({ value: 0, valid: true, empty: true })
  })
  it('accepts whole non-negative numbers', () => {
    expect(parseCount('7')).toMatchObject({ value: 7, valid: true })
    expect(parseCount(' 12 ')).toMatchObject({ value: 12, valid: true })
  })
  it('rejects negatives, decimals and non-numbers (never clamps)', () => {
    for (const bad of ['-1', '1.5', 'abc', '3x', '--', '1e2']) {
      expect(parseCount(bad)).toMatchObject({ value: null, valid: false })
    }
  })
})

describe('C / A / B arithmetic', () => {
  it('editing C sets A=ceil(C/2), B=floor(C/2)', () => {
    expect(deriveFromTotal(10)).toEqual({ total: 10, database: 5, llm: 5 })
    expect(deriveFromTotal(7)).toEqual({ total: 7, database: 4, llm: 3 })
    expect(deriveFromTotal(0)).toEqual({ total: 0, database: 0, llm: 0 })
    expect(deriveFromTotal(1)).toEqual({ total: 1, database: 1, llm: 0 })
  })
  it('editing A or B sets C=A+B', () => {
    expect(deriveFromParts(3, 4)).toEqual({ total: 7, database: 3, llm: 4 })
  })

  it('applyRowEdit couples the fields through the raw string row', () => {
    let row = emptyRow()
    row = applyRowEdit(row, 'total', '9')
    expect(row).toEqual({ total: '9', database: '5', llm: '4' })

    row = applyRowEdit(row, 'database', '2')
    expect(row).toEqual({ total: '6', database: '2', llm: '4' }) // C = A + B

    row = applyRowEdit(row, 'llm', '10')
    expect(row).toEqual({ total: '12', database: '2', llm: '10' })
  })

  it('applyRowEdit keeps an invalid entry verbatim and does not recompute', () => {
    let row = applyRowEdit(emptyRow(), 'total', 'abc')
    expect(row.total).toBe('abc')
    expect(row.database).toBe('0') // unchanged, not clamped
    const { errors } = validateRow(row)
    expect(errors.total).toBeTruthy()
  })
})

describe('validateRow', () => {
  it('flags A over DB availability and blocks (no silent clamp)', () => {
    const row = applyRowEdit(emptyRow(), 'database', '8')
    const { errors, ok } = validateRow(row, 5)
    expect(ok).toBe(false)
    expect(errors.availability).toContain('5')
  })
  it('passes when A is within availability', () => {
    const row = applyRowEdit(emptyRow(), 'total', '6') // A=3
    expect(validateRow(row, 3).ok).toBe(true)
  })
  it('flags a broken A+B==C invariant', () => {
    const row = { total: '5', database: '1', llm: '1' }
    expect(validateRow(row, 99).errors.sum).toBeTruthy()
  })
})

describe('readiness gating', () => {
  const rowsWithLlm = { מבוא: { total: '2', database: '1', llm: '1' } }
  const rowsDbOnly = { מבוא: { total: '2', database: '2', llm: '0' } }

  it('missing/mismatched pricing blocks only when B > 0', () => {
    const notReady = { ready_for_llm: false, blocking_reasons: ['pricing incomplete'] }
    expect(llmBlockedReasons(rowsWithLlm, notReady)).toEqual(['pricing incomplete'])
    expect(llmBlockedReasons(rowsDbOnly, notReady)).toEqual([])
  })
  it('stale pricing only warns, never blocks', () => {
    const ready = { ready_for_llm: true, warnings: ['pricing snapshot is 40 days old'] }
    expect(llmBlockedReasons(rowsWithLlm, ready)).toEqual([])
    expect(pricingWarnings(ready)).toEqual(['pricing snapshot is 40 days old'])
  })
  it('totalLlmRequested sums B across categories', () => {
    expect(
      totalLlmRequested({
        a: { total: '4', database: '2', llm: '2' },
        b: { total: '3', database: '3', llm: '0' },
      }),
    ).toBe(2)
  })
})

describe('parseCeiling', () => {
  it('accepts a positive dollar amount, optional $ and up to 2 decimals', () => {
    expect(parseCeiling('5')).toEqual({ value: 5, valid: true })
    expect(parseCeiling('$7.50')).toEqual({ value: 7.5, valid: true })
  })
  it('rejects zero, negatives and junk', () => {
    for (const bad of ['0', '-2', 'abc', '1.234', '']) {
      expect(parseCeiling(bad).valid).toBe(false)
    }
  })
})

describe('startBlockers', () => {
  const categories = [
    { name: 'מבוא', question_count: 5 },
    { name: 'גזע המוח', question_count: 1 },
  ]
  const availabilityByName = { מבוא: 5, 'גזע המוח': 1 }

  it('blocks an empty request', () => {
    const b = startBlockers({
      rows: {},
      availabilityByName,
      ceilingRaw: '5.00',
      readiness: null,
    })
    expect(b.some((x) => x.includes('לפחות שאלה אחת'))).toBe(true)
  })

  it('is ready for a valid DB-only request even when LLM is not ready', () => {
    const rows = { מבוא: applyRowEdit(emptyRow(), 'total', '4') } // 2 / 2 -> wait, total 4 => A2 B2
    rows['מבוא'] = { total: '4', database: '4', llm: '0' }
    const b = startBlockers({
      rows,
      availabilityByName,
      ceilingRaw: '5.00',
      readiness: { ready_for_llm: false, blocking_reasons: ['no key'] },
    })
    expect(b).toEqual([])
  })

  it('blocks a bad ceiling', () => {
    const rows = { מבוא: { total: '2', database: '2', llm: '0' } }
    const b = startBlockers({
      rows,
      availabilityByName,
      ceilingRaw: '0',
      readiness: null,
    })
    expect(b.some((x) => x.includes('תקרת עלות'))).toBe(true)
  })

  it('blocks when A exceeds availability', () => {
    const rows = { 'גזע המוח': { total: '3', database: '3', llm: '0' } }
    const b = startBlockers({
      rows,
      availabilityByName,
      ceilingRaw: '5.00',
      readiness: null,
    })
    expect(b.some((x) => x.includes('גזע המוח'))).toBe(true)
  })
})

describe('buildCreatePayload', () => {
  const categories = [
    { name: 'מבוא', question_count: 9 }, // canonical idx 0
    { name: 'היסטולוגיה', question_count: 9 }, // canonical idx 7
    { name: 'גרעיני הבסיס', question_count: 9 }, // canonical idx 6
  ]

  it('keeps only rows with total > 0 and preserves the given (canonical) order', () => {
    const rows = {
      היסטולוגיה: { total: '2', database: '1', llm: '1' },
      מבוא: { total: '4', database: '2', llm: '2' },
      'גרעיני הבסיס': { total: '0', database: '0', llm: '0' },
    }
    const payload = buildCreatePayload(rows, categories, '6.00')
    expect(Object.keys(payload.categories)).toEqual(['מבוא', 'היסטולוגיה'])
    expect(payload.categories['מבוא']).toEqual({ total: 4, database: 2, llm: 2 })
    expect(payload.cost_ceiling_usd).toBe('6.00')
  })

  it('falls back to the default ceiling when the box is invalid', () => {
    const payload = buildCreatePayload(
      { מבוא: { total: '2', database: '2', llm: '0' } },
      categories,
      'not-a-number',
    )
    expect(payload.cost_ceiling_usd).toBe('5.00')
  })
})

describe('orderQuestions / stripJobMetadata', () => {
  const jobQuestions = [
    {
      number: 2,
      question: 'q2',
      answer1: 'a',
      answer2: 'b',
      answer3: 'c',
      answer4: 'd',
      correct_answer: 3,
      origin: 'llm',
      instance_id: 'iid-2',
      id: null,
      category: 'מבוא',
      categories: ['מבוא'],
      generation_meta: { attempts: 2, cost_usd: '0.34' },
      accuracy_list: [],
    },
    {
      number: 1,
      question: 'q1',
      answer1: 'a',
      answer2: 'b',
      answer3: 'c',
      answer4: 'd',
      correct_answer: 1,
      origin: 'database',
      instance_id: 'iid-1',
      id: 42,
      category: 'מבוא',
    },
  ]

  it('orders by global number', () => {
    expect(orderQuestions(jobQuestions).map((q) => q.number)).toEqual([1, 2])
  })

  it('strips every job-only field, keeping exactly the seven public fields in order', () => {
    const stripped = stripJobMetadata(jobQuestions)
    expect(stripped.map((q) => q.number)).toEqual([1, 2])
    for (const q of stripped) {
      expect(Object.keys(q).sort()).toEqual([...SEVEN_PUBLIC_FIELDS].sort())
      expect(q).not.toHaveProperty('origin')
      expect(q).not.toHaveProperty('instance_id')
      expect(q).not.toHaveProperty('generation_meta')
      expect(q).not.toHaveProperty('id')
      expect(q).not.toHaveProperty('categories')
    }
    // answer order untouched (DOCX endpoint owns randomisation)
    expect(stripped[1]).toMatchObject({ answer1: 'a', answer2: 'b', answer3: 'c', answer4: 'd' })
  })
})

describe('status helpers', () => {
  it('classifies polling vs terminal', () => {
    expect(isPollingStatus('queued')).toBe(true)
    expect(isPollingStatus('running')).toBe(true)
    for (const s of ['completed', 'partial', 'interrupted', 'cost_ceiling', 'failed']) {
      expect(isPollingStatus(s)).toBe(false)
      expect(isTerminalStatus(s)).toBe(true)
    }
  })
})

describe('retryableSlots', () => {
  it('returns only failed/interrupted/cost_ceiling LLM slots', () => {
    const view = {
      categories: {
        מבוא: {
          slots: [
            { slot_id: 's1', kind: 'llm', status: 'failed', number: 1 },
            { slot_id: 's2', kind: 'llm', status: 'accepted', number: 2 },
            { slot_id: 's3', kind: 'database', status: 'failed', number: 3 },
            { slot_id: 's4', kind: 'llm', status: 'cost_ceiling', number: 4 },
          ],
        },
      },
    }
    expect(retryableSlots(view).map((s) => s.slot_id)).toEqual(['s1', 's4'])
  })
})

describe('active-job persistence', () => {
  beforeEach(() => {
    window.localStorage.clear()
    syncJobIdToUrl(null)
  })

  it('round-trips through localStorage', () => {
    saveActiveJobId('job-abc')
    expect(loadActiveJobId()).toBe('job-abc')
    saveActiveJobId(null)
    expect(loadActiveJobId()).toBeNull()
  })

  it('prefers a job id present in the URL query', () => {
    saveActiveJobId('from-storage')
    syncJobIdToUrl('from-url')
    expect(window.location.search).toContain('examJob=from-url')
    expect(loadActiveJobId()).toBe('from-url')
  })
})
