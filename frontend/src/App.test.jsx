import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App.jsx'

// WP26 §6 -- topic bar must come from the backend's authoritative
// CATEGORY_ORDER (via /api/test/categories), not from question insertion
// order or alphabetization.
const CANONICAL_CATEGORIES = [
  { name: 'מבוא', question_count: 3 },
  { name: 'התעלה השדרתית ותכולתה', question_count: 1 },
  { name: 'גרעיני הבסיס', question_count: 2 },
]

function mockFetchByUrl(routes) {
  globalThis.fetch = vi.fn((url) => {
    for (const [pattern, body] of routes) {
      if (pattern.test(String(url))) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
      }
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  })
}

beforeEach(() => {
  mockFetchByUrl([
    [/\/api\/questions$/, []],
    [/\/api\/test\/categories$/, CANONICAL_CATEGORIES],
  ])
})

describe('App shell (WP26 §6 UI corrections)', () => {
  it('renders the exact required brand title', async () => {
    render(<App />)
    expect(
      await screen.findByText('מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב'),
    ).toBeInTheDocument()
  })

  it('lays out the top tabs so אודות המערכת is first (rendered far right in RTL) and עיון בשאלות is last (far left)', async () => {
    render(<App />)
    await screen.findByText('מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב')
    const tabs = screen.getAllByRole('button').filter((b) =>
      ['אודות המערכת', 'העלאת שאלות', 'יצירת מבחן', 'עיון בשאלות'].includes(b.textContent),
    )
    expect(tabs.map((t) => t.textContent)).toEqual([
      'אודות המערכת', 'העלאת שאלות', 'יצירת מבחן', 'עיון בשאלות',
    ])
  })

  it('preserves upload-before-generation as the logical order of the two middle tabs', async () => {
    render(<App />)
    await screen.findByText('מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב')
    const tabs = screen.getAllByRole('button').filter((b) =>
      ['העלאת שאלות', 'יצירת מבחן'].includes(b.textContent),
    )
    expect(tabs[0].textContent).toBe('העלאת שאלות')
    expect(tabs[1].textContent).toBe('יצירת מבחן')
  })

  it('renders the question-browser topic bar in authoritative CATEGORY_ORDER, not alphabetized', async () => {
    render(<App />)
    const sidebar = await screen.findByText('נושאים')
    const card = sidebar.closest('div.rounded-lg')
    // each category row also has an icon-only "edit" button with no text --
    // keep only the labeled selector buttons ("כל השאלות" + one per category)
    const buttons = within(card).getAllByRole('button').filter((b) => b.textContent.trim() !== '')
    // first is "כל השאלות" (all questions); the rest follow CATEGORY_ORDER
    const names = buttons.slice(1).map((b) => b.textContent)
    expect(names[0]).toContain('מבוא')
    expect(names[1]).toContain('התעלה השדרתית ותכולתה')
    expect(names[2]).toContain('גרעיני הבסיס')
  })

  it('About tab replaces the old generic marketing content with course-relevant Hebrew information', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב')
    await user.click(screen.getByRole('button', { name: 'אודות המערכת' }))
    await waitFor(() => expect(screen.getByText('מטרת מאגר השאלות')).toBeInTheDocument())
    expect(screen.getByText(/היסטוריית מבחנים וגרסאות/)).toBeInTheDocument()
    expect(screen.getByText(/החרגת שאלות מהמאגר/)).toBeInTheDocument()
    expect(screen.queryByText('מערכת היברידית אמינה')).not.toBeInTheDocument()
  })
})
