import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// WP27 -- staged DB review before LLM generation. Covers every item in
// WP27's "Frontend tests" list. Same mocking pattern as
// ExamGenerationSection.test.jsx (kept as its own file per this codebase's
// existing per-WP convention, e.g. examGen.wp26.test.js).
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

// A=1/B=1 job awaiting DB-review approval: 1 accepted DB question, 1 still-
// queued planned LLM slot.
function makeDbReviewView(over = {}) {
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

// the same job once Continue has completed the planned B=1 batch.
function makeCompletedView(over = {}) {
  return makeDbReviewView({
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

describe('WP27 - staged DB review screen', () => {
  it('mixed creation opens the DB-review screen, not an automatic LLM progress run', async () => {
    api.createJob.mockResolvedValue({ job_id: 'job-1', status: 'queued', workflow_phase: 'db_review' })
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    const total = await screen.findByLabelText('סה"כ שאלות עבור מבוא')
    await user.clear(total)
    await user.type(total, '2')
    await user.click(screen.getByRole('button', { name: 'צור מבחן' }))

    expect(await screen.findByTestId('db-review-banner')).toBeInTheDocument()
    expect(screen.getByTestId('job-status')).toHaveTextContent('ממתין')
    expect(screen.getByText('1. שאלת מאגר 1')).toBeInTheDocument()
    expect(screen.queryByText('2. שאלת בינה 2')).not.toBeInTheDocument()
    // no polling loop was started for a db_review (non-"running") job
    expect(api.fetchJob).toHaveBeenCalledTimes(1)
  })

  it('shows the exact required waiting label and the planned LLM count', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView({ pending_llm_total: 3 }))
    render(<ExamGenerationSection />)
    const banner = await screen.findByTestId('db-review-banner')
    expect(banner).toHaveTextContent('ממתין לאישור שאלות המאגר')
    expect(banner).toHaveTextContent('3')
  })

  it('renders canonical category headings and only the currently accepted DB cards', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    expect(screen.getByRole('heading', { level: 5, name: 'מבוא' })).toBeInTheDocument()
    expect(screen.getByText('1. שאלת מאגר 1')).toBeInTheDocument()
  })

  it('renders no placeholder row for the still-pending planned LLM slot', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    expect(screen.getAllByText(/^\d+\. שאלת/)).toHaveLength(1)
  })

  it('keeps both replacement controls usable on every accepted question during db_review', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    const card = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    expect(within(card).getByRole('button', { name: 'החלף בשאלה מהמאגר' })).toBeEnabled()
    expect(within(card).getByRole('button', { name: 'צור שאלה אחרת' })).toBeEnabled()
  })

  it('cost display updates after a manual LLM replacement, and db_review is not exited by it', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    expect(screen.getByTestId('accumulated-cost')).toHaveTextContent('$0.00')

    api.replaceViaLlm.mockResolvedValue(makeDbReviewView({
      questions: [{ ...llmQuestion(1, 'iid-db') }],
      accumulated_cost_usd: '0.34', remaining_cost_usd: '4.66', cost_basis: 'conservative_bound',
    }))
    const card = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    await user.click(within(card).getByRole('button', { name: 'צור שאלה אחרת' }))
    await waitFor(() => expect(screen.getByTestId('accumulated-cost')).toHaveTextContent('$0.34'))
    // an intentional replacement never changes the workflow phase
    expect(screen.getByTestId('db-review-banner')).toBeInTheDocument()
  })

  it('Continue is present during db_review, protected from double submission, and disappears once complete', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    render(<ExamGenerationSection />)
    const btn = await screen.findByTestId('continue-llm-button')
    expect(btn).toHaveTextContent('המשך ליצירת שאלות חדשות באמצעות בינה מלאכותית')

    let resolveContinue
    api.continueLlm.mockReturnValue(new Promise((r) => { resolveContinue = r }))
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(btn).toBeDisabled()
    expect(api.continueLlm).toHaveBeenCalledTimes(1)

    api.fetchJob.mockResolvedValue(makeCompletedView())
    resolveContinue({ job_id: 'job-1', status: 'completed', workflow_phase: 'complete' })
    await waitFor(() => expect(screen.queryByTestId('continue-llm-button')).not.toBeInTheDocument())
    expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם')
    expect(screen.getByText('2. שאלת בינה 2')).toBeInTheDocument()
  })

  it('renders the intentional empty A=0/B>0 db-review state, not an error, with Continue still offered', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView({ questions: [], accepted_count: 0, pending_llm_total: 2 }))
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    expect(screen.getByTestId('empty-questions-message')).toHaveTextContent('לא נבחרו שאלות מהמאגר')
    expect(screen.getByTestId('continue-llm-button')).toBeInTheDocument()
  })

  it('B=0 shows the job as completed immediately and never offers Continue', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeCompletedView({
      questions: [dbQuestion(1, 'iid-db'), { ...dbQuestion(2, 'iid-db2') }],
      pending_llm_total: 0,
    }))
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
    expect(screen.queryByTestId('continue-llm-button')).not.toBeInTheDocument()
    expect(screen.queryByTestId('db-review-banner')).not.toBeInTheDocument()
  })

  it('refresh/reopen restores the same db_review state', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    const { unmount } = render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    unmount()
    render(<ExamGenerationSection />)
    expect(await screen.findByTestId('db-review-banner')).toBeInTheDocument()
    expect(screen.getByText('1. שאלת מאגר 1')).toBeInTheDocument()
  })

  it('disables branching during db_review and explains when it becomes available', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeDbReviewView())
    render(<ExamGenerationSection />)
    await screen.findByTestId('db-review-banner')
    expect(screen.queryByTestId('branch-button-active')).not.toBeInTheDocument()
    expect(screen.getByTestId('branch-disabled-note')).toBeInTheDocument()
  })

  it('completion restores the established full-exam controls (branch, exports, no db-review banner)', async () => {
    window.localStorage.setItem('examJob.activeId', 'job-1')
    api.fetchJob.mockResolvedValue(makeCompletedView())
    render(<ExamGenerationSection />)
    await waitFor(() => expect(screen.getByTestId('job-status')).toHaveTextContent('הושלם'))
    expect(screen.queryByTestId('db-review-banner')).not.toBeInTheDocument()
    expect(screen.getByTestId('branch-button-active')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ייצא מבחן (DOCX)' })).toBeEnabled()
  })

  it('a historical (read-only) db_review job shows the waiting banner with no Continue button', async () => {
    api.fetchJobsList.mockResolvedValue([
      { job_id: 'old-job', display_name: 'מבחן ישן ממתין', created_utc: '2026-01-01T00:00:00Z', status: 'queued', workflow_phase: 'db_review' },
    ])
    api.fetchJob.mockResolvedValue(makeDbReviewView({ job_id: 'old-job' }))
    const user = userEvent.setup()
    render(<ExamGenerationSection />)
    await screen.findByTestId('saved-exam-list')
    await user.click(screen.getByRole('button', { name: 'פתח' }))

    expect(await screen.findByTestId('readonly-banner')).toBeInTheDocument()
    expect(screen.getByTestId('db-review-banner')).toBeInTheDocument()
    expect(screen.queryByTestId('continue-llm-button')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'החלף בשאלה מהמאגר' })).not.toBeInTheDocument()
  })
})
