import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// WP31 Part A/B/C: credential-failure display, network/CORS error messaging,
// exactly-one-PATCH editing, and actual-vs-upper-bound cost labeling.

vi.mock('@/lib/examApi.js', () => ({
  API_BASE_URL: 'http://test/api',
  NETWORK_ERROR_MESSAGE_HE:
    'תקשורת עם השרת נכשלה (בדקו שה-Backend פועל ושאין חסימת CORS) – נסו שוב.',
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
  updateQuestionManually: vi.fn(),
  downloadGeneratedXlsx: vi.fn(),
  downloadFullExamXlsx: vi.fn(),
  downloadExamDocx: vi.fn(),
  saveBlob: vi.fn(),
}))

import * as api from '@/lib/examApi.js'
import ExamGenerationSection from './ExamGenerationSection.jsx'

const STATUS_LABEL = { completed: 'הושלם', partial: 'הושלם חלקית' }

const AUTH_FAILURE_HEBREW_MESSAGE =
  'מפתח ה-API של OpenAI שגוי או חסר בשרת. יש לתקן את מפתח ה-API ' +
  'בהגדרות השרת (OPENAI_API_KEY) ולהפעיל את השרת מחדש.'

function dbQuestion(n, iid) {
  return {
    number: n, question: `שאלת מאגר ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 1,
    origin: 'database', instance_id: iid, id: 100 + n,
    category: 'מבוא', categories: ['מבוא'],
    accuracy: null, distinction: null, accuracy_list: [], distinction_list: [],
  }
}

function llmQuestion(n, iid, over = {}) {
  return {
    number: n, question: `שאלת בינה ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 2,
    origin: 'llm', instance_id: iid, id: null,
    category: 'מבוא', categories: ['מבוא'],
    generation_meta: {
      attempts: 1, retries_by_slot: 0, cost_usd: '0.34', outcome: 'accepted',
      review_quality: 'clean', review_warnings: [], manually_edited: false,
    },
    ...over,
  }
}

function makeView(over = {}) {
  const questions = over.questions || [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')]
  const extraSlots = over.extraSlots || []
  return {
    job_id: 'job-1', status: over.status || 'completed',
    cost_ceiling_usd: '5.00', accumulated_cost_usd: '0.34',
    cost_basis: over.cost_basis || 'conservative_bound',
    remaining_cost_usd: '4.66', warnings: [],
    totals: { questions_requested: 2, llm_requested: 1, llm_accepted: 1, llm_failed: 0, retries: 0 },
    categories: {
      מבוא: {
        order_index: 0, total: 2, database: 1, llm: 1, accepted: 2, failed: 0, pending: 0,
        slots: [
          { slot_id: 's-db', instance_id: 'iid-db', kind: 'database', number: 1, status: 'accepted', attempts: 0, retries: 0, safe_error: null },
          { slot_id: 's-llm', instance_id: 'iid-llm', kind: 'llm', number: 2, status: 'accepted', attempts: 1, retries: 0, safe_error: null },
          ...extraSlots,
        ],
      },
    },
    questions,
    category_history: {},
    attempt_telemetry: { by_category: {}, by_slot: {}, by_instance: {} },
    identity: null, display_name: 'מבחן', slug: 'exam',
    parent_job_id: null, root_job_id: 'job-1',
    excluded_db_ids_count: 0, branchable: true,
    workflow_phase: 'complete', pending_llm_total: 0, accepted_count: 2,
    safe_error: over.safe_error ?? null,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.clearAllMocks()
  api.fetchCategories.mockResolvedValue([])
  api.fetchReadiness.mockResolvedValue({ ready_for_llm: true, warnings: [], blocking_reasons: [] })
  api.fetchJobsList.mockResolvedValue([])
})

async function renderResumed(view) {
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

describe('WP31 Part C - editing sends exactly one PATCH', () => {
  it('saving an edit calls updateQuestionManually exactly once with the six editable fields', async () => {
    const user = userEvent.setup()
    await renderResumed(makeView())
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByTestId('edit-question-button'))
    const dialog = screen.getByText('עריכת שאלה').closest('div.relative')
    const stem = within(dialog).getByLabelText('גוף השאלה')
    await user.clear(stem)
    await user.type(stem, 'שאלה מתוקנת')

    const updated = makeView({ questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')] })
    updated.questions[1].question = 'שאלה מתוקנת'
    api.updateQuestionManually.mockResolvedValue(updated)

    await user.click(within(dialog).getByRole('button', { name: 'שמירה' }))
    await screen.findByText('2. שאלה מתוקנת')

    expect(api.updateQuestionManually).toHaveBeenCalledTimes(1)
    expect(api.updateQuestionManually).toHaveBeenCalledWith(
      'job-1', 'iid-llm',
      {
        question: 'שאלה מתוקנת', answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד',
        correct_answer: 2,
      },
    )
  })
})

describe('WP31 Part C - network/CORS failure shows the Hebrew message', () => {
  it('a rejected PATCH carrying the network-error message shows it, not a raw browser error', async () => {
    const user = userEvent.setup()
    await renderResumed(makeView())
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByTestId('edit-question-button'))
    const dialog = screen.getByText('עריכת שאלה').closest('div.relative')

    const netErr = new Error(api.NETWORK_ERROR_MESSAGE_HE)
    netErr.isNetworkError = true
    api.updateQuestionManually.mockRejectedValue(netErr)

    await user.click(within(dialog).getByRole('button', { name: 'שמירה' }))
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent(api.NETWORK_ERROR_MESSAGE_HE)
    expect(alert.textContent).not.toMatch(/Failed to fetch/i)
    expect(alert.textContent).not.toMatch(/TypeError/i)
  })
})

describe('WP31 Part A - credential failure is shown distinctly, never as a rejected question', () => {
  it('an authentication-failed LLM slot carries the actionable Hebrew key message as its safe_error, distinct from a content rejection', async () => {
    const failedSlot = llmQuestion(3, 'iid-llm-2')
    const view = makeView({
      status: 'partial',
      questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')],
      extraSlots: [
        {
          slot_id: 's-llm-2', instance_id: 'iid-llm-2', kind: 'llm', number: 3,
          status: 'failed', attempts: 1, retries: 0,
          safe_error: AUTH_FAILURE_HEBREW_MESSAGE,
        },
      ],
      safe_error: AUTH_FAILURE_HEBREW_MESSAGE,
    })
    await renderResumed(view)

    const warningIcon = screen.getByText('⚠')
    expect(warningIcon).toHaveAttribute('title', AUTH_FAILURE_HEBREW_MESSAGE)
    // never a generic/placeholder rejection reason masquerading as content review
    expect(warningIcon.getAttribute('title')).not.toMatch(/נפסל|דחיה|distractor|review/i)
    expect(warningIcon.getAttribute('title')).toMatch(/API/)
  })
})

describe('WP31 Part B §4 - actual vs. upper-bound cost labels', () => {
  it('a token-derived ("calculated") cost is labeled as actual calculated usage', async () => {
    await renderResumed(makeView({ cost_basis: 'calculated' }))
    const label = screen.getByTestId('cost-basis-label')
    expect(label.textContent).toMatch(/בפועל/)
    expect(label.textContent).not.toMatch(/הערכ/)
  })

  it('a fallback ("conservative_bound") cost is labeled explicitly as an estimated upper bound, never money definitely spent', async () => {
    await renderResumed(makeView({ cost_basis: 'conservative_bound' }))
    const label = screen.getByTestId('cost-basis-label')
    expect(label.textContent).toMatch(/הערכ/)
    expect(label.textContent).toMatch(/לא עלות בפועל/)
  })
})
