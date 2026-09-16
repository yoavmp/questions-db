import { describe, it, expect, beforeEach } from 'vitest'
import {
  COURSE_CHOICES,
  EXAM_TYPE_CHOICES,
  buildIdentityPayload,
  defaultYear,
  emptyIdentity,
  identityBlockers,
  jobListLabel,
  loadViewedJobId,
  saveViewedJobId,
  structuredDisplayName,
  syncViewedJobIdToUrl,
} from './examGen.js'

beforeEach(() => {
  window.localStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('exam identity (WP26 §1)', () => {
  it('emptyIdentity defaults to structured mode with the current year and default sitting', () => {
    const identity = emptyIdentity()
    expect(identity.mode).toBe('structured')
    expect(identity.course).toBe(COURSE_CHOICES[0])
    expect(identity.exam_type).toBe(EXAM_TYPE_CHOICES[0])
    expect(identity.sitting).toBe('א')
    expect(identity.year).toBe(defaultYear())
  })

  it('builds the exact example structured display name', () => {
    const name = structuredDisplayName({
      course: 'מבנה המוח', year: '2026', exam_type: 'מבחן מסכם', sitting: 'א',
    })
    expect(name).toBe('מבנה המוח 2026 מבחן מסכם מועד א')
  })

  it('structured payload trims year/sitting and defaults a blank sitting', () => {
    const payload = buildIdentityPayload({
      mode: 'structured', course: 'נוירואנטומיה', year: ' 2025 ', exam_type: 'מבחן אמצע', sitting: '  ',
    })
    expect(payload).toEqual({
      mode: 'structured', course: 'נוירואנטומיה', year: '2025', exam_type: 'מבחן אמצע', sitting: 'א',
    })
  })

  it('custom payload uses the trimmed custom name exactly', () => {
    const payload = buildIdentityPayload({ mode: 'custom', custom_name: '  תרגול  ' })
    expect(payload).toEqual({ mode: 'custom', custom_name: 'תרגול' })
  })

  it('identityBlockers flags an invalid structured form', () => {
    const blockers = identityBlockers({
      mode: 'structured', course: 'לא קיים', year: '26', exam_type: 'לא קיים', sitting: '',
    })
    expect(blockers.length).toBeGreaterThan(0)
  })

  it('identityBlockers is empty for a valid structured form', () => {
    expect(identityBlockers(emptyIdentity())).toEqual([])
  })

  it('identityBlockers flags an empty custom name', () => {
    expect(identityBlockers({ mode: 'custom', custom_name: '   ' }).length).toBe(1)
    expect(identityBlockers({ mode: 'custom', custom_name: 'x' })).toEqual([])
  })
})

describe('jobListLabel', () => {
  it('includes the display name, date and short id', () => {
    const label = jobListLabel({
      display_name: 'מבנה המוח 2026 מבחן מסכם מועד א',
      created_utc: '2026-09-16T14:00:00Z',
      job_id: '14f2a1ea-0000-0000-0000-000000000000',
    })
    expect(label).toContain('מבנה המוח 2026 מבחן מסכם מועד א')
    expect(label).toContain('2026-09-16')
    expect(label).toContain('14f2a1ea')
  })
})

describe('viewed-job persistence (WP26 §5, separate from the active job)', () => {
  it('round-trips through localStorage independently of the active-job key', () => {
    saveViewedJobId('viewed-123')
    expect(loadViewedJobId()).toBe('viewed-123')
    expect(window.localStorage.getItem('examJob.activeId')).toBeNull()
  })

  it('the URL param takes precedence, and can be cleared independently', () => {
    syncViewedJobIdToUrl('from-url')
    expect(window.location.search).toContain('viewJob=from-url')
    expect(loadViewedJobId()).toBe('from-url')
    syncViewedJobIdToUrl(null)
    expect(window.location.search).not.toContain('viewJob')
  })
})
