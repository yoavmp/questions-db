import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/examApi.js', () => ({
  API_BASE_URL: 'http://test/api',
  fetchCategories: vi.fn(),
  fetchReadiness: vi.fn(),
  createJob: vi.fn(),
  fetchJob: vi.fn(),
  retrySlot: vi.fn(),
  updateCostCeiling: vi.fn(),
  replaceFromDb: vi.fn(),
  replaceViaLlm: vi.fn(),
  downloadGeneratedXlsx: vi.fn(),
  downloadFullExamXlsx: vi.fn(),
  downloadExamDocx: vi.fn(),
  saveBlob: vi.fn(),
}))

import * as api from '@/lib/examApi.js'
import ExamGenerationSection from './ExamGenerationSection.jsx'

const STATUS_LABEL = {
  queued: 'ממתין',
  running: 'רץ',
  completed: 'הושלם',
  partial: 'הושלם חלקית',
  interrupted: 'הופסק',
  cost_ceiling: 'נעצר בתקרת עלות',
  failed: 'נכשל',
}

// canonical order per backend CATEGORY_ORDER: מבוא(0) < גרעיני הבסיס(6) < היסטולוגיה(7)
const CATEGORIES = [
  { name: 'מבוא', question_count: 9 },
  { name: 'גרעיני הבסיס', question_count: 4 },
  { name: 'היסטולוגיה', question_count: 9 },
]

function dbQuestion(n, iid, analytics = {}) {
  return {
    number: n,
    question: `שאלת מאגר ${n}`,
    answer1: 'א',
    answer2: 'ב',
    answer3: 'ג',
    answer4: 'ד',
    correct_answer: 1,
    origin: 'database',
    instance_id: iid,
    id: 100 + n,
    category: 'מבוא',
    categories: ['מבוא'],
    accuracy: analytics.accuracy ?? null,
    distinction: analytics.distinction ?? null,
    accuracy_list: analytics.accuracy_list ?? [],
    distinction_list: analytics.distinction_list ?? [],
  }
}
function llmQuestion(n, iid) {
  return {
    number: n,
    question: `שאלת בינה ${n}`,
    answer1: 'א',
    answer2: 'ב',
    answer3: 'ג',
    answer4: 'ד',
    correct_answer: 2,
    origin: 'llm',
    instance_id: iid,
    id: null,
    category: 'מבוא',
    categories: ['מבוא'],
    generation_meta: { attempts: 1, retries_by_slot: 0, cost_usd: '0.34', outcome: 'accepted' },
  }
}

function makeView(over = {}) {
  return {
    job_id: 'job-1',
    status: 'completed',
    cost_ceiling_usd: '5.00',
    accumulated_cost_usd: '0.34',
    cost_basis: 'conservative_bound',
    remaining_cost_usd: '4.66',
    warnings: [],
    totals: {
      questions_requested: 2,
      llm_requested: 1,
      llm_accepted: 1,
      llm_failed: 0,
      retries: 0,
    },
    categories: {
      מבוא: {
        order_index: 0,
        total: 2,
        database: 1,
        llm: 1,
        accepted: 2,
        failed: 0,
        pending: 0,
        slots: [
          { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
          { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'accepted', attempts: 1, retries: 0, safe_error: null },
        ],
      },
    },
    questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')],
    category_history: {},
    attempt_telemetry: {
      by_category: {
        מבוא: { attempts: 1, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 1, cost_usd: '0.34', entries: 1 },
      },
      by_slot: {
        's-db': { instance_id: 'iid-db', attempts: 0, retries: 0, replacements: 0, kind: 'database', category: 'מבוא', number: 1, outcomes: [] },
        's-llm': { instance_id: 'iid-llm', attempts: 1, retries: 0, replacements: 0, kind: 'llm', category: 'מבוא', number: 2, outcomes: ['accepted'] },
      },
      totals: { attempts: 1, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 1, cost_usd: '0.34', entries: 1, ledger_entries: 1 },
    },
    ...over,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.clearAllMocks()
  api.fetchCategories.mockResolvedValue(CATEGORIES)
  api.fetchReadiness.mockResolvedValue({ ready_for_llm: true, warnings: [], blocking_reasons: [] })
})

// --------------------------------------------------------------------------- //
// builder: categories, arithmetic, validation, readiness
// --------------------------------------------------------------------------- //
describe('builder', () => {
  it('renders all categories in the canonical order returned by the API, three inputs each', async () => {
    render(<ExamGenerationSection />)
    const totalBoxes = await screen.findAllByLabelText(/^סה"כ שאלות עבור/)
    expect(totalBoxes.map((el) => el.getAttribute('aria-label'))).toEqual([
      'סה"כ שאלות עבור מבוא',
      'סה"כ שאלות עבור גרעיני הבסיס',
      'סה"כ שאלות עבור היסטולוגיה',
    ])
    expect(screen.getAllByLabelText(/שאלות מהמאגר עבור/)).toHaveLength(3)
    expect(screen.getAllByLabelText(/שאלות בבינה מלאכותית עבור/)).toHaveLength(3)
  })

  it('editing C splits into A=ceil, B=floor; editing A/B recomputes C', async () => {
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    const db = screen.getByLabelText('שאלות מהמאגר עבור מבוא')
    const llm = screen.getByLabelText('שאלות בבינה מלאכותית עבור מבוא')

    await user.clear(total)
    await user.type(total, '7')
    expect(db).toHaveValue(4)
    expect(llm).toHaveValue(3)

    await user.clear(db)
    await user.type(db, '2')
    expect(total).toHaveValue(5) // C = A + B = 2 + 3
  })

  it('A over DB availability shows an inline error and blocks start (no silent clamp)', async () => {
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const db = await screen.findByLabelText('שאלות מהמאגר עבור גרעיני הבסיס') // availability 4
    await user.clear(db)
    await user.type(db, '9')
    expect(db).toHaveValue(9) // not clamped to 4
    expect(await screen.findByRole('alert')).toHaveTextContent(/זמינות 4/)
    expect(screen.getByRole('button', { name: 'צור מבחן' })).toBeDisabled()
  })

  it('LLM-not-ready blocks a request with B>0 but a DB-only request stays startable', async () => {
    api.fetchReadiness.mockResolvedValue({
      ready_for_llm: false,
      blocking_reasons: ['OPENAI_API_KEY is not set'],
      warnings: [],
    })
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')

    await user.clear(total)
    await user.type(total, '4') // A=2 B=2  -> LLM requested
    expect(screen.getByTestId('start-blockers')).toHaveTextContent('OPENAI_API_KEY')
    expect(screen.getByRole('button', { name: 'צור מבחן' })).toBeDisabled()

    // make it DB-only
    const db = screen.getByLabelText('שאלות מהמאגר עבור מבוא')
    await user.clear(db)
    await user.type(db, '4') // A=4 B=2 -> still B=2; zero it
    const llm = screen.getByLabelText('שאלות בבינה מלאכותית עבור מבוא')
    await user.clear(llm)
    await user.type(llm, '0')
    expect(screen.getByRole('button', { name: 'צור מבחן' })).toBeEnabled()
  })

  it('stale-pricing warning is shown and does not block', async () => {
    api.fetchReadiness.mockResolvedValue({
      ready_for_llm: true,
      warnings: ['pricing snapshot is 44 days old (threshold 30)'],
      blocking_reasons: [],
    })
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    await user.clear(total)
    await user.type(total, '4')
    expect(screen.getByText(/44 days old/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'צור מבחן' })).toBeEnabled()
  })

  it('editable cost ceiling defaults to $5.00', async () => {
    render(<ExamGenerationSection />)
    expect(await screen.findByLabelText(/תקרת עלות לכל המבחן/)).toHaveValue(5)
  })
})

// --------------------------------------------------------------------------- //
// start protection + persistence + polling
// --------------------------------------------------------------------------- //
describe('start / persistence / polling', () => {
  it('prevents double submission', async () => {
    let resolveCreate
    api.createJob.mockReturnValue(new Promise((r) => { resolveCreate = r }))
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    await user.clear(total)
    await user.type(total, '4')

    const btn = screen.getByRole('button', { name: 'צור מבחן' })
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(btn).toBeDisabled()
    expect(api.createJob).toHaveBeenCalledTimes(1)

    api.fetchJob.mockResolvedValue(makeView())
    resolveCreate({ job_id: 'job-1', status: 'queued' })
    await waitFor(() => expect(screen.getByTestId('job-id')).toHaveTextContent('job-1'))
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
  })

  it('persists the active job id (localStorage + URL) and resumes it on remount', async () => {
    api.createJob.mockResolvedValue({ job_id: 'job-xyz', status: 'queued' })
    api.fetchJob.mockResolvedValue(makeView({ job_id: 'job-xyz' }))
    const user = userEvent.setup()
    const { unmount } = render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    await user.clear(total)
    await user.type(total, '2')
    await user.click(screen.getByRole('button', { name: 'צור מבחן' }))

    await waitFor(() => expect(screen.getByTestId('job-id')).toHaveTextContent('job-xyz'))
    expect(window.localStorage.getItem('examJob.activeId')).toBe('job-xyz')
    expect(window.location.search).toContain('examJob=job-xyz')

    unmount()
    api.fetchJob.mockClear()
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-id')).toHaveTextContent('job-xyz'))
    expect(api.fetchJob).toHaveBeenCalledWith('job-xyz')
  })

  it('polls a running job to completion and shows accepted partials immediately', async () => {
    api.createJob.mockResolvedValue({ job_id: 'job-1', status: 'queued' })
    api.fetchJob
      .mockResolvedValueOnce(
        makeView({
          status: 'running',
          questions: [dbQuestion(1, 'iid-db')], // partial: DB accepted, LLM pending
          categories: {
            מבוא: {
              order_index: 0, total: 2, database: 1, llm: 1,
              accepted: 1, failed: 0, pending: 1,
              slots: [
                { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
                { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'running', attempts: 1, retries: 0, safe_error: null },
              ],
            },
          },
        }),
      )
      .mockResolvedValue(makeView())

    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    await user.clear(total)
    await user.type(total, '2')
    await user.click(screen.getByRole('button', { name: 'צור מבחן' }))

    // partial result visible while still running
    expect(await screen.findByText('1. שאלת מאגר 1')).toBeInTheDocument()
    // then it reaches completed and the LLM question appears
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
    expect(screen.getByText('2. שאלת בינה 2')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// progress: interruption, retry, cap increase
// --------------------------------------------------------------------------- //
describe('progress states', () => {
  async function renderResumed(view) {
    window.localStorage.setItem('examJob.activeId', view.job_id || 'job-1')
    api.fetchJob.mockResolvedValue(view)
    render(<ExamGenerationSection />)
    // wait until the resumed job's real status is applied (not the transient
    // job=null render) so no setState lands outside act afterwards
    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent(STATUS_LABEL[view.status]),
    )
  }

  it('shows an interrupted job clearly and offers retry of eligible slots', async () => {
    const user = userEvent.setup()
    const interrupted = makeView({
      status: 'interrupted',
      questions: [dbQuestion(1, 'iid-db')],
      categories: {
        מבוא: {
          order_index: 0, total: 2, database: 1, llm: 1,
          accepted: 1, failed: 1, pending: 0,
          slots: [
            { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
            { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'interrupted', attempts: 1, retries: 0, safe_error: 'backend restarted' },
          ],
        },
      },
    })
    await renderResumed(interrupted)
    expect(screen.getByTestId('job-status')).toHaveTextContent('הופסק')

    const completed = makeView()
    api.retrySlot.mockResolvedValue(completed)
    await user.click(screen.getByRole('button', { name: 'נסה שוב' }))
    expect(api.retrySlot).toHaveBeenCalledWith('job-1', 's-llm')
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
  })

  it('raises the cost ceiling through the PUT endpoint', async () => {
    const user = userEvent.setup()
    await renderResumed(makeView({ status: 'cost_ceiling' }))
    expect(screen.getByTestId('job-status')).toHaveTextContent('נעצר בתקרת עלות')

    api.updateCostCeiling.mockResolvedValue(makeView({ cost_ceiling_usd: '9.00', remaining_cost_usd: '8.66' }))
    const box = screen.getByLabelText(/העלאת תקרת העלות/)
    await user.type(box, '9')
    await user.click(screen.getByRole('button', { name: 'עדכן תקרה' }))
    expect(api.updateCostCeiling).toHaveBeenCalledWith('job-1', 9)
    await waitFor(() => expect(screen.getByTestId('accumulated-cost')).toHaveTextContent('$9.00'))
  })

  it('renders per-category and per-slot progress', async () => {
    await renderResumed(makeView({ status: 'partial' }))
    expect(screen.getByText(/ביקשו 2 \(מאגר 1 \/ בינה 1\)/)).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// results: replacements, transitions, rollback, locking, telemetry, exports
// --------------------------------------------------------------------------- //
describe('results and replacements', () => {
  async function renderResumed(view = makeView()) {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(view)
    render(<ExamGenerationSection />)
    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent(STATUS_LABEL[view.status]),
    )
    if ((view.questions || []).length) {
      await screen.findByText(`${view.questions[0].number}. ${view.questions[0].question}`)
    }
  }

  it('shows both replacement controls on every accepted question regardless of origin', async () => {
    await renderResumed()
    const cards = screen.getAllByText(/^\d+\. שאלת/).map((el) => el.closest('div.p-4'))
    for (const card of cards) {
      const q = within(card)
      expect(q.getByRole('button', { name: 'החלף בשאלה מהמאגר' })).toBeInTheDocument()
      expect(q.getByRole('button', { name: 'צור שאלה אחרת' })).toBeInTheDocument()
    }
    // per-question origin badges (the only composition indicator)
    expect(screen.getByText('מתוך המאגר')).toBeInTheDocument()
    expect(screen.getByText('נוצר בבינה מלאכותית')).toBeInTheDocument()
  })

  it('LLM->DB via "החלף בשאלה מהמאגר": calls replace-db and the badge flips to DB', async () => {
    const user = userEvent.setup()
    await renderResumed()
    const flipped = makeView({
      questions: [dbQuestion(1, 'iid-db'), { ...dbQuestion(2, 'iid-llm'), question: 'שאלת מאגר חדשה 2' }],
    })
    api.replaceFromDb.mockResolvedValue(flipped)

    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByRole('button', { name: 'החלף בשאלה מהמאגר' }))
    expect(api.replaceFromDb).toHaveBeenCalledWith('job-1', 'iid-llm')
    await screen.findByText('2. שאלת מאגר חדשה 2')
    expect(screen.getAllByText('מתוך המאגר')).toHaveLength(2)
    expect(screen.queryByText('נוצר בבינה מלאכותית')).not.toBeInTheDocument()
  })

  it('DB->LLM via "צור שאלה אחרת": calls replace-llm and the badge flips to LLM', async () => {
    const user = userEvent.setup()
    await renderResumed()
    const flipped = makeView({
      questions: [{ ...llmQuestion(1, 'iid-db'), question: 'שאלת בינה חדשה 1' }, llmQuestion(2, 'iid-llm')],
    })
    api.replaceViaLlm.mockResolvedValue(flipped)

    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    await user.click(within(dbCard).getByRole('button', { name: 'צור שאלה אחרת' }))
    expect(api.replaceViaLlm).toHaveBeenCalledWith('job-1', 'iid-db')
    await screen.findByText('1. שאלת בינה חדשה 1')
    expect(screen.getAllByText('נוצר בבינה מלאכותית')).toHaveLength(2)
  })

  it('DB->DB and LLM->LLM keep the origin but refresh the text from the server', async () => {
    const user = userEvent.setup()
    await renderResumed()
    api.replaceFromDb.mockResolvedValue(
      makeView({ questions: [{ ...dbQuestion(1, 'iid-db'), question: 'מאגר אחר 1' }, llmQuestion(2, 'iid-llm')] }),
    )
    api.replaceViaLlm.mockResolvedValue(
      makeView({ questions: [{ ...dbQuestion(1, 'iid-db'), question: 'מאגר אחר 1' }, { ...llmQuestion(2, 'iid-llm'), question: 'בינה אחרת 2' }] }),
    )
    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    await user.click(within(dbCard).getByRole('button', { name: 'החלף בשאלה מהמאגר' }))
    await screen.findByText('1. מאגר אחר 1')
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByRole('button', { name: 'צור שאלה אחרת' }))
    await screen.findByText('2. בינה אחרת 2')
    expect(screen.getByText('מתוך המאגר')).toBeInTheDocument()
    expect(screen.getByText('נוצר בבינה מלאכותית')).toBeInTheDocument()
  })

  it('on replacement failure the current question stays visible and unchanged, with an error', async () => {
    const user = userEvent.setup()
    await renderResumed()
    api.replaceViaLlm.mockRejectedValue(Object.assign(new Error('לא הופקה שאלה מאושרת; המקורית נשמרה'), { status: 200 }))

    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByRole('button', { name: 'צור שאלה אחרת' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('נשמרה')
    // unchanged
    expect(screen.getByText('2. שאלת בינה 2')).toBeInTheDocument()
    expect(screen.getByText('נוצר בבינה מלאכותית')).toBeInTheDocument()
  })

  it('locks every replacement control while one mutation is in flight', async () => {
    const user = userEvent.setup()
    await renderResumed()
    let resolveIt
    api.replaceFromDb.mockReturnValue(new Promise((r) => { resolveIt = r }))

    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    await user.click(within(dbCard).getByRole('button', { name: 'החלף בשאלה מהמאגר' }))

    for (const b of screen.getAllByRole('button', { name: /החלף בשאלה מהמאגר|צור שאלה אחרת/ })) {
      expect(b).toBeDisabled()
    }
    resolveIt(makeView())
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'החלף בשאלה מהמאגר' })[0]).toBeEnabled(),
    )
  })

  it('never shows a recomputed current DB-vs-LLM aggregate; quotas stay request provenance', async () => {
    const user = userEvent.setup()
    await renderResumed()
    const quotaLine = screen.getByText(/ביקשו 2 \(מאגר 1 \/ בינה 1\)/)

    // flip the LLM question to DB; server keeps the request quotas identical
    api.replaceFromDb.mockResolvedValue(
      makeView({ questions: [dbQuestion(1, 'iid-db'), { ...dbQuestion(2, 'iid-llm') }] }),
    )
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByRole('button', { name: 'החלף בשאלה מהמאגר' }))
    await waitFor(() => expect(screen.getAllByText('מתוך המאגר')).toHaveLength(2))

    // the only per-composition signal is the badges; the quota line is unchanged
    expect(quotaLine).toHaveTextContent('ביקשו 2 (מאגר 1 / בינה 1)')
    expect(screen.queryByText(/כרגע.*מהמאגר/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('current-composition')).not.toBeInTheDocument()
  })

  it('never renders internal semantic history (category_history) on the exam screen', async () => {
    await renderResumed(
      makeView({
        category_history: {
          מבוא: [
            {
              number: 2,
              question: 'שאלת בינה שהוחלפה — היסטוריה סמנטית פנימית',
              answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד',
              correct_answer: 2,
            },
          ],
        },
      }),
    )
    // the screen shows the current questions but not the internal uniqueness state
    expect(screen.getByText('1. שאלת מאגר 1')).toBeInTheDocument()
    expect(screen.queryByText('שאלות בינה שהוחלפו')).not.toBeInTheDocument()
    expect(
      screen.queryByText(/היסטוריה סמנטית פנימית/),
    ).not.toBeInTheDocument()
  })

  it('renders ledger-derived attempt telemetry and cost warnings', async () => {
    await renderResumed(
      makeView({
        warnings: [{ code: 'pricing_stale', message: 'מחירון ישן; האומדן עדיין חסם בטוח' }],
        attempt_telemetry: {
          by_category: {
            מבוא: { attempts: 4, charged_failed_attempts: 2, retries: 1, replacements: 1, accepted: 1, cost_usd: '1.02', entries: 4 },
          },
          by_slot: {},
          totals: { attempts: 4, charged_failed_attempts: 2, retries: 1, replacements: 1, accepted: 1, cost_usd: '1.02', entries: 4, ledger_entries: 4 },
        },
      }),
    )
    const tel = screen.getByTestId('telemetry')
    expect(tel).toHaveTextContent('סה"כ ניסיונות: 4')
    expect(tel).toHaveTextContent('נכשלו וחויבו: 2')
    expect(tel).toHaveTextContent('ניסיונות חוזרים: 1')
    expect(screen.getByText(/מחירון ישן/)).toBeInTheDocument()
  })

  it('downloads the LLM-only Excel through the job export endpoint', async () => {
    const user = userEvent.setup()
    await renderResumed()
    api.downloadGeneratedXlsx.mockResolvedValue(new Blob(['x']))
    await user.click(screen.getByRole('button', { name: 'ייצוא שאלות בינה בלבד (Excel)' }))
    expect(api.downloadGeneratedXlsx).toHaveBeenCalledWith('job-1')
    await waitFor(() => expect(api.saveBlob).toHaveBeenCalled())
  })

  it('downloads the full-exam Excel through its own distinct endpoint (§5)', async () => {
    const user = userEvent.setup()
    await renderResumed()
    api.downloadFullExamXlsx.mockResolvedValue(new Blob(['x']))
    await user.click(screen.getByRole('button', { name: 'ייצוא מבחן מלא (Excel)' }))
    expect(api.downloadFullExamXlsx).toHaveBeenCalledWith('job-1')
    expect(api.downloadGeneratedXlsx).not.toHaveBeenCalled()
    await waitFor(() => expect(api.saveBlob).toHaveBeenCalled())
  })

  it('exports the current question set through the existing DOCX path', async () => {
    const user = userEvent.setup()
    await renderResumed()
    api.downloadExamDocx.mockResolvedValue(new Blob(['x']))
    await user.click(screen.getByRole('button', { name: 'ייצא מבחן (DOCX)' }))
    const [questionsArg, includeAnswers] = api.downloadExamDocx.mock.calls[0]
    expect(includeAnswers).toBe(false)
    expect(questionsArg.map((q) => q.number)).toEqual([1, 2]) // canonical order
    await waitFor(() => expect(api.saveBlob).toHaveBeenCalled())
  })
})

// --------------------------------------------------------------------------- //
// WP21: restored grouped presentation, per-question/overall analytics, and
// ledger-derived (not mutable-slot-derived) attempt/retry counts.
// --------------------------------------------------------------------------- //
describe('WP21 - category headings, analytics, ledger-derived counts', () => {
  async function renderResumed(view) {
    window.localStorage.setItem('examJob.activeId', view.job_id || 'job-1')
    api.fetchJob.mockResolvedValue(view)
    render(<ExamGenerationSection />)
    await waitFor(() =>
      expect(screen.getByTestId('job-status')).toHaveTextContent(STATUS_LABEL[view.status]),
    )
    if ((view.questions || []).length) {
      await screen.findByText(`${view.questions[0].number}. ${view.questions[0].question}`)
    }
  }

  it('renders one heading per category, in canonical order, never repeated within a group (§2)', async () => {
    const view = makeView({
      categories: {
        מבוא: {
          order_index: 0, total: 2, database: 1, llm: 1, accepted: 2, failed: 0, pending: 0,
          slots: [
            { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
            { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'accepted', attempts: 1, retries: 0, safe_error: null },
          ],
        },
        'גרעיני הבסיס': {
          order_index: 6, total: 2, database: 2, llm: 0, accepted: 2, failed: 0, pending: 0,
          slots: [
            { slot_id: 's-db2', instance_id: 'iid-db2', kind: 'database', number: 3, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
            { slot_id: 's-db3', instance_id: 'iid-db3', kind: 'database', number: 4, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
          ],
        },
      },
      questions: [
        dbQuestion(1, 'iid-db'),
        llmQuestion(2, 'iid-llm'),
        { ...dbQuestion(3, 'iid-db2'), category: 'גרעיני הבסיס', categories: ['גרעיני הבסיס'] },
        { ...dbQuestion(4, 'iid-db3'), category: 'גרעיני הבסיס', categories: ['גרעיני הבסיס'] },
      ],
    })
    await renderResumed(view)
    const headings = screen.getAllByRole('heading', { level: 5 })
    expect(headings.map((h) => h.textContent)).toEqual(['מבוא', 'גרעיני הבסיס']) // once each, canonical order
  })

  it('shows every historical value when a DB question has several, and N/A when a question has none (§3)', async () => {
    const view = makeView({
      questions: [
        dbQuestion(1, 'iid-db', { accuracy: 85, distinction: 0.4, accuracy_list: [80, 90], distinction_list: [0.4] }),
        llmQuestion(2, 'iid-llm'),
      ],
    })
    await renderResumed(view)
    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    expect(within(dbCard).getByText(/דיוק:\s*80%, 90%/)).toBeInTheDocument()
    expect(within(dbCard).getByText(/הבחנה:\s*0\.4/)).toBeInTheDocument()
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    expect(within(llmCard).getByText(/דיוק:\s*N\/A/)).toBeInTheDocument()
    expect(within(llmCard).getByText(/הבחנה:\s*N\/A/)).toBeInTheDocument()
  })

  it('computes overall mean accuracy and the distinction-threshold count/proportion, default threshold 0.3 (§4)', async () => {
    const view = makeView({
      questions: [
        dbQuestion(1, 'iid-db', { accuracy: 80, distinction: 0.5, accuracy_list: [80], distinction_list: [0.5] }),
        llmQuestion(2, 'iid-llm'), // missing -- excluded, not zero
      ],
    })
    await renderResumed(view)
    const stats = screen.getByTestId('overall-analytics')
    expect(stats).toHaveTextContent('דיוק ממוצע: 80.0%')
    expect(stats).toHaveTextContent('שאלות עם הבחנה גבוהה מ-0.3: 1 מתוך 1')
  })

  it('recomputes the distinction count when the threshold slider moves', async () => {
    const view = makeView({
      questions: [
        dbQuestion(1, 'iid-db', { distinction: 0.5, distinction_list: [0.5] }),
        { ...dbQuestion(2, 'iid-db2'), distinction: 0.2, distinction_list: [0.2] },
      ],
    })
    await renderResumed(view)
    const stats = screen.getByTestId('overall-analytics')
    expect(stats).toHaveTextContent('שאלות עם הבחנה גבוהה מ-0.3: 1 מתוך 2')
    fireEvent.change(screen.getByLabelText('סף הבחנה:'), { target: { value: '0.1' } })
    expect(stats).toHaveTextContent('שאלות עם הבחנה גבוהה מ-0.1: 2 מתוך 2')
  })

  it('shows N/A and 0 מתוך 0 when every question is missing analytics -- never 0% or a divide-by-zero (§4)', async () => {
    const view = makeView({
      questions: [llmQuestion(1, 'iid-llm'), { ...llmQuestion(2, 'iid-llm2'), instance_id: 'iid-llm2' }],
    })
    await renderResumed(view)
    const stats = screen.getByTestId('overall-analytics')
    expect(stats).toHaveTextContent('דיוק ממוצע: N/A')
    expect(stats).toHaveTextContent('0 מתוך 0')
  })

  it('per-slot progress chips use ledger-derived ניסיונות/חזרות labels, not נ=/ח= abbreviations', async () => {
    await renderResumed(makeView({ status: 'partial' }))
    const progressCard = screen.getByText('התקדמות לפי נושא').closest('div.rounded-lg')
    expect(within(progressCard).getByText(/ניסיונות: 1/)).toBeInTheDocument()
    expect(screen.queryByText(/נ=/)).not.toBeInTheDocument()
    expect(screen.queryByText(/ח=/)).not.toBeInTheDocument()
  })

  it('keeps a failed paid replace_llm visible via ledger-derived counts even though the mutable slot/generation_meta counters rolled back (§6)', async () => {
    const view = makeView({
      questions: [
        dbQuestion(1, 'iid-db'),
        // generation_meta reflects only the original accepted attempt -- as it
        // is after WP18R's failure rollback restores attempts/retries
        { ...llmQuestion(2, 'iid-llm'), generation_meta: { attempts: 1, retries_by_slot: 0, cost_usd: '0.05', outcome: 'accepted' } },
      ],
      attempt_telemetry: {
        by_category: {
          מבוא: { attempts: 2, failed_attempts: 1, charged_failed_attempts: 1, retries: 0, replacements: 1, accepted: 1, cost_usd: '0.09', entries: 2 },
        },
        by_slot: {
          's-db': { instance_id: 'iid-db', attempts: 0, retries: 0, replacements: 0, kind: 'database', category: 'מבוא', number: 1, outcomes: [] },
          's-llm': { instance_id: 'iid-llm', attempts: 2, retries: 0, replacements: 1, kind: 'llm', category: 'מבוא', number: 2, outcomes: ['accepted', 'question_rejected'] },
        },
        totals: { attempts: 2, failed_attempts: 1, charged_failed_attempts: 1, retries: 0, replacements: 1, accepted: 1, cost_usd: '0.09', entries: 2, ledger_entries: 2 },
      },
    })
    await renderResumed(view)
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    expect(within(llmCard).getByText(/ניסיונות: 2/)).toBeInTheDocument()
    expect(within(llmCard).getByText(/חזרות: 1/)).toBeInTheDocument()
  })

  it('never shows category_history and never a current DB/LLM aggregate alongside the new sections', async () => {
    await renderResumed(
      makeView({
        category_history: { מבוא: [{ number: 2, question: 'היסטוריה סמנטית פנימית', answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 1 }] },
      }),
    )
    expect(screen.queryByText(/היסטוריה סמנטית פנימית/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('current-composition')).not.toBeInTheDocument()
    expect(screen.queryByText(/כרגע.*מהמאגר/)).not.toBeInTheDocument()
  })
})
