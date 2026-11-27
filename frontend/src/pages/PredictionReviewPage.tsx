import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, getLabelDetail, getPredictions, reopenPrediction, reviewPrediction,
  type LabelDetail, type PredictionQueueItem, type PredictionState } from '../api'
import ErrorBanner from '../components/ErrorBanner'
import PredictionReviewCard from '../components/PredictionReviewCard'
import { useDomain } from '../domain'
import { captureOperation } from '../operationContext'

type Origin = 'all' | 'human' | 'prediction'
type Sort = 'text' | 'category' | 'action' | 'confidence' | 'prediction_state' | 'scored_at'

export default function PredictionReviewPage() {
  const { projectId = '' } = useParams()
  const { domainId } = useDomain()
  const navigate = useNavigate()
  const [origin, setOrigin] = useState<Origin>('all')
  const [state, setState] = useState<PredictionState | 'all'>('all')
  const [sortBy, setSortBy] = useState<Sort>('scored_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [items, setItems] = useState<PredictionQueueItem[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState(0)
  const generation = useRef(0)
  const pageSize = 100
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<LabelDetail | null>(null)
  const detailGeneration = useRef(0)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    if (!projectId) return
    const operation = captureOperation(domainId, projectId)
    const request = ++generation.current
    setLoading(true); setError(null)
    try {
      const result = await getPredictions(projectId, {
        origin, prediction_state: origin === 'human' || state === 'all' ? undefined : state,
        sort_by: sortBy, sort_order: sortOrder, limit: pageSize, offset,
      }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent() || request !== generation.current) return
      setItems(result.items)
      setTotal(result.total)
      if (!result.items.length && offset > 0) setOffset(Math.max(0, offset - pageSize))
      setSelected(current => result.items.some(row => row.origin === 'prediction' && row.id === current) ? current : null)
    } catch (cause) {
      if (operation.isCurrent() && request === generation.current) { setItems([]); setError(String(cause)) }
    } finally {
      if (operation.isCurrent() && request === generation.current) setLoading(false)
      operation.finish()
    }
  }, [domainId, origin, projectId, offset, sortBy, sortOrder, state])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const clear = () => { setItems([]); setSelected(null); setError(null) }
    window.addEventListener('dlj-account-changing', clear)
    return () => window.removeEventListener('dlj-account-changing', clear)
  }, [])
  const predictions = items.filter(item => item.origin === 'prediction')
  const selectedItem = predictions.find(item => item.id === selected) ?? null
  useEffect(() => {
    const request = ++detailGeneration.current
    setSelectedDetail(null)
    if (!selectedItem || selectedItem.media_kind !== 'image') return
    const operation = captureOperation(domainId, projectId)
    void getLabelDetail(domainId, selectedItem.label_id, operation.signal, projectId, operation.credential ?? undefined)
      .then(detail => { if (operation.isCurrent() && request === detailGeneration.current) setSelectedDetail(detail) })
      .catch(() => undefined)
      .finally(operation.finish)
    return operation.finish
  }, [domainId, projectId, selectedItem])
  const index = selectedItem ? predictions.indexOf(selectedItem) : -1
  const move = (delta: number) => {
    if (!predictions.length) return
    const next = Math.max(0, Math.min(predictions.length - 1, (index < 0 ? 0 : index) + delta))
    setSelected(predictions[next].id)
  }
  const mutate = async (kind: 'accept' | 'correct' | 'reopen', spansReviewed = false, category?: string, actualAction?: string) => {
    if (!selectedItem || busy) return
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null); setNotice('')
    try {
      if (kind === 'reopen') await reopenPrediction(projectId, selectedItem.id, {
        expected_revision: selectedItem.current_label_log_id, decision_version: selectedItem.decision_version,
      }, operation.credential ?? undefined, operation.signal)
      else await reviewPrediction(projectId, selectedItem.id, {
        action: kind, category, actual_action: actualAction,
        expected_revision: selectedItem.current_label_log_id, decision_version: selectedItem.decision_version,
        human_spans_reviewed: spansReviewed,
      }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      setNotice(kind === 'accept' ? 'Prediction accepted.' : kind === 'correct' ? 'Correction recorded.' : 'Prediction reopened.')
      const nextId = predictions[index + 1]?.id ?? null
      await load()
      if (operation.isCurrent()) setSelected(nextId)
    } catch (cause) {
      if (operation.isCurrent()) setError(cause instanceof ApiError && cause.status === 409 ?
        'This prediction changed elsewhere. The queue has been refreshed.' : String(cause))
      if (operation.isCurrent() && cause instanceof ApiError && cause.status === 409) await load()
    } finally { operation.finish(); setBusy(false) }
  }
  const rows = items.map(item => item.origin === 'prediction' ?
    { kind: item.origin, key: item.id, text: item.text, category: item.category, action: item.action,
      confidence: item.dlj_confidence, state: item.prediction_state, scored: item.scored_at, media: item.media_kind } :
    { kind: item.origin, key: item.label_id, text: item.text_preview, category: item.category,
      action: item.recommended_action, confidence: item.confidence, state: 'human', scored: item.scored_at, media: item.media_kind })
  const sort = (field: Sort) => { setOffset(0); if (sortBy === field) setSortOrder(value => value === 'asc' ? 'desc' : 'asc'); else { setSortBy(field); setSortOrder('asc') } }
  return <div className="page"><div className="eyebrow">Project review</div><h1>Prediction review</h1>
    <p className="subtitle">Compare model provenance with DLJ confidence, then accept, correct, or reopen.</p>
    <ErrorBanner message={error} />{notice && <p className="success" role="status">{notice}</p>}
    <div className="toolbar card card-pad"><label className="field">Origin<select value={origin} onChange={event => { setOffset(0); setOrigin(event.target.value as Origin); setSelected(null) }}><option value="all">All</option><option value="human">Human</option><option value="prediction">Prediction</option></select></label>
      <label className="field">Prediction state<select value={state} disabled={origin === 'human'} onChange={event => { setOffset(0); setState(event.target.value as typeof state); setSelected(null) }}><option value="all">All</option><option value="pending_review">Pending review</option><option value="accepted">Accepted</option><option value="corrected">Corrected</option><option value="unknown">Unknown assessment</option><option value="reopened">Reopened</option></select></label></div>
    {loading ? <div className="loading"><span className="spinner" />Loading review queue…</div> : <div className="card table-wrap"><table className="table"><thead><tr>
      {([['text', 'Item text'], ['category', 'Category'], ['action', 'Action'], ['confidence', 'Confidence'], ['prediction_state', 'State'], ['scored_at', 'Scored']] as [Sort, string][]).map(([field, label]) => <th key={field}><button className="table-sort" onClick={() => sort(field)}>{label}{sortBy === field ? ` ${sortOrder === 'asc' ? '↑' : '↓'}` : ''}</button></th>)}</tr></thead><tbody>
      {rows.map(row => <tr key={`${row.kind}:${row.key}`} onClick={() => row.kind === 'prediction' ? setSelected(row.key) : navigate(`/projects/${encodeURIComponent(projectId)}/review/${encodeURIComponent(row.key)}`)}>
        <td className="preview-cell">{row.media === 'image' && <span className="pill media-badge">Image</span>}{row.text?.slice(0, 120) || (row.media === 'image' ? 'Image' : '—')}</td><td>{row.category ?? '—'}</td><td>{row.action ?? '—'}</td><td>{Math.round(row.confidence * 100)}%</td><td><span className="pill">{row.kind === 'human' ? 'human' : row.state.replace('_', ' ')}</span></td><td>{row.scored ? new Date(row.scored).toLocaleString() : '—'}</td></tr>)}
      {!rows.length && <tr><td colSpan={6} className="muted">No items match these filters.</td></tr>}</tbody></table></div>}
    <div className="button-row"><button disabled={loading || offset === 0} onClick={() => setOffset(offset - pageSize)}>Previous page</button>
      <span>{total ? offset + 1 : 0}–{Math.min(offset + pageSize, total)} of {total}</span>
      <button disabled={loading || offset + pageSize >= total} onClick={() => setOffset(offset + pageSize)}>Next page</button></div>
    {selectedItem && <div className="prediction-overlay"><PredictionReviewCard key={selectedItem.current_label_log_id} item={{ ...selectedItem,
      text: selectedDetail?.text ?? selectedItem.text, content: selectedDetail?.content ?? selectedItem.content }} busy={busy}
      onAccept={checked => void mutate('accept', checked)} onCorrect={(category, action, checked) => void mutate('correct', checked, category, action)}
      onReopen={() => void mutate('reopen')} onNext={() => move(1)} onPrevious={() => move(-1)} onClose={() => setSelected(null)} /></div>}
  </div>
}
