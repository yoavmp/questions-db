import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// WP27R -- persisted workflow phase, atomic Continue claim, reliable
// frontend polling. Same mocking pattern as ExamGenerationSection.wp27.test.jsx.
vi.mock('@/lib/examApi.js', () => ({
  API_BASE_URL: 'http://test/api',
  fetchCategories: vi.fn(),
  fetchReadiness: vi.fn(),
  createJob: vi.fn(),
  fetchJob: vi.fn(),
  fetchJobsList: vi.fn(),
  branchJob: vi.fn(),
  previewExclusionFile: vi.fn(),
  retrySlot: vi.fn(),
  updateCostCeiling: vi.fn(),
  replaceFromDb: vi.fn(),
  replaceViaLlm: vi.fn(),
  continueLlm: vi.fn(),
  downloadGeneratedXlsx: vi.fn(),
  downloadFullExamXlsx: vi.fn(),
  downloadExamDocx: vi.fn(),
  saveBlob: vi.fn(),
}))

import * as api from '@/lib/examApi.js'
import ExamGenerationSection from './ExamGenerationSection.jsx'

const CATEGORIES = [
  { name: 'מבוא', question_count: 9 },
  { name: 'גרעיני הבסיס', question_count: 4 },
  { name: 'היסטולוגיה', question_count: 9 },
]

function dbQuestion(n, iid) {
  return {
    number: n,
    question: `שאלת מאגר ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 1,
    origin: 'database', instance_id: iid, id: 100 + n,
    category: 'מבוא', categories: ['מבוא'],
    accuracy: null, distinction: null, accuracy_list: [], distinction_list: [],
  }
}
function llmQuestion(n, iid) {
  return {
    number: n,
    question: `שאלת בינה ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 2,
    origin: 'llm', instance_id: iid, id: null,
    category: 'מבוא', categories: ['מבוא'],
    generation_meta: { attempts: 1, retries_by_slot: 0, cost_usd: '0.34', outcome: 'accepted' },
  }
}

const BLANK_TELEMETRY = {
  by_category: {}, by_slot: {},
  totals: { attempts: 0, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 0, cost_usd: '0', entries: 0, ledger_entries: 0 },
}

function makeView(over = {}) {
  return {
    job_id: 'job-1',
    status: 'queued',
    workflow_phase: 'db_review',
    cost_ceiling_usd: '5.00',
    accumulated_cost_usd: '0',
    cost_basis: 'none',
    remaining_cost_usd: '5.00',
    warnings: [],
    pending_llm_total: 1,
    accepted_count: 1,
    totals: { questions_requested: 2, llm_requested: 1, llm_accepted: 0, llm_failed: 0, retries: 0 },
    categories: {
      מבוא: {
        order_index: 0, total: 2, database: 1, llm: 1,
        accepted: 1, failed: 0, pending: 1,
        slots: [
          { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
          { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'queued', attempts: 0, retries: 0, safe_error: null },
        ],
      },
    },
    questions: [dbQuestion(1, 'iid-db')],
    category_history: {},
    attempt_telemetry: BLANK_TELEMETRY,
    identity: null,
    display_name: 'מבחן בדיקה',
    slug: 'test-exam',
    parent_job_id: null,
    root_job_id: 'job-1',
    excluded_db_ids_count: 0,
    branchable: false,
    ...over,
  }
}

function makeCompletedView(over = {}) {
  return makeView({
    status: 'completed',
    workflow_phase: 'complete',
    pending_llm_total: 0,
    accepted_count: 2,
    accumulated_cost_usd: '0.34',
    remaining_cost_usd: '4.66',
    cost_basis: 'conservative_bound',
    totals: { questions_requested: 2, llm_requested: 1, llm_accepted: 1, llm_failed: 0, retries: 0 },
    categories: {
      מבוא: {
        order_index: 0, total: 2, database: 1, llm: 1, accepted: 2, failed: 0, pending: 0,
        slots: [
          { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
          { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'accepted', attempts: 1, retries: 0, safe_error: null },
        ],
      },
    },
    questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')],
    branchable: true,
    ...over,
  })
}

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.clearAllMocks()
  api.fetchCategories.mockResolvedValue(CATEGORIES)
  api.fetchReadiness.mockResolvedValue({ ready_for_llm: true, warnings: [], blocking_reasons: [] })
  api.fetchJobsList.mockResolvedValue([])
})

describe('WP27R - reliable Continue claim and polling', () => {
  it('applies the returned claimed state immediately, independent of a slow follow-up GET', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValueOnce(makeView())
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('continue-llm-button')

    // the claim response resolves immediately; the follow-up GET is slow
    // (never resolves during this assertion window) -- the UI must still
    // reflect the claimed "running" state right away, not depend on the GET.
    api.continueLlm.mockResolvedValue({
      job_id: 'job-1', status: 'running', workflow_phase: 'llm_generation',
    })
    api.fetchJob.mockReturnValue(new Promise(() => {})) // never resolves
    fireEvent.click(btn)

    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('רץ'))
    expect(screen.queryByTestId('continue-llm-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('db-review-banner')).not.toBeInTheDocument()
  })

  it('cannot double-submit Continue', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeView())
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('continue-llm-button')

    let resolveContinue
    api.continueLlm.mockReturnValue(new Promise((r) => { resolveContinue = r }))
    fireEvent.click(btn)
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(api.continueLlm).toHaveBeenCalledTimes(1)

    api.fetchJob.mockResolvedValue(makeCompletedView())
    resolveContinue({ job_id: 'job-1', status: 'completed', workflow_phase: 'complete' })
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
  })

  it('a concurrent/already-claimed (409) response loads the current job instead of showing a fatal error', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValueOnce(makeView())
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('continue-llm-button')

    const err = Object.assign(new Error('another exam-generation operation is already running'), { status: 409 })
    api.continueLlm.mockRejectedValue(err)
    api.fetchJob.mockResolvedValue(makeView({ status: 'running', workflow_phase: 'llm_generation' }))
    fireEvent.click(btn)

    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('רץ'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a genuine (non-409) Continue failure still shows an error', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValueOnce(makeView())
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('continue-llm-button')

    api.continueLlm.mockRejectedValue(Object.assign(new Error('LLM generation is not ready'), { status: 400 }))
    fireEvent.click(btn)

    expect(await screen.findByRole('alert')).toHaveTextContent('LLM generation is not ready')
  })

  it('refresh/reopen of a running llm_generation job polls', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeView({ status: 'running', workflow_phase: 'llm_generation' }))
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('רץ'))
    await waitFor(() => expect(api.fetchJob.mock.calls.length).toBeGreaterThan(1))
  })

  it('queued + db_review never polls', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeView())
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    const callsAfterMount = api.fetchJob.mock.calls.length
    await new Promise((r) => setTimeout(r, 50))
    expect(api.fetchJob.mock.calls.length).toBe(callsAfterMount) // no polling ticks
  })

  it('partial/interrupted + llm_generation with remaining planned work shows the resume banner, not db_review, and exposes recovery', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeView({
      status: 'interrupted',
      workflow_phase: 'llm_generation',
      pending_llm_total: 1,
      categories: {
        מבוא: {
          order_index: 0, total: 2, database: 1, llm: 1,
          accepted: 1, failed: 0, pending: 1,
          slots: [
            { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
            { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'interrupted', attempts: 1, retries: 0, safe_error: 'backend restarted' },
          ],
        },
      },
    }))
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הופסק'))

    expect(screen.queryByTestId('db-review-banner')).not.toBeInTheDocument()
    expect(screen.getByTestId('resume-banner')).toBeInTheDocument()
    expect(screen.getByTestId('resume-llm-button')).toBeInTheDocument()
    // the individual-slot recovery path (retry) remains available too
    expect(screen.getByRole('button', { name: 'נסה שוב' })).toBeInTheDocument()
    // not polled (paused, not actively running)
    const callsAfterMount = api.fetchJob.mock.calls.length
    await new Promise((r) => setTimeout(r, 50))
    expect(api.fetchJob.mock.calls.length).toBe(callsAfterMount)
  })

  it('resuming from the resume banner calls continue-llm and starts polling', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValueOnce(makeView({
      status: 'partial', workflow_phase: 'llm_generation', pending_llm_total: 1,
    }))
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('resume-llm-button')

    api.continueLlm.mockResolvedValue({ job_id: 'job-1', status: 'running', workflow_phase: 'llm_generation' })
    api.fetchJob.mockResolvedValue(makeView({ status: 'running', workflow_phase: 'llm_generation' }))
    fireEvent.click(btn)

    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('רץ'))
    expect(api.continueLlm).toHaveBeenCalledWith('job-1')
  })

  it('completion stops polling and restores the final-exam controls', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeView({ status: 'running', workflow_phase: 'llm_generation' }))
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('רץ'))

    api.fetchJob.mockResolvedValue(makeCompletedView())
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'), { timeout: 3000 })

    const callsAtCompletion = api.fetchJob.mock.calls.length
    await new Promise((r) => setTimeout(r, 50))
    expect(api.fetchJob.mock.calls.length).toBe(callsAtCompletion) // polling stopped
    expect(screen.getByTestId('branch-button-active')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ייצא מבחן (DOCX)' })).toBeEnabled()
  })
})
