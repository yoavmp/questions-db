import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as api from './examApi.js'

// These tests stub the global fetch (fake API fixtures) to lock the wire
// contract: paths, verbs, and -- for DOCX -- that job-only metadata is stripped
// before the questions reach the legacy endpoint.

function okJson(body) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  })
}
function errJson(status, body) {
  return Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve(body),
  })
}

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

describe('job endpoints', () => {
  it('createJob POSTs to /exam-jobs', async () => {
    fetch.mockReturnValueOnce(okJson({ job_id: 'j1', status: 'queued' }))
    const res = await api.createJob({ categories: {}, cost_ceiling_usd: '5.00' })
    expect(res.job_id).toBe('j1')
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/exam-jobs$/)
    expect(opts.method).toBe('POST')
  })

  it('fetchJob GETs /exam-jobs/<id>', async () => {
    fetch.mockReturnValueOnce(okJson({ status: 'completed', questions: [] }))
    await api.fetchJob('j1')
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/exam-jobs\/j1$/)
  })

  it('retrySlot / updateCostCeiling / replace endpoints hit the right paths', async () => {
    fetch.mockReturnValue(okJson({ status: 'completed', questions: [] }))
    await api.retrySlot('j1', 's1')
    await api.updateCostCeiling('j1', 9)
    await api.replaceFromDb('j1', 'iid')
    await api.replaceViaLlm('j1', 'iid')
    const paths = fetch.mock.calls.map((c) => c[0])
    expect(paths[0]).toMatch(/\/exam-jobs\/j1\/slots\/s1\/retry$/)
    expect(paths[1]).toMatch(/\/exam-jobs\/j1\/cost-ceiling$/)
    expect(paths[2]).toMatch(/\/exam-jobs\/j1\/questions\/iid\/replace-db$/)
    expect(paths[3]).toMatch(/\/exam-jobs\/j1\/questions\/iid\/replace-llm$/)
    expect(fetch.mock.calls[1][1].method).toBe('PUT')
  })

  it('throws an Error carrying the backend reason + status on non-2xx', async () => {
    fetch.mockReturnValueOnce(errJson(409, { error: 'another operation is already running' }))
    await expect(api.replaceFromDb('j1', 'iid')).rejects.toMatchObject({
      status: 409,
      message: 'another operation is already running',
    })
  })

  it('updateQuestionManually PATCHes /exam-jobs/<id>/questions/<iid> with the six editable fields', async () => {
    fetch.mockReturnValueOnce(okJson({ status: 'completed', questions: [] }))
    const payload = {
      question: 'q?', answer1: 'a1', answer2: 'a2', answer3: 'a3', answer4: 'a4', correct_answer: 2,
    }
    await api.updateQuestionManually('j1', 'iid', payload)
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/exam-jobs\/j1\/questions\/iid$/)
    expect(opts.method).toBe('PATCH')
    expect(JSON.parse(opts.body)).toEqual(payload)
  })
})

describe('WP26 jobs-list / branch / exclusion-preview endpoints', () => {
  it('fetchJobsList GETs /exam-jobs and returns the jobs array', async () => {
    fetch.mockReturnValueOnce(okJson({ jobs: [{ job_id: 'j1' }, { job_id: 'j2' }] }))
    const jobs = await api.fetchJobsList()
    expect(jobs).toHaveLength(2)
    expect(fetch.mock.calls[0][0]).toMatch(/\/api\/exam-jobs$/)
  })

  it('fetchJobsList tolerates a missing jobs key', async () => {
    fetch.mockReturnValueOnce(okJson({}))
    expect(await api.fetchJobsList()).toEqual([])
  })

  it('branchJob POSTs the identity to /exam-jobs/<id>/branch', async () => {
    fetch.mockReturnValueOnce(okJson({ job_id: 'child-1', parent_job_id: 'j1' }))
    const identity = { mode: 'custom', custom_name: 'גרסה חדשה' }
    const res = await api.branchJob('j1', identity)
    expect(res.job_id).toBe('child-1')
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/exam-jobs\/j1\/branch$/)
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ identity })
  })

  it('previewExclusionFile POSTs multipart form data to the preview endpoint', async () => {
    fetch.mockReturnValueOnce(okJson({ resolved_db_ids: [1, 2], counts: {}, warnings: [] }))
    const file = new File(['a,b'], 'excl.xlsx')
    const res = await api.previewExclusionFile(file)
    expect(res.resolved_db_ids).toEqual([1, 2])
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/exam-jobs\/exclusions\/preview$/)
    expect(opts.body).toBeInstanceOf(FormData)
  })
})

describe('downloadExamDocx', () => {
  it('POSTs only the seven public fields (job metadata stripped) to /test/export-docx', async () => {
    fetch.mockReturnValueOnce(
      Promise.resolve({ ok: true, status: 200, blob: () => Promise.resolve(new Blob(['x'])) }),
    )
    const jobQuestions = [
      {
        number: 1,
        question: 'q1',
        answer1: 'a',
        answer2: 'b',
        answer3: 'c',
        answer4: 'd',
        correct_answer: 2,
        origin: 'llm',
        instance_id: 'iid-1',
        id: null,
        generation_meta: { attempts: 2, cost_usd: '0.3' },
        categories: ['מבוא'],
      },
    ]
    await api.downloadExamDocx(jobQuestions, true)
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/test\/export-docx$/)
    const sent = JSON.parse(opts.body)
    expect(sent.include_answers).toBe(true)
    expect(sent.questions).toHaveLength(1)
    expect(Object.keys(sent.questions[0]).sort()).toEqual(
      ['answer1', 'answer2', 'answer3', 'answer4', 'correct_answer', 'number', 'question'].sort(),
    )
    expect(sent.questions[0]).not.toHaveProperty('generation_meta')
    expect(sent.questions[0]).not.toHaveProperty('origin')
    expect(sent.questions[0]).not.toHaveProperty('instance_id')
  })
})

describe('downloadGeneratedXlsx / downloadFullExamXlsx (two distinct routes, §5)', () => {
  it('downloadGeneratedXlsx GETs the LLM-only export endpoint and returns a Blob', async () => {
    fetch.mockReturnValueOnce(
      Promise.resolve({ ok: true, status: 200, blob: () => Promise.resolve(new Blob(['x'])) }),
    )
    const blob = await api.downloadGeneratedXlsx('j1')
    expect(blob).toBeInstanceOf(Blob)
    expect(fetch.mock.calls[0][0]).toMatch(/\/exam-jobs\/j1\/export\.xlsx$/)
  })

  it('downloadFullExamXlsx GETs its own distinct full-export endpoint', async () => {
    fetch.mockReturnValueOnce(
      Promise.resolve({ ok: true, status: 200, blob: () => Promise.resolve(new Blob(['x'])) }),
    )
    const blob = await api.downloadFullExamXlsx('j1')
    expect(blob).toBeInstanceOf(Blob)
    expect(fetch.mock.calls[0][0]).toMatch(/\/exam-jobs\/j1\/export-full\.xlsx$/)
  })
})
