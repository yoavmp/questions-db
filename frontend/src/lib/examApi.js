// Thin fetch wrappers for the asynchronous exam-generation job API (WP18/WP18R)
// plus the two legacy output endpoints WP19 keeps using (categories + DOCX).
//
// Every call returns parsed JSON (or a Blob for downloads) and throws an Error
// carrying { status, body } on a non-2xx response so the component can show the
// backend's Hebrew reason.

import { stripJobMetadata } from './examGen.js'

export const API_BASE_URL =
  (typeof window !== 'undefined' && window.__API_BASE_URL__) ||
  'http://127.0.0.1:4567/api'

async function jsonOrThrow(resp) {
  let body = null
  try {
    body = await resp.json()
  } catch {
    body = null
  }
  if (!resp.ok) {
    const msg = (body && (body.error || body.message)) || `HTTP ${resp.status}`
    const err = new Error(msg)
    err.status = resp.status
    err.body = body
    throw err
  }
  return body
}

// --- categories (canonical order + live DB availability) -------------
export async function fetchCategories() {
  const resp = await fetch(`${API_BASE_URL}/test/categories`)
  return jsonOrThrow(resp)
}

export async function fetchReadiness() {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/readiness`)
  return jsonOrThrow(resp)
}

// --- jobs -----------------------------------------------------------
export async function createJob(payload) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return jsonOrThrow(resp) // { job_id, status, url, display_name, slug }
}

export async function fetchJob(jobId) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}`)
  return jsonOrThrow(resp) // full result_view
}

// WP27 -- claim + run the originally-planned LLM batch for a job currently
// awaiting DB-review approval. Small response shape, same as createJob; the
// caller re-fetches fetchJob() for the full (possibly still in-progress) result.
export async function continueLlm(jobId) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}/continue-llm`, {
    method: 'POST',
  })
  return jsonOrThrow(resp) // { job_id, status, workflow_phase, url }
}

// WP26 §1 -- every persisted job, newest-first, safe list fields only.
export async function fetchJobsList() {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs`)
  const body = await jsonOrThrow(resp)
  return body.jobs || []
}

// WP26 §4 -- branch a completed saved exam into a new editable job. The
// parent is never mutated; `identity` is the same structured/custom shape
// `createJob` accepts.
export async function branchJob(jobId, identity) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}/branch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identity }),
  })
  return jsonOrThrow(resp)
}

// WP26 §2 -- local, non-provider preview/resolve of an optional exclusion
// workbook. Never persists the uploaded bytes.
export async function previewExclusionFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/exclusions/preview`, {
    method: 'POST',
    body: formData,
  })
  return jsonOrThrow(resp)
}

export async function retrySlot(jobId, slotId) {
  const resp = await fetch(
    `${API_BASE_URL}/exam-jobs/${jobId}/slots/${slotId}/retry`,
    { method: 'POST' },
  )
  return jsonOrThrow(resp)
}

export async function updateCostCeiling(jobId, ceilingUsd) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}/cost-ceiling`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cost_ceiling_usd: Number(ceilingUsd).toFixed(2) }),
  })
  return jsonOrThrow(resp)
}

export async function replaceFromDb(jobId, instanceId) {
  const resp = await fetch(
    `${API_BASE_URL}/exam-jobs/${jobId}/questions/${instanceId}/replace-db`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
  )
  return jsonOrThrow(resp)
}

export async function replaceViaLlm(jobId, instanceId) {
  const resp = await fetch(
    `${API_BASE_URL}/exam-jobs/${jobId}/questions/${instanceId}/replace-llm`,
    { method: 'POST' },
  )
  return jsonOrThrow(resp)
}

// WP28 §B3 -- persistently edit the current LLM-origin question in one slot.
// `payload` is the six editable fields (question, answer1..4, correct_answer).
export async function updateQuestionManually(jobId, instanceId, payload) {
  const resp = await fetch(
    `${API_BASE_URL}/exam-jobs/${jobId}/questions/${instanceId}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  )
  return jsonOrThrow(resp)
}

// --- downloads ----------------------------------------------------
// Two distinct, unambiguous exports (WP21 §5) -- one route/label per meaning:
// LLM-only (unchanged since WP18/19, for later manual DB upload) vs. the full
// current exam (new, complete legacy schema). Never overload one label.
export async function downloadGeneratedXlsx(jobId) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}/export.xlsx`)
  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status}`)
    err.status = resp.status
    throw err
  }
  return resp.blob()
}

export async function downloadFullExamXlsx(jobId) {
  const resp = await fetch(`${API_BASE_URL}/exam-jobs/${jobId}/export-full.xlsx`)
  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status}`)
    err.status = resp.status
    throw err
  }
  return resp.blob()
}

// The existing Hebrew DOCX path. Job-only metadata is stripped first; answer
// randomisation stays owned by the DOCX endpoint.
export async function downloadExamDocx(questions, includeAnswers) {
  const resp = await fetch(`${API_BASE_URL}/test/export-docx`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      questions: stripJobMetadata(questions),
      include_answers: !!includeAnswers,
    }),
  })
  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status}`)
    err.status = resp.status
    throw err
  }
  return resp.blob()
}

// Trigger a browser download for a fetched Blob.
export function saveBlob(blob, filename) {
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.style.display = 'none'
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  window.URL.revokeObjectURL(url)
  document.body.removeChild(a)
}
