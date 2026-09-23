import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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
  updateQuestionManually: vi.fn(),
  downloadGeneratedXlsx: vi.fn(),
  downloadFullExamXlsx: vi.fn(),
  downloadExamDocx: vi.fn(),
  saveBlob: vi.fn(),
}))

import * as api from '@/lib/examApi.js'
import ExamGenerationSection from './ExamGenerationSection.jsx'

const STATUS_LABEL = { completed: 'הושלם' }

function dbQuestion(n, iid) {
  return {
    number: n, question: `שאלת מאגר ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 1,
    origin: 'database', instance_id: iid, id: 100 + n,
    category: 'מבוא', categories: ['מבוא'],
    accuracy: null, distinction: null, accuracy_list: [], distinction_list: [],
  }
}

function llmQuestion(n, iid, { reviewQuality = 'clean', reviewWarnings = [], manuallyEdited = false } = {}) {
  return {
    number: n, question: `שאלת בינה ${n}`,
    answer1: 'א', answer2: 'ב', answer3: 'ג', answer4: 'ד', correct_answer: 2,
    origin: 'llm', instance_id: iid, id: null,
    category: 'מבוא', categories: ['מבוא'],
    generation_meta: {
      attempts: 1, retries_by_slot: 0, cost_usd: '0.34', outcome: 'accepted',
      review_quality: reviewQuality, review_warnings: reviewWarnings, manually_edited: manuallyEdited,
    },
  }
}

const WARNING = {
  warning_id: 'w1', code: 'weak_distractor_type_mismatch', field: 'answer4',
  message_he: 'תשובה 4 אינה מאותו סוג מבני.', resolved: false, resolved_by: null, resolved_at: null,
}

function makeView(over = {}) {
  const questions = over.questions || [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm')]
  return {
    job_id: 'job-1', status: 'completed',
    cost_ceiling_usd: '5.00', accumulated_cost_usd: '0.34', cost_basis: 'conservative_bound',
    remaining_cost_usd: '4.66', warnings: [],
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
    questions,
    category_history: {},
    attempt_telemetry: {
      by_category: { מבוא: { attempts: 1, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 1, cost_usd: '0.34', entries: 1 } },
      by_slot: {
        's-db': { attempts: 0, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 0, cost_usd: '0', entries: 0 },
        's-llm': { attempts: 1, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 1, cost_usd: '0.34', entries: 1 },
      },
      by_instance: {
        'iid-db': { attempts: 0, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 0, cost_usd: '0', entries: 0 },
        'iid-llm': { attempts: 1, failed_attempts: 0, charged_failed_attempts: 0, retries: 0, replacements: 0, accepted: 1, cost_usd: '0.34', entries: 1 },
      },
    },
    identity: null, display_name: 'מבחן', slug: 'exam',
    parent_job_id: null, root_job_id: 'job-1',
    excluded_db_ids_count: 0, branchable: true,
    workflow_phase: 'complete', pending_llm_total: 0, accepted_count: 2,
    ...over,
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

describe('WP28 - warning badge and field highlighting', () => {
  it('shows the "דורש בדיקה" badge, the Hebrew explanation, and highlights the exact affected answer', async () => {
    await renderResumed(makeView({
      questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm', { reviewQuality: 'warning', reviewWarnings: [WARNING] })],
    }))
    const card = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    const within2 = within(card)
    expect(within2.getByTestId('requires-review-badge')).toHaveTextContent('דורש בדיקה')
    expect(within2.getByTestId('warning-explanation')).toHaveTextContent(WARNING.message_he)
    // answer4 is the flagged field (index 3, 1-based label "4.")
    const answerRow = within2.getByText('ד').closest('div.p-2')
    expect(answerRow.className).toMatch(/amber/)
  })

  it('shows a quieter "תוקן ידנית" state once the warning is resolved, not the active warning', async () => {
    const resolved = { ...WARNING, resolved: true, resolved_by: 'manual_edit', resolved_at: '2026-01-01T00:00:00Z' }
    await renderResumed(makeView({
      questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm', { reviewQuality: 'warning', reviewWarnings: [resolved], manuallyEdited: true })],
    }))
    const card = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    expect(within(card).getByTestId('manually-fixed-badge')).toHaveTextContent('תוקן ידנית')
    expect(within(card).queryByTestId('requires-review-badge')).not.toBeInTheDocument()
    expect(within(card).queryByTestId('warning-explanation')).not.toBeInTheDocument()
  })

  it('a clean LLM question and a database question show neither badge', async () => {
    await renderResumed(makeView())
    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    for (const card of [dbCard, llmCard]) {
      expect(within(card).queryByTestId('requires-review-badge')).not.toBeInTheDocument()
      expect(within(card).queryByTestId('manually-fixed-badge')).not.toBeInTheDocument()
    }
  })
})

describe('WP28 - edit control only on LLM-origin questions', () => {
  it('only the LLM question has an "ערוך שאלה" control', async () => {
    await renderResumed(makeView())
    const dbCard = screen.getByText('1. שאלת מאגר 1').closest('div.p-4')
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    expect(within(dbCard).queryByTestId('edit-question-button')).not.toBeInTheDocument()
    expect(within(llmCard).getByTestId('edit-question-button')).toBeInTheDocument()
  })
})

describe('WP28 - edit form validation, cancel, save, and rerender', () => {
  async function openEdit(user) {
    await renderResumed(makeView())
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByTestId('edit-question-button'))
    return screen.getByText('עריכת שאלה').closest('div.relative')
  }

  it('the form opens pre-filled with the current values', async () => {
    const user = userEvent.setup()
    const dialog = await openEdit(user)
    expect(within(dialog).getByLabelText('גוף השאלה')).toHaveValue('שאלת בינה 2')
    expect(within(dialog).getByLabelText('תשובה 1')).toHaveValue('א')
  })

  it('shows a validation error and never calls the API when two answers are made identical', async () => {
    const user = userEvent.setup()
    const dialog = await openEdit(user)
    const a2 = within(dialog).getByLabelText('תשובה 2')
    await user.clear(a2)
    await user.type(a2, 'א') // now equals answer1
    await user.click(within(dialog).getByRole('button', { name: 'שמירה' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('שונות')
    expect(api.updateQuestionManually).not.toHaveBeenCalled()
  })

  it('cancel closes the form and makes no API call', async () => {
    const user = userEvent.setup()
    const dialog = await openEdit(user)
    await user.click(within(dialog).getByRole('button', { name: 'ביטול' }))
    expect(screen.queryByText('עריכת שאלה')).not.toBeInTheDocument()
    expect(api.updateQuestionManually).not.toHaveBeenCalled()
  })

  it('a successful save persists through the backend and rerenders immediately', async () => {
    const user = userEvent.setup()
    const dialog = await openEdit(user)
    const stem = within(dialog).getByLabelText('גוף השאלה')
    await user.clear(stem)
    await user.type(stem, 'שאלה מתוקנת')
    const updatedView = makeView({
      questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm', { manuallyEdited: true })],
    })
    updatedView.questions[1].question = 'שאלה מתוקנת'
    api.updateQuestionManually.mockResolvedValue(updatedView)

    await user.click(within(dialog).getByRole('button', { name: 'שמירה' }))
    expect(api.updateQuestionManually).toHaveBeenCalledWith(
      'job-1', 'iid-llm',
      expect.objectContaining({ question: 'שאלה מתוקנת', correct_answer: 2 }),
    )
    await screen.findByText('2. שאלה מתוקנת')
    expect(screen.queryByText('עריכת שאלה')).not.toBeInTheDocument()
  })
})

describe('WP28 - reload displays persisted edits and resolved-warning state', () => {
  it('a freshly fetched job already shows manually_edited / resolved metadata', async () => {
    const resolved = { ...WARNING, resolved: true, resolved_by: 'manual_edit' }
    await renderResumed(makeView({
      questions: [
        dbQuestion(1, 'iid-db'),
        { ...llmQuestion(2, 'iid-llm', { reviewQuality: 'warning', reviewWarnings: [resolved], manuallyEdited: true }), question: 'כבר נערכה בעבר' },
      ],
    }))
    const card = screen.getByText('2. כבר נערכה בעבר').closest('div.p-4')
    expect(within(card).getByTestId('manually-fixed-badge')).toBeInTheDocument()
  })
})

describe('WP28 - export confirmation when unresolved warnings remain', () => {
  const viewWithWarning = () => makeView({
    questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm', { reviewQuality: 'warning', reviewWarnings: [WARNING] })],
  })

  it('asks for confirmation before each export when an unresolved warning exists', async () => {
    const user = userEvent.setup()
    await renderResumed(viewWithWarning())
    await user.click(screen.getByRole('button', { name: 'ייצא מבחן (DOCX)' }))
    expect(screen.getByTestId('export-confirm-message')).toHaveTextContent('1 שאלות')
    expect(api.downloadExamDocx).not.toHaveBeenCalled()
  })

  it('cancelling the confirmation makes no export call', async () => {
    const user = userEvent.setup()
    await renderResumed(viewWithWarning())
    await user.click(screen.getByRole('button', { name: 'ייצוא שאלות בינה בלבד (Excel)' }))
    await user.click(screen.getByRole('button', { name: 'ביטול' }))
    expect(api.downloadGeneratedXlsx).not.toHaveBeenCalled()
    expect(screen.queryByTestId('export-confirm-message')).not.toBeInTheDocument()
  })

  it('confirming makes exactly one export call', async () => {
    const user = userEvent.setup()
    await renderResumed(viewWithWarning())
    api.downloadFullExamXlsx.mockResolvedValue(new Blob(['x']))
    await user.click(screen.getByRole('button', { name: 'ייצוא מבחן מלא (Excel)' }))
    await user.click(screen.getByRole('button', { name: 'המשך בייצוא' }))
    await waitFor(() => expect(api.downloadFullExamXlsx).toHaveBeenCalledTimes(1))
    expect(api.downloadFullExamXlsx).toHaveBeenCalledWith('job-1')
  })

  it('resolved warnings never trigger the confirmation', async () => {
    const user = userEvent.setup()
    const resolved = { ...WARNING, resolved: true, resolved_by: 'manual_edit' }
    await renderResumed(makeView({
      questions: [dbQuestion(1, 'iid-db'), llmQuestion(2, 'iid-llm', { reviewQuality: 'warning', reviewWarnings: [resolved] })],
    }))
    api.downloadGeneratedXlsx.mockResolvedValue(new Blob(['x']))
    await user.click(screen.getByRole('button', { name: 'ייצוא שאלות בינה בלבד (Excel)' }))
    expect(screen.queryByTestId('export-confirm-message')).not.toBeInTheDocument()
    await waitFor(() => expect(api.downloadGeneratedXlsx).toHaveBeenCalledTimes(1))
  })
})

describe('WP28 - failed LLM replacement retention message', () => {
  it('clearly states the original was retained', async () => {
    const user = userEvent.setup()
    await renderResumed(makeView())
    api.replaceViaLlm.mockRejectedValue(
      Object.assign(new Error('לא נוצרה שאלה חלופית. השאלה המקורית נשמרה. (ניסיונות: 2, עלות: $0.19)'), { status: 200 }),
    )
    const llmCard = screen.getByText('2. שאלת בינה 2').closest('div.p-4')
    await user.click(within(llmCard).getByRole('button', { name: 'צור שאלה אחרת' }))
    await screen.findByText(/לא נוצרה שאלה חלופית\. השאלה המקורית נשמרה\./)
    // the original question is still shown, unchanged
    expect(screen.getByText('2. שאלת בינה 2')).toBeInTheDocument()
  })
})

describe('WP28 - RTL/LTR numeric ratio isolation', () => {
  it('the accepted-count ratio is isolated in a left-to-right bdi element with logical operand order', async () => {
    await renderResumed(makeView())
    const el = screen.getByTestId('accepted-count').querySelector('bdi')
    expect(el).toBeTruthy()
    expect(el).toHaveAttribute('dir', 'ltr')
    expect(el.textContent).toBe('2 / 2')
  })

  it('the accumulated-cost ratio is isolated the same way', async () => {
    await renderResumed(makeView())
    const el = screen.getByTestId('accumulated-cost').querySelector('bdi')
    expect(el).toBeTruthy()
    expect(el).toHaveAttribute('dir', 'ltr')
  })
})
