import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, getAutonomy, getGuidelines, getLabelDetail, getPending, relabelItem, verifyLabel, type LabelDetail, type NerSpan, type PendingLabel, type TierStatus } from '../api'
import GuidelinesPanel from '../components/GuidelinesPanel'
import { useDomain } from '../domain'
import ConfidenceIndicator from '../components/ConfidenceIndicator'
import ErrorBanner from '../components/ErrorBanner'
import FactorBar from '../components/FactorBar'
import LoadingSpinner from '../components/LoadingSpinner'
import TierBadge from '../components/TierBadge'
import TextViewer from '../components/TextViewer'
import CategorySelector from '../components/CategorySelector'
import NEREditor from '../components/NEREditor'
import TagSelector from '../components/TagSelector'
import ImageViewer from '../components/ImageViewer'

export default function ReviewCard() {
  const { domainId } = useDomain()
  const { labelId } = useParams()
  const currentDomain = useRef(domainId)
  currentDomain.current = domainId
  const navigate = useNavigate()
  const [item, setItem] = useState<LabelDetail | null>(null)
  const [loadedDomain, setLoadedDomain] = useState('')
  const [pending, setPending] = useState<PendingLabel[]>([])
  const [tier, setTier] = useState<TierStatus | null>(null)
  const [entityTypes, setEntityTypes] = useState<string[]>([])
  const [editedSpans, setEditedSpans] = useState<NerSpan[]>([])
  const [editedTags, setEditedTags] = useState<string[]>([])
  const [outcome, setOutcome] = useState<'' | 'correct' | 'incorrect'>('')
  const [override, setOverride] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [showGuidelines, setShowGuidelines] = useState(false)
  const [guidelines, setGuidelines] = useState<string | null>(null)
  useEffect(() => {
    if (!domainId) { setGuidelines(null); return }
    let live = true
    getGuidelines(domainId).then(result => { if (live) setGuidelines(result.guidelines) })
      .catch(() => { if (live) setGuidelines(null) })
    return () => { live = false }
  }, [domainId])
  useEffect(() => { setOutcome(''); setOverride(''); setMessage(''); setItem(null); setEditedSpans([]); setEditedTags([]); setLoadedDomain('') }, [domainId, labelId])
  const load = useCallback(async () => {
    if (!domainId) return
    setBusy(true); setError(null)
    try {
      const [detail, rows, autonomy] = await Promise.all([
        getLabelDetail(domainId, labelId ?? ''), getPending(domainId, { limit: 200 }), getAutonomy(domainId),
      ])
      if (currentDomain.current !== domainId) return
      setPending(rows)
      setItem(detail)
      setEditedSpans(detail.content?.content_type === 'text_ner' ? detail.content.spans : [])
      setEditedTags(detail.content?.content_type === 'text_multilabel' ? detail.content.tags : [])
      setEntityTypes(autonomy.categories.map(status => status.category))
      setLoadedDomain(domainId)
      setTier(autonomy.categories.find(status => status.category === detail.category) ?? null)
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }, [domainId, labelId])
  useEffect(() => { void load() }, [load])
  const spansDirty = item !== null && JSON.stringify(editedSpans) !==
    JSON.stringify(item.content?.content_type === 'text_ner' ? item.content.spans : [])
  const tagsDirty = item !== null && JSON.stringify(editedTags) !==
    JSON.stringify(item.content?.content_type === 'text_multilabel' ? item.content.tags : [])
  const saveSpans = async () => {
    if (!item || !domainId || !item.category || item.verified_at || !spansDirty || busy) return
    setBusy(true); setError(null); setMessage('')
    try {
      await relabelItem(domainId, item.label_id, {
        category: item.category, idempotency_token: item.revision_id, spans: editedSpans,
      })
      await load()
      setMessage('Spans saved.')
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await load()
        setError('This label changed. Review the latest spans before editing again.')
      } else setError(String(cause))
    } finally { setBusy(false) }
  }
  const saveTags = async () => {
    if (!item || !domainId || !item.category || item.verified_at || !tagsDirty || busy) return
    setBusy(true); setError(null); setMessage('')
    try {
      await relabelItem(domainId, item.label_id, {
        category: item.category, idempotency_token: item.revision_id, tags: editedTags,
      })
      await load()
      setMessage('Tags saved.')
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await load()
        setError('This label changed. Review the latest tags before editing again.')
      } else setError(String(cause))
    } finally { setBusy(false) }
  }
  const submit = async (action: string) => {
    if (!item || !domainId || item.verified_at || item.status !== 'scored') return
    if (domainId !== loadedDomain) { setError('Domain changed. Please reload.'); return }
    if (busy) return
    if (!outcome) { setError('Select the verified ground-truth outcome before reviewing.'); return }
    setBusy(true); setError(null)
    try {
      await verifyLabel({ domain_id: domainId, label_id: item.label_id, actual_action: action, verified_outcome: outcome === 'correct' })
      setMessage(`Verified ${item.label_id}.`)
      const next = pending.find(row => row.label_id !== item.label_id)
      if (next) navigate(`/review/${encodeURIComponent(next.label_id)}`, { replace: true, state: { label: next, domainId } })
      else navigate('/queue', { replace: true })
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        await load()
        setError('This label has changed. Review its current status before continuing.')
      } else setError(String(cause))
    } finally { setBusy(false) }
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (item?.verified_at || item?.status !== 'scored' || event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement ||
          (event.target instanceof HTMLElement && event.target.isContentEditable) ||
          event.metaKey || event.ctrlKey || event.altKey) return
      if (event.key.toLowerCase() === 'a') void submit(item?.recommended_action ?? '')
      if (event.key.toLowerCase() === 'o' && override) void submit(override)
      if (event.key.toLowerCase() === 'e') setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')
    }
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler)
  })
  const alternatives = ['approve', 'reject'].filter(action => action !== item?.recommended_action)
  return <div className="page"><div className="eyebrow">03 / Verification</div><h1>Review label</h1><p className="subtitle">Confirm or correct the recommended action using a known ground-truth outcome.</p>
    <button className="button secondary" aria-expanded={showGuidelines} onClick={() => setShowGuidelines(value => !value)}>Guidelines</button>
    {showGuidelines && <GuidelinesPanel guidelines={guidelines} />}
    <ErrorBanner message={error} />{message && <div className="notice">{message}</div>}{busy && !item && <LoadingSpinner />}
    {item && loadedDomain === domainId ? <div className="grid-2"><div className="card card-pad"><div className="eyebrow">Label</div><h2 style={{ margin: '10px 0 3px' }}>{item.label_id}</h2><p className="muted">{item.category ?? 'Pending classification'} · Annotator {item.annotator_id ?? 'unknown'}</p>
      {item.content?.content_type === 'image_classification' && item.content.image_url && <ImageViewer imageUrl={item.content.image_url} category={item.category} readOnly />}
      {item.content?.content_type !== 'image_classification' && <TextViewer text={item.text} />}
      {item.text !== null && (item.content === null || item.content.content_type === 'text_ner') && <><NEREditor key={item.revision_id} text={item.text} spans={editedSpans} entityTypes={entityTypes} onSpansChange={setEditedSpans} readOnly={Boolean(item.verified_at)} />{!item.verified_at && <div className="button-row" style={{ marginTop: 12 }}>{spansDirty && <span className="muted" role="status">Unsaved changes</span>}<button className="button secondary" onClick={() => void saveSpans()} disabled={busy || !spansDirty || !item.category}>Save Spans</button>{!item.category && <span className="muted">Choose a category before saving spans.</span>}</div>}</>}
      {item.content?.content_type === 'text_multilabel' && <><TagSelector key={item.revision_id} tags={editedTags} availableTags={[...entityTypes, ...item.content.tags]} onTagsChange={setEditedTags} readOnly={Boolean(item.verified_at)} />{!item.verified_at && <div className="button-row" style={{ marginTop: 12 }}>{tagsDirty && <span className="muted" role="status">Unsaved changes</span>}<button className="button secondary" onClick={() => void saveTags()} disabled={busy || !tagsDirty || !item.category}>Save Tags</button></div>}</>}
      {(item.text !== null || item.content?.content_type === 'image_classification') && !spansDirty && !tagsDirty && <CategorySelector domainId={domainId} labelId={item.label_id} revisionId={item.revision_id} category={item.category} previousCategory={item.previous_category} onSaved={load} />}
      <hr style={{ border: 0, borderTop: '1px solid #e7ecf2', margin: '22px 0' }} /><h3 className="section-title">Factor signals</h3>{Object.entries(item.factors).map(([factor, value]) => <FactorBar key={factor} factor={factor} value={value} />)}</div>
      <div className="stack">{item.status === 'scored' && item.confidence !== null && <div className="card card-pad"><div className="eyebrow">JM recommendation</div><h2 style={{ textTransform: 'capitalize' }}>{item.recommended_action}</h2><ConfidenceIndicator value={item.confidence} /><div className="button-row" style={{ marginTop: 20 }}>{tier && <TierBadge tier={tier.tier} />}<span className="muted">Conservation: {tier?.conservation_reason ?? (tier?.conservation_gate_pass ? 'clear' : 'unknown')}</span></div></div>}
        {item.status !== 'scored' ? <div className="card card-pad"><h3 className="section-title">Pending classification</h3><p className="muted">Choose a category before verification.</p></div> : item.verified_at ? <div className="card card-pad"><h3 className="section-title">Already reviewed</h3><p className="muted">Verified outcome: {item.verified_outcome ? 'Correct' : 'Incorrect'} · Action: {item.actual_action ?? 'unknown'}</p></div> :
          <div className="card card-pad"><h3 className="section-title">Your verification</h3><p className="muted">Outcome means whether the label was correct against ground truth. Approval alone does not establish correctness.</p><label className="field">Known outcome<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}><option value="">Select outcome…</option><option value="correct">Correct</option><option value="incorrect">Incorrect</option></select></label><div className="button-row" style={{ marginTop: 18 }}><button className="button" disabled={busy || !outcome || !item.recommended_action} onClick={() => void submit(item.recommended_action ?? '')}>Approve recommendation (A)</button><select className="select" aria-label="Override action" value={override} onChange={event => setOverride(event.target.value)}><option value="">Choose override…</option>{alternatives.map(value => <option key={value}>{value}</option>)}</select><button className="button amber" disabled={busy || !outcome || !override} onClick={() => void submit(override)}>Override (O)</button><button className="button danger" onClick={() => setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')}>Escalate (E)</button></div></div>}
      </div></div> : !busy && <div className="card card-pad">Label not found. <button className="button secondary" onClick={() => navigate('/queue')}>Back to queue</button></div>}
  </div>
}
