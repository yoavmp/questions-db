// Pure, framework-free helpers for the exam-generation job screen (WP19).
//
// Everything here is deterministic and side-effect free except the small
// localStorage / URL helpers at the bottom, which are what let an active job
// survive a refresh or reopen. Kept separate from the React component so the
// C/A/B arithmetic, validation, ordering and DOCX-metadata stripping can be
// unit tested without a DOM.

export const DEFAULT_COST_CEILING_USD = '5.00'

export const SEVEN_PUBLIC_FIELDS = [
  'number',
  'question',
  'answer1',
  'answer2',
  'answer3',
  'answer4',
  'correct_answer',
]

// --- integer parsing -------------------------------------------------------

// An empty box means 0. Anything that is not a whole, non-negative number is
// invalid (never silently clamped).
export function parseCount(raw) {
  if (raw === '' || raw === null || raw === undefined) {
    return { value: 0, valid: true, empty: true }
  }
  const s = String(raw).trim()
  if (!/^\d+$/.test(s)) {
    return { value: null, valid: false, empty: false }
  }
  return { value: parseInt(s, 10), valid: true, empty: false }
}

// --- C / A / B coupling --------------------------------------------------

// Editing C: A = ceil(C/2) from DB, B = floor(C/2) from LLM.
export function deriveFromTotal(total) {
  const c = Math.max(0, Math.trunc(total))
  return { total: c, database: Math.ceil(c / 2), llm: Math.floor(c / 2) }
}

// Editing A or B: C = A + B.
export function deriveFromParts(database, llm) {
  const a = Math.max(0, Math.trunc(database))
  const b = Math.max(0, Math.trunc(llm))
  return { total: a + b, database: a, llm: b }
}

// A category row is three raw strings. Applying an edit keeps the coupling
// above whenever the edited value(s) parse; an invalid entry is stored as-is
// so the box can show what the user typed and the error can be rendered.
export function applyRowEdit(row, field, rawValue) {
  const next = { ...row, [field]: rawValue }
  if (field === 'total') {
    const t = parseCount(rawValue)
    if (t.valid) {
      const d = deriveFromTotal(t.value)
      next.database = String(d.database)
      next.llm = String(d.llm)
    }
    return next
  }
  // field === 'database' | 'llm'
  const a = parseCount(field === 'database' ? rawValue : row.database)
  const b = parseCount(field === 'llm' ? rawValue : row.llm)
  if (a.valid && b.valid) {
    next.total = String(a.value + b.value)
  }
  return next
}

export function emptyRow() {
  return { total: '0', database: '0', llm: '0' }
}

export function rowNumbers(row) {
  const total = parseCount(row.total)
  const database = parseCount(row.database)
  const llm = parseCount(row.llm)
  return {
    total,
    database,
    llm,
    valid: total.valid && database.valid && llm.valid,
  }
}

// --- validation / readiness -------------------------------------------

// availability: integer count of DB questions available for this category.
export function validateRow(row, availability) {
  const n = rowNumbers(row)
  const errors = {}
  if (!n.total.valid) errors.total = 'מספר שלם אי-שלילי בלבד'
  if (!n.database.valid) errors.database = 'מספר שלם אי-שלילי בלבד'
  if (!n.llm.valid) errors.llm = 'מספר שלם אי-שלילי בלבד'
  if (n.valid && n.database.value + n.llm.value !== n.total.value) {
    errors.sum = 'סכום מאגר + בינה מלאכותית חייב להיות שווה לסה"כ'
  }
  if (
    n.valid &&
    typeof availability === 'number' &&
    n.database.value > availability
  ) {
    errors.availability = `נדרשו ${n.database.value} שאלות מהמאגר, זמינות ${availability}`
  }
  return { errors, ok: Object.keys(errors).length === 0 }
}

export function totalLlmRequested(rows) {
  return Object.values(rows).reduce((sum, row) => {
    const n = rowNumbers(row)
    return sum + (n.llm.valid ? n.llm.value : 0)
  }, 0)
}

export function totalQuestionsRequested(rows) {
  return Object.values(rows).reduce((sum, row) => {
    const n = rowNumbers(row)
    return sum + (n.total.valid ? n.total.value : 0)
  }, 0)
}

// Missing / mismatched / incomplete pricing (readiness.ready_for_llm === false)
// blocks ONLY when some B > 0. DB-only generation stays usable.
export function llmBlockedReasons(rows, readiness) {
  if (totalLlmRequested(rows) <= 0) return []
  if (!readiness) return []
  if (readiness.ready_for_llm) return []
  const reasons = readiness.blocking_reasons || []
  return reasons.length ? reasons : ['יצירת שאלות בבינה מלאכותית אינה מוכנה']
}

// Stale pricing warns, never blocks.
export function pricingWarnings(readiness) {
  if (!readiness) return []
  return readiness.warnings || []
}

export function parseCeiling(raw) {
  const s = String(raw).trim().replace(/^\$/, '')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return { value: null, valid: false }
  const v = Number(s)
  if (!(v > 0)) return { value: null, valid: false }
  return { value: v, valid: true }
}

// Whole-screen readiness to start. Returns every reason it is blocked so the
// UI can list them; an empty array means "ready".
export function startBlockers({ rows, availabilityByName, ceilingRaw, readiness }) {
  const blockers = []
  if (totalQuestionsRequested(rows) <= 0) {
    blockers.push('יש לבקש לפחות שאלה אחת')
  }
  for (const [name, row] of Object.entries(rows)) {
    const n = rowNumbers(row)
    if (n.total.valid && n.total.value === 0) continue
    const { errors } = validateRow(row, availabilityByName?.[name])
    for (const key of Object.keys(errors)) {
      blockers.push(`${name}: ${errors[key]}`)
    }
  }
  if (!parseCeiling(ceilingRaw).valid) {
    blockers.push('תקרת עלות חייבת להיות מספר חיובי')
  }
  blockers.push(...llmBlockedReasons(rows, readiness))
  return blockers
}

// --- request payload (canonical order preserved) --------------------

// `categories` is the array from GET /api/test/categories, already in canonical
// order. Only rows whose total > 0 are sent.
export function buildCreatePayload(rows, categories, ceilingRaw) {
  const out = {}
  for (const cat of categories) {
    const row = rows[cat.name]
    if (!row) continue
    const n = rowNumbers(row)
    if (!n.valid || n.total.value <= 0) continue
    out[cat.name] = {
      total: n.total.value,
      database: n.database.value,
      llm: n.llm.value,
    }
  }
  const ceiling = parseCeiling(ceilingRaw)
  return {
    categories: out,
    cost_ceiling_usd: ceiling.valid ? ceiling.value.toFixed(2) : DEFAULT_COST_CEILING_USD,
  }
}

// --- results ordering + DOCX metadata stripping --------------------

export function orderQuestions(questions) {
  return [...(questions || [])].sort((a, b) => (a.number ?? 0) - (b.number ?? 0))
}

// The existing DOCX path only ever reads the seven public fields. Everything
// job-only (instance_id, origin, generation_meta, id, categories, performance
// lists, ...) is dropped before the questions are handed to /api/test/export-docx.
// Answer order is left exactly as given so the DOCX endpoint's own daily-seed
// randomisation is preserved.
export function stripJobMetadata(questions) {
  return orderQuestions(questions).map((q) => {
    const out = {}
    for (const f of SEVEN_PUBLIC_FIELDS) out[f] = q[f]
    return out
  })
}

// --- category grouping (WP21 §2) -------------------------------------

// `questions` must already be in canonical/global-number order (orderQuestions
// output). Groups consecutive same-category runs so a heading renders once
// per group and is never repeated within it -- global numbering is always
// contiguous per category (WP17 category_order + number_base), so a
// consecutive-run grouping is equivalent to (and simpler than) the legacy
// screen's object-key grouping.
export function groupByCategory(questions) {
  const groups = []
  for (const q of questions || []) {
    const last = groups[groups.length - 1]
    if (last && last.category === q.category) {
      last.questions.push(q)
    } else {
      groups.push({ category: q.category, questions: [q] })
    }
  }
  return groups
}

// --- per-question analytics display (WP21 §3, recovered legacy contract) --

// Exact legacy convention (pre-WP19 QuestionCard): every raw historical value
// when there is more than one recorded exam use it appeared in; the single
// per-question average as a fallback; 'N/A' (never the bare word "NaN", never
// a fabricated 0) when there is no data at all. `percent` adds the historical
// '%' suffix used for accuracy but not distinction.
export function formatMeasure(list, avg, { percent = false } = {}) {
  const fmt = (v) => (percent ? `${v}%` : `${v}`)
  if (Array.isArray(list) && list.length > 0) return list.map(fmt).join(', ')
  if (avg != null) return fmt(avg)
  return 'N/A'
}

// --- overall exam analytics (WP21 §4, recovered legacy contract) ----------

export const DEFAULT_DISTINCTION_THRESHOLD = 0.3

// Legacy formula verbatim (git show 4cd86d1:frontend/src/App.jsx, the deleted
// TestGenerationSection): mean of each question's OWN average accuracy
// (ignoring questions with no accuracy at all); count/total of questions
// whose OWN average distinction is STRICTLY greater than `threshold`, among
// only the questions that have a distinction value at all. All-missing is
// `null` (rendered 'N/A' at presentation) -- never 0, never a divide-by-zero.
export function overallAnalytics(questions, threshold) {
  const accuracyValues = (questions || [])
    .map((q) => parseFloat(q.accuracy))
    .filter((acc) => !Number.isNaN(acc) && acc != null)
  const avgAccuracy =
    accuracyValues.length > 0
      ? accuracyValues.reduce((sum, acc) => sum + acc, 0) / accuracyValues.length
      : null
  const validDistinction = (questions || [])
    .map((q) => parseFloat(q.distinction))
    .filter((d) => !Number.isNaN(d) && d != null)
  const highDistinctionCount = validDistinction.filter((d) => d > threshold).length
  return {
    avgAccuracy,
    highDistinctionCount,
    totalValidDistinction: validDistinction.length,
  }
}

// --- ledger-derived attempt/retry/replacement counts (WP21 §6, WP21R §2) --

// Question-card counts must come from the immutable cost_ledger (via
// attempt_telemetry.by_slot), not the mutable slot.attempts/slot.retries --
// a failed paid replace_llm rolls the SLOT back to its pre-attempt state
// (WP18R), so those mutable counters silently lose it; the ledger never does.
//
// WP21R owner decision: `retries` (failure retries) and `replacements`
// (intentional replace_llm calls) are kept SEPARATE, never folded into one
// "חזרות" figure -- an intentional replacement must never inflate the
// displayed failure-retry count. `failedAttempts` is exposed too so a
// nonzero failure count stays visible even after a rollback restores the
// slot's own mutable counters.
const _BLANK_COUNTS = { attempts: 0, retries: 0, replacements: 0, failedAttempts: 0 }

function _counts(b) {
  if (!b) return { ..._BLANK_COUNTS }
  return {
    attempts: b.attempts || 0,
    retries: b.retries || 0,
    replacements: b.replacements || 0,
    failedAttempts: b.failed_attempts || 0,
  }
}

export function slotAttemptCounts(telemetry, slotId) {
  return _counts(telemetry?.by_slot?.[slotId])
}

// A result question DTO only carries `instance_id` (stable across
// replacements), not the internal `slot_id` the ledger is keyed by -- look it
// up by matching `by_slot[*].instance_id` (also stable) instead.
export function slotAttemptCountsByInstance(telemetry, instanceId) {
  const bySlot = telemetry?.by_slot || {}
  for (const b of Object.values(bySlot)) {
    if (b.instance_id === instanceId) return _counts(b)
  }
  return { ..._BLANK_COUNTS }
}

export function isTerminalStatus(status) {
  return ['completed', 'partial', 'interrupted', 'cost_ceiling', 'failed'].includes(status)
}

export function isPollingStatus(status) {
  return status === 'queued' || status === 'running'
}

// LLM slots that can be retried.
export function retryableSlots(view) {
  const out = []
  const cats = view?.categories || {}
  for (const [name, cat] of Object.entries(cats)) {
    for (const slot of cat.slots || []) {
      if (
        slot.kind === 'llm' &&
        ['failed', 'interrupted', 'cost_ceiling'].includes(slot.status)
      ) {
        out.push({ ...slot, category: name })
      }
    }
  }
  return out
}

export function formatUSD(x) {
  const n = Number(x)
  if (Number.isNaN(n)) return String(x)
  return `$${n.toFixed(2)}`
}

// --- active-job persistence (survives refresh / reopen) -----------

const LS_KEY = 'examJob.activeId'
const URL_PARAM = 'examJob'

export function saveActiveJobId(id) {
  try {
    if (id) window.localStorage.setItem(LS_KEY, id)
    else window.localStorage.removeItem(LS_KEY)
  } catch {
    /* private mode / storage disabled */
  }
}

export function loadActiveJobId() {
  let fromUrl = null
  try {
    fromUrl = new URLSearchParams(window.location.search).get(URL_PARAM)
  } catch {
    fromUrl = null
  }
  if (fromUrl) return fromUrl
  try {
    return window.localStorage.getItem(LS_KEY)
  } catch {
    return null
  }
}

export function syncJobIdToUrl(id) {
  try {
    const url = new URL(window.location.href)
    if (id) url.searchParams.set(URL_PARAM, id)
    else url.searchParams.delete(URL_PARAM)
    window.history.replaceState(window.history.state, '', url)
  } catch {
    /* no History API (very old browsers / SSR) */
  }
}
