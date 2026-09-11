import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button.jsx'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import { Input } from '@/components/ui/input.jsx'

import {
  DEFAULT_COST_CEILING_USD,
  DEFAULT_DISTINCTION_THRESHOLD,
  applyRowEdit,
  buildCreatePayload,
  emptyRow,
  formatMeasure,
  formatUSD,
  groupByCategory,
  isPollingStatus,
  loadActiveJobId,
  orderQuestions,
  overallAnalytics,
  parseCeiling,
  pricingWarnings,
  retryableSlots,
  rowNumbers,
  saveActiveJobId,
  slotAttemptCounts,
  slotAttemptCountsByInstance,
  startBlockers,
  syncJobIdToUrl,
  validateRow,
} from '@/lib/examGen.js'
import * as api from '@/lib/examApi.js'

const POLL_MS = 1500

const STATUS_LABEL = {
  queued: 'ממתין',
  running: 'רץ',
  completed: 'הושלם',
  partial: 'הושלם חלקית',
  interrupted: 'הופסק',
  cost_ceiling: 'נעצר בתקרת עלות',
  failed: 'נכשל',
}

const SLOT_STATUS_LABEL = {
  queued: 'ממתין',
  running: 'רץ',
  accepted: 'התקבל',
  failed: 'נכשל',
  interrupted: 'הופסק',
  cost_ceiling: 'תקרת עלות',
}

function OriginBadge({ origin }) {
  if (origin === 'llm') {
    return (
      <Badge variant="outline" className="hebrew-text border-purple-400 text-purple-700">
        נוצר בבינה מלאכותית
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="hebrew-text">
      מתוך המאגר
    </Badge>
  )
}

// --------------------------------------------------------------------------- //
// builder
// --------------------------------------------------------------------------- //
function CategoryInputs({ categories, rows, onEdit }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[1fr_5rem_5rem_5rem] gap-2 hebrew-text text-sm font-semibold text-gray-600 px-1">
        <span>נושא</span>
        <span className="text-center">סה"כ</span>
        <span className="text-center">מהמאגר</span>
        <span className="text-center">בינה</span>
      </div>
      {categories.map((cat) => {
        const row = rows[cat.name] || emptyRow()
        const { errors } = validateRow(row, cat.question_count)
        return (
          <div key={cat.name} className="p-3 border rounded-lg space-y-1">
            <div className="grid grid-cols-[1fr_5rem_5rem_5rem] gap-2 items-center">
              <div className="hebrew-text">
                <span className="font-medium">{cat.name}</span>
                <span className="text-gray-500 mr-2 text-sm">
                  ({cat.question_count} במאגר)
                </span>
              </div>
              <Input
                type="number"
                min="0"
                aria-label={`סה"כ שאלות עבור ${cat.name}`}
                value={row.total}
                onChange={(e) => onEdit(cat.name, 'total', e.target.value)}
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                aria-label={`שאלות מהמאגר עבור ${cat.name}`}
                value={row.database}
                onChange={(e) => onEdit(cat.name, 'database', e.target.value)}
                className="text-center"
              />
              <Input
                type="number"
                min="0"
                aria-label={`שאלות בבינה מלאכותית עבור ${cat.name}`}
                value={row.llm}
                onChange={(e) => onEdit(cat.name, 'llm', e.target.value)}
                className="text-center"
              />
            </div>
            {Object.values(errors).map((msg, i) => (
              <p key={i} role="alert" className="hebrew-text text-sm text-red-600">
                {msg}
              </p>
            ))}
          </div>
        )
      })}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// progress
// --------------------------------------------------------------------------- //
function SlotChips({ slots, telemetry, onRetry, retryingSlotId, mutating }) {
  return (
    <div className="flex flex-wrap gap-2">
      {slots.map((slot) => {
        const retryable =
          slot.kind === 'llm' &&
          ['failed', 'interrupted', 'cost_ceiling'].includes(slot.status)
        // ledger-derived, not the mutable (rollback-prone) slot counters (§6)
        const { attempts, retries } = slotAttemptCounts(telemetry, slot.slot_id)
        return (
          <span
            key={slot.slot_id}
            className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hebrew-text bg-gray-50"
          >
            <span className="font-medium">#{slot.number}</span>
            <span>{slot.kind === 'llm' ? 'בינה' : 'מאגר'}</span>
            <span
              className={
                slot.status === 'accepted'
                  ? 'text-green-700'
                  : slot.status === 'failed'
                    ? 'text-red-700'
                    : 'text-gray-600'
              }
            >
              {SLOT_STATUS_LABEL[slot.status] || slot.status}
            </span>
            {attempts > 0 && (
              <span className="text-gray-500">
                (ניסיונות: {attempts}
                {retries > 0 ? ` · חזרות: ${retries}` : ''})
              </span>
            )}
            {slot.safe_error && (
              <span className="text-red-600" title={slot.safe_error}>
                ⚠
              </span>
            )}
            {retryable && (
              <Button
                variant="outline"
                size="sm"
                className="hebrew-text h-6 px-2 text-xs"
                disabled={!!retryingSlotId || !!mutating}
                onClick={() => onRetry(slot.slot_id)}
              >
                {retryingSlotId === slot.slot_id ? 'מנסה שוב...' : 'נסה שוב'}
              </Button>
            )}
          </span>
        )
      })}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// result question
// --------------------------------------------------------------------------- //
function ResultQuestion({ q, telemetry, disabled, isMutating, onReplaceDb, onReplaceLlm }) {
  const [showAnswer, setShowAnswer] = useState(false)
  const answers = [q.answer1, q.answer2, q.answer3, q.answer4]
  // ledger-derived, not q.generation_meta's mutable slot counters (§6) -- a
  // failed paid replace_llm rolls those back to their pre-attempt value, but
  // the ledger (and this) still shows it.
  const { attempts, retries } = slotAttemptCountsByInstance(telemetry, q.instance_id)
  return (
    <Card className="p-4 hebrew-text">
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="font-semibold flex-1">
          {q.number}. {q.question}
        </p>
        <OriginBadge origin={q.origin} />
      </div>
      <div className="space-y-1 text-sm">
        {answers.map((a, i) => (
          <div
            key={i}
            className={`p-2 rounded border ${
              showAnswer && i + 1 === q.correct_answer
                ? 'bg-green-50 border-green-200 text-green-800'
                : 'bg-gray-50 border-gray-200'
            }`}
          >
            <span className="font-medium">{i + 1}.</span> {a}
          </div>
        ))}
      </div>
      {/* historical accuracy/distinction -- 'N/A' when there is no data at
          all (LLM origin, or a never-used DB question); every recorded value
          when the question appeared in more than one exam (§3) */}
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-gray-500">
        <span>דיוק: {formatMeasure(q.accuracy_list, q.accuracy, { percent: true })}</span>
        <span>הבחנה: {formatMeasure(q.distinction_list, q.distinction)}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="hebrew-text"
          onClick={() => setShowAnswer((v) => !v)}
        >
          {showAnswer ? 'הסתר תשובה' : 'הצג תשובה נכונה'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="hebrew-text"
          disabled={disabled}
          onClick={() => onReplaceDb(q.instance_id)}
        >
          {isMutating ? 'מחליף...' : 'החלף בשאלה מהמאגר'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="hebrew-text"
          disabled={disabled}
          onClick={() => onReplaceLlm(q.instance_id)}
        >
          {isMutating ? 'יוצר...' : 'צור שאלה אחרת'}
        </Button>
        {attempts > 0 && (
          <span className="text-xs text-gray-500">
            ניסיונות: {attempts}
            {retries > 0 ? ` · חזרות: ${retries}` : ''}
            {q.generation_meta?.cost_usd
              ? `, עלות: ${formatUSD(q.generation_meta.cost_usd)}`
              : ''}
          </span>
        )}
      </div>
    </Card>
  )
}

// --------------------------------------------------------------------------- //
// main
// --------------------------------------------------------------------------- //
export default function ExamGenerationSection() {
  const [categories, setCategories] = useState([])
  const [readiness, setReadiness] = useState(null)
  const [rows, setRows] = useState({})
  const [ceiling, setCeiling] = useState(DEFAULT_COST_CEILING_USD)

  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')

  const [starting, setStarting] = useState(false)
  const [mutating, setMutating] = useState(null) // instance_id being replaced
  const [retryingSlotId, setRetryingSlotId] = useState(null)
  const [newCeiling, setNewCeiling] = useState('')
  const [raisingCeiling, setRaisingCeiling] = useState(false)
  const [distinctionThreshold, setDistinctionThreshold] = useState(DEFAULT_DISTINCTION_THRESHOLD)

  const startingRef = useRef(false)

  // initial data + resume an active job
  useEffect(() => {
    ;(async () => {
      try {
        const [cats, ready] = await Promise.all([
          api.fetchCategories(),
          api.fetchReadiness().catch(() => null),
        ])
        setCategories(Array.isArray(cats) ? cats : [])
        setReadiness(ready)
      } catch (e) {
        setError(e.message || 'שגיאה בטעינת הנתונים')
      }
      const resumeId = loadActiveJobId()
      if (resumeId) {
        setJobId(resumeId)
        try {
          setJob(await api.fetchJob(resumeId))
        } catch {
          // stale id -> forget it
          saveActiveJobId(null)
          syncJobIdToUrl(null)
          setJobId(null)
        }
      }
    })()
  }, [])

  // polling while the job is queued/running. We only poll once a status is
  // known (set either by the resume fetch or by the optimistic placeholder
  // handleStart installs) so a resumed terminal job never briefly polls.
  useEffect(() => {
    if (!jobId || !job) return undefined
    if (!isPollingStatus(job.status)) return undefined
    let cancelled = false
    const tick = async () => {
      try {
        const v = await api.fetchJob(jobId)
        if (!cancelled) setJob(v)
      } catch {
        /* transient - keep polling */
      }
    }
    const h = setInterval(tick, POLL_MS)
    tick()
    return () => {
      cancelled = true
      clearInterval(h)
    }
  }, [jobId, job?.status])

  const editRow = useCallback((name, field, value) => {
    setRows((prev) => ({
      ...prev,
      [name]: applyRowEdit(prev[name] || emptyRow(), field, value),
    }))
  }, [])

  const availabilityByName = React.useMemo(() => {
    const m = {}
    for (const c of categories) m[c.name] = c.question_count
    return m
  }, [categories])

  const blockers = startBlockers({
    rows,
    availabilityByName,
    ceilingRaw: ceiling,
    readiness,
  })
  const warnings = pricingWarnings(readiness)

  const handleStart = async () => {
    if (startingRef.current || blockers.length) return
    startingRef.current = true
    setStarting(true)
    setError('')
    try {
      const payload = buildCreatePayload(rows, categories, ceiling)
      const res = await api.createJob(payload)
      saveActiveJobId(res.job_id)
      syncJobIdToUrl(res.job_id)
      setJobId(res.job_id)
      // optimistic placeholder so the poller starts immediately
      setJob({
        status: res.status || 'queued',
        questions: [],
        categories: {},
        totals: {},
        warnings: [],
        cost_ceiling_usd: payload.cost_ceiling_usd,
        accumulated_cost_usd: '0',
        remaining_cost_usd: payload.cost_ceiling_usd,
        cost_basis: 'none',
      })
    } catch (e) {
      setError(e.message || 'שגיאה ביצירת המבחן')
    } finally {
      startingRef.current = false
      setStarting(false)
    }
  }

  const refresh = async () => {
    try {
      setJob(await api.fetchJob(jobId))
    } catch (e) {
      setError(e.message || 'שגיאה ברענון')
    }
  }

  const withMutation = async (instanceId, fn) => {
    if (mutating || retryingSlotId || raisingCeiling) return
    setMutating(instanceId)
    setError('')
    try {
      const v = await fn()
      setJob(v) // refresh view from the server response
    } catch (e) {
      setError(e.message || 'הפעולה נכשלה; השאלה הנוכחית נשמרה')
      // keep `job` as-is so the current question stays visible and unchanged
    } finally {
      setMutating(null)
    }
  }

  const handleReplaceDb = (iid) =>
    withMutation(iid, () => api.replaceFromDb(jobId, iid))
  const handleReplaceLlm = (iid) =>
    withMutation(iid, () => api.replaceViaLlm(jobId, iid))

  const handleRetry = async (slotId) => {
    if (mutating || retryingSlotId || raisingCeiling) return
    setRetryingSlotId(slotId)
    setError('')
    try {
      setJob(await api.retrySlot(jobId, slotId))
    } catch (e) {
      setError(e.message || 'ניסיון חוזר נכשל')
    } finally {
      setRetryingSlotId(null)
    }
  }

  const handleRaiseCeiling = async () => {
    const parsed = parseCeiling(newCeiling)
    if (!parsed.valid || raisingCeiling || mutating) return
    setRaisingCeiling(true)
    setError('')
    try {
      setJob(await api.updateCostCeiling(jobId, parsed.value))
      setNewCeiling('')
    } catch (e) {
      setError(e.message || 'עדכון התקרה נכשל')
    } finally {
      setRaisingCeiling(false)
    }
  }

  const handleNewExam = () => {
    saveActiveJobId(null)
    syncJobIdToUrl(null)
    setJobId(null)
    setJob(null)
    setError('')
  }

  const downloadDocx = async (includeAnswers) => {
    try {
      const blob = await api.downloadExamDocx(
        orderQuestions(job.questions),
        includeAnswers,
      )
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
      api.saveBlob(blob, `exam${includeAnswers ? '_answers' : ''}_${ts}.docx`)
    } catch (e) {
      setError(e.message || 'שגיאה בייצוא DOCX')
    }
  }

  const downloadXlsx = async () => {
    try {
      const blob = await api.downloadGeneratedXlsx(jobId)
      api.saveBlob(blob, `generated_questions_${jobId.slice(0, 8)}.xlsx`)
    } catch (e) {
      setError(e.message || 'שגיאה בייצוא Excel')
    }
  }

  const downloadFullXlsx = async () => {
    try {
      const blob = await api.downloadFullExamXlsx(jobId)
      api.saveBlob(blob, `full_exam_${jobId.slice(0, 8)}.xlsx`)
    } catch (e) {
      setError(e.message || 'שגיאה בייצוא Excel')
    }
  }

  // ------------------------------------------------------------------- //
  // render: builder
  // ------------------------------------------------------------------- //
  if (!jobId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">יצירת מבחן</CardTitle>
          <CardDescription className="hebrew-text">
            בחר לכל נושא כמה שאלות בסך הכול, כמה מתוך המאגר וכמה ייוצרו בבינה
            מלאכותית. עריכת סה"כ מחלקת אוטומטית בין השניים; עריכת אחד הצדדים
            מעדכנת את הסה"כ.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {error && (
            <p role="alert" className="hebrew-text text-red-600 bg-red-50 p-3 rounded">
              {error}
            </p>
          )}

          <div className="space-y-2 max-w-xs">
            <label className="hebrew-text font-medium text-sm" htmlFor="cost-ceiling">
              תקרת עלות לכל המבחן (דולר)
            </label>
            <Input
              id="cost-ceiling"
              type="number"
              min="0"
              step="0.01"
              value={ceiling}
              onChange={(e) => setCeiling(e.target.value)}
              className="text-center"
            />
          </div>

          {warnings.length > 0 && (
            <div className="hebrew-text bg-yellow-50 border border-yellow-200 text-yellow-800 p-3 rounded space-y-1">
              {warnings.map((w, i) => (
                <p key={i}>⚠ {w}</p>
              ))}
            </div>
          )}

          <CategoryInputs categories={categories} rows={rows} onEdit={editRow} />

          {blockers.length > 0 && (
            <div
              className="hebrew-text bg-gray-50 border p-3 rounded text-sm text-gray-700 space-y-1"
              data-testid="start-blockers"
            >
              {blockers.map((b, i) => (
                <p key={i}>• {b}</p>
              ))}
            </div>
          )}

          <Button
            className="w-full hebrew-text"
            disabled={starting || blockers.length > 0}
            onClick={handleStart}
          >
            {starting ? 'יוצר מבחן...' : 'צור מבחן'}
          </Button>
        </CardContent>
      </Card>
    )
  }

  // ------------------------------------------------------------------- //
  // render: progress + results
  // ------------------------------------------------------------------- //
  const status = job?.status || 'queued'
  const totals = job?.totals || {}
  const questions = orderQuestions(job?.questions || [])
  const cats = job?.categories || {}
  const tel = job?.attempt_telemetry
  const retryList = retryableSlots(job || {})
  const anyBusy = !!mutating || !!retryingSlotId || raisingCeiling
  // recomputed on every render straight from the current question list, so a
  // failed replacement (which never replaces `job`) leaves it unchanged and a
  // successful one is reflected immediately (§4)
  const stats = overallAnalytics(questions, distinctionThreshold)
  const groups = groupByCategory(questions)

  return (
    <div className="space-y-6">
      {error && (
        <p role="alert" className="hebrew-text text-red-600 bg-red-50 p-3 rounded">
          {error}
        </p>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="hebrew-text flex items-center gap-2">
              מבחן
              <Badge className="hebrew-text" data-testid="job-status">
                {STATUS_LABEL[status] || status}
              </Badge>
            </CardTitle>
            <Button variant="outline" className="hebrew-text" onClick={handleNewExam}>
              צור מבחן חדש
            </Button>
          </div>
          <CardDescription className="hebrew-text" data-testid="job-id">
            מזהה עבודה: {jobId}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="hebrew-text grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div className="p-3 bg-gray-50 rounded">
              <div className="text-gray-500">שאלות שהתקבלו</div>
              <div className="font-semibold" data-testid="accepted-count">
                {questions.length} / {totals.questions_requested ?? '—'}
              </div>
            </div>
            <div className="p-3 bg-gray-50 rounded">
              <div className="text-gray-500">שאלות בינה שהתקבלו</div>
              <div className="font-semibold">
                {totals.llm_accepted ?? 0} / {totals.llm_requested ?? 0}
              </div>
            </div>
            <div className="p-3 bg-gray-50 rounded">
              <div className="text-gray-500">עלות מצטברת</div>
              <div className="font-semibold" data-testid="accumulated-cost">
                {formatUSD(job?.accumulated_cost_usd || 0)} /{' '}
                {formatUSD(job?.cost_ceiling_usd || 0)}
              </div>
              <div className="text-gray-500 text-xs">
                בסיס חישוב: {job?.cost_basis || 'none'}
              </div>
            </div>
            <div className="p-3 bg-gray-50 rounded">
              <div className="text-gray-500">יתרה עד התקרה</div>
              <div className="font-semibold">
                {formatUSD(job?.remaining_cost_usd || 0)}
              </div>
            </div>
          </div>

          {(job?.warnings || []).length > 0 && (
            <div className="hebrew-text bg-yellow-50 border border-yellow-200 text-yellow-800 p-3 rounded space-y-1 text-sm">
              {job.warnings.map((w, i) => (
                <p key={i}>⚠ {w.message || w.code || JSON.stringify(w)}</p>
              ))}
            </div>
          )}

          {/* raise the ceiling, then retry */}
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <label className="hebrew-text text-sm text-gray-600" htmlFor="raise-ceiling">
                העלאת תקרת העלות (דולר)
              </label>
              <Input
                id="raise-ceiling"
                type="number"
                min="0"
                step="0.01"
                value={newCeiling}
                onChange={(e) => setNewCeiling(e.target.value)}
                className="w-32 text-center"
                placeholder={job?.cost_ceiling_usd}
              />
            </div>
            <Button
              variant="outline"
              className="hebrew-text"
              disabled={raisingCeiling || anyBusy || !parseCeiling(newCeiling).valid}
              onClick={handleRaiseCeiling}
            >
              {raisingCeiling ? 'מעדכן...' : 'עדכן תקרה'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* per-category / per-slot progress */}
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">התקדמות לפי נושא</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {Object.entries(cats)
            .sort((a, b) => (a[1].order_index ?? 0) - (b[1].order_index ?? 0))
            .map(([name, cat]) => (
              <div key={name} className="space-y-2">
                <div className="hebrew-text flex items-center gap-3 text-sm">
                  <span className="font-medium">{name}</span>
                  <span className="text-gray-500">
                    ביקשו {cat.total} (מאגר {cat.database} / בינה {cat.llm})
                  </span>
                  <span className="text-green-700">התקבלו {cat.accepted}</span>
                  {cat.failed > 0 && (
                    <span className="text-red-700">נכשלו {cat.failed}</span>
                  )}
                  {cat.pending > 0 && (
                    <span className="text-gray-600">בהמתנה {cat.pending}</span>
                  )}
                </div>
                <SlotChips
                  slots={cat.slots || []}
                  telemetry={tel}
                  onRetry={handleRetry}
                  retryingSlotId={retryingSlotId}
                  mutating={mutating}
                />
              </div>
            ))}
          {retryList.length === 0 && status !== 'completed' && (
            <p className="hebrew-text text-sm text-gray-500">
              אין כרגע משבצות הניתנות לניסיון חוזר.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ledger-derived attempt telemetry */}
      {tel && tel.totals && tel.totals.ledger_entries > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="hebrew-text">ניסיונות ועלויות (מתוך פנקס העלויות)</CardTitle>
            <CardDescription className="hebrew-text">
              נתונים אלה נגזרים מפנקס העלויות בלבד, כך שניסיונות שנכשלו וחויבו
              נשארים ניתנים לאיתור גם אחרי גלגול לאחור.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="hebrew-text text-sm space-y-1" data-testid="telemetry">
              <p>
                סה"כ ניסיונות: {tel.totals.attempts}, מתוכם נכשלו וחויבו:{' '}
                {tel.totals.charged_failed_attempts}, ניסיונות חוזרים:{' '}
                {tel.totals.retries}, החלפות בבינה: {tel.totals.replacements},
                רשומות בפנקס: {tel.totals.ledger_entries}
              </p>
              {Object.entries(tel.by_category).map(([name, c]) => (
                <p key={name} className="text-gray-600">
                  {name}: ניסיונות {c.attempts}, נכשלו וחויבו{' '}
                  {c.charged_failed_attempts}, עלות {formatUSD(c.cost_usd)}
                </p>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* overall exam analytics (§4, recovered legacy contract) */}
      {questions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="hebrew-text">סטטיסטיקות המבחן</CardTitle>
          </CardHeader>
          <CardContent className="hebrew-text space-y-2 text-sm" data-testid="overall-analytics">
            <p>
              דיוק ממוצע:{' '}
              {stats.avgAccuracy != null ? `${stats.avgAccuracy.toFixed(1)}%` : 'N/A'}
            </p>
            <div className="flex items-center gap-2">
              <label className="text-sm" htmlFor="distinction-threshold">
                סף הבחנה:
              </label>
              <input
                id="distinction-threshold"
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={distinctionThreshold}
                onChange={(e) => setDistinctionThreshold(parseFloat(e.target.value))}
                className="flex-1"
              />
              <span className="text-sm min-w-[3rem]">{distinctionThreshold.toFixed(1)}</span>
            </div>
            <p>
              שאלות עם הבחנה גבוהה מ-{distinctionThreshold.toFixed(1)}:{' '}
              {stats.highDistinctionCount} מתוך {stats.totalValidDistinction}
            </p>
          </CardContent>
        </Card>
      )}

      {/* outputs */}
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">ייצוא</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            <Button
              className="hebrew-text"
              disabled={questions.length === 0}
              onClick={() => downloadDocx(false)}
            >
              ייצא מבחן (DOCX)
            </Button>
            <Button
              variant="outline"
              className="hebrew-text"
              disabled={questions.length === 0}
              onClick={() => downloadDocx(true)}
            >
              ייצא דף תשובות (DOCX)
            </Button>
            <Button
              variant="outline"
              className="hebrew-text"
              onClick={downloadXlsx}
            >
              ייצוא שאלות בינה בלבד (Excel)
            </Button>
            <Button
              variant="outline"
              className="hebrew-text"
              disabled={questions.length === 0}
              onClick={downloadFullXlsx}
            >
              ייצוא מבחן מלא (Excel)
            </Button>
          </div>
          <p className="hebrew-text text-xs text-gray-500 mt-2">
            "שאלות בינה בלבד" - לשימוש חוזר/העלאה עתידית למאגר; "מבחן מלא" - כל
            השאלות הנוכחיות בסכימה המלאה. שאלות שנוצרו נשמרות במבחן זה בלבד
            ואינן נוספות למאגר.
          </p>
        </CardContent>
      </Card>

      {/* results, grouped by category (§2) */}
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">שאלות המבחן</CardTitle>
          <CardDescription className="hebrew-text">
            כל שאלה מסומנת כמקורה במאגר או ביצירת בינה מלאכותית. שני הכפתורים
            זמינים בכל שאלה שהתקבלה.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {questions.length === 0 ? (
            <p className="hebrew-text text-gray-500">
              {isPollingStatus(status)
                ? 'עדיין אין שאלות שהתקבלו...'
                : 'לא התקבלו שאלות.'}
            </p>
          ) : (
            groups.map((group) => (
              <div key={group.category} className="space-y-4">
                <h5 className="hebrew-text font-medium text-lg border-b pb-2 text-blue-700">
                  {group.category}
                </h5>
                {group.questions.map((q) => (
                  <ResultQuestion
                    key={q.instance_id}
                    q={q}
                    telemetry={tel}
                    disabled={anyBusy}
                    isMutating={mutating === q.instance_id}
                    onReplaceDb={handleReplaceDb}
                    onReplaceLlm={handleReplaceLlm}
                  />
                ))}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
