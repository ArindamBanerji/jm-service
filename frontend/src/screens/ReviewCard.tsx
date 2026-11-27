import { useCallback, useEffect, useRef, useState } from 'react'
import { useBlocker, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, getAutonomy, getGuidelines, getLabelDetail, getNextBatch, getPending, relabelItem, verifyLabel, type LabelDetail, type NerSpan, type PendingLabel, type TierStatus } from '../api'
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
import { captureOperation, type OperationContext } from '../operationContext'

export default function ReviewCard() {
  const { domainId, projectId } = useDomain()
  const path = (page: string) => `${projectId ? `/projects/${encodeURIComponent(projectId)}` : ''}/${page}`
  const { labelId } = useParams()
  const smartReview = new URLSearchParams(useLocation().search).get('queue') === 'smart'
  const currentRoute = useRef({ domainId, labelId })
  currentRoute.current = { domainId, labelId }
  const loadController = useRef<AbortController | null>(null)
  const preserveTagInputFor = useRef<{ domainId: string; labelId: string } | null>(null)
  const preserveDraft = useRef(false)
  const allowSavedNavigation = useRef(false)
  const draftToPreserve = useRef<{ domainId: string; sourceLabelId: string; expectedLabelId?: string;
    tagInput: string; tags: string[]; spans: NerSpan[];
    tagsDirty: boolean; spansDirty: boolean } | null>(null)
  const navigate = useNavigate()
  const [item, setItem] = useState<LabelDetail | null>(null)
  const [loadedDomain, setLoadedDomain] = useState('')
  const [pending, setPending] = useState<PendingLabel[]>([])
  const [tier, setTier] = useState<TierStatus | null>(null)
  const [entityTypes, setEntityTypes] = useState<string[]>([])
  const [editedSpans, setEditedSpans] = useState<NerSpan[]>([])
  const [editedTags, setEditedTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [outcome, setOutcome] = useState<'' | 'correct' | 'incorrect'>('')
  const [override, setOverride] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [isMutating, setIsMutating] = useState(false)
  const mutationLock = useRef(false)
  const mutationOwner = useRef<OperationContext | null>(null)
  const [categoryDirty, setCategoryDirty] = useState(false)
  const startMutation = () => {
    if (mutationLock.current) return false
    mutationLock.current = true
    mutationOwner.current = captureOperation(domainId, projectId)
    loadController.current?.abort()
    setIsMutating(true)
    return true
  }
  const endMutation = () => { mutationOwner.current?.finish(); mutationOwner.current = null; mutationLock.current = false; setIsMutating(false) }
  const [showGuidelines, setShowGuidelines] = useState(false)
  const [guidelines, setGuidelines] = useState<string | null>(null)
  useEffect(() => {
    allowSavedNavigation.current = false
    setGuidelines(null)
    if (!domainId) return
    const owner = captureOperation(domainId, projectId)
    getGuidelines(domainId, owner.signal, projectId, owner.credential ?? undefined)
      .then(result => { if (owner.isCurrent()) setGuidelines(result.guidelines) })
      .catch(() => { if (owner.isCurrent()) setGuidelines(null) })
      .finally(owner.finish)
    return owner.finish
  }, [domainId, projectId])
  useEffect(() => {
    const draft = draftToPreserve.current
    const keepingDraft = preserveDraft.current && draft?.domainId === domainId &&
      (draft.sourceLabelId === labelId || draft.expectedLabelId === labelId)
    if (!keepingDraft) {
      preserveDraft.current = false
      draftToPreserve.current = null
      if (preserveTagInputFor.current?.domainId === domainId && preserveTagInputFor.current.labelId === labelId) preserveTagInputFor.current = null
      else setTagInput('')
      setEditedSpans([]); setEditedTags([]); setCategoryDirty(false)
    }
    setOutcome(''); setOverride(''); setNote(''); setMessage(''); setItem(null); setLoadedDomain(''); setPending([]); setTier(null)
  }, [domainId, projectId, labelId])
  const load = useCallback(async () => {
    loadController.current?.abort()
    const controller = new AbortController()
    const operation = captureOperation(domainId, projectId)
    operation.signal.addEventListener('abort', () => controller.abort(), { once: true })
    loadController.current = controller
    if (!domainId || !labelId) { setBusy(false); operation.finish(); return }
    setBusy(true); setError(null)
    try {
      const [detail, rows, autonomy] = await Promise.all([
        getLabelDetail(domainId, labelId, controller.signal, projectId, operation.credential ?? undefined), getPending(domainId, { limit: 200 }, controller.signal, projectId, operation.credential ?? undefined), getAutonomy(domainId, controller.signal, projectId, operation.credential ?? undefined),
      ])
      if (controller.signal.aborted || !operation.isCurrent() || currentRoute.current.domainId !== domainId || currentRoute.current.labelId !== labelId) return
      if (detail.label_id !== currentRoute.current.labelId) {
        if (preserveDraft.current && draftToPreserve.current?.domainId === domainId &&
            draftToPreserve.current.sourceLabelId === labelId)
          draftToPreserve.current.expectedLabelId = detail.label_id
        navigate(path(`review/${encodeURIComponent(detail.label_id)}`), { replace: true })
        return
      }
      setPending(rows)
      setItem(detail)
      setNote(detail.review_notes ?? '')
      const savedDraft = preserveDraft.current && draftToPreserve.current?.domainId === domainId &&
        (draftToPreserve.current.sourceLabelId === labelId || draftToPreserve.current.expectedLabelId === labelId)
        ? draftToPreserve.current : null
      setEditedSpans(savedDraft?.spansDirty ? savedDraft.spans :
        detail.content?.content_type === 'text_ner' ? detail.content.spans : [])
      setEditedTags(savedDraft?.tagsDirty ? savedDraft.tags :
        detail.content?.content_type === 'text_multilabel' ? detail.content.tags : [])
      if (savedDraft) {
        setTagInput(savedDraft.tagInput)
        preserveDraft.current = false
        draftToPreserve.current = null
      }
      setEntityTypes(autonomy.categories.map(status => status.category))
      setLoadedDomain(domainId)
      setTier(autonomy.categories.find(status => status.category === detail.category) ?? null)
    } catch (cause) { if (!controller.signal.aborted && currentRoute.current.labelId === labelId && currentRoute.current.domainId === domainId) setError(String(cause)) }
    finally { if (!controller.signal.aborted && currentRoute.current.labelId === labelId && currentRoute.current.domainId === domainId) setBusy(false); operation.finish() }
  }, [domainId, projectId, labelId, navigate])
  useEffect(() => { void load(); return () => loadController.current?.abort() }, [load])
  const spansDirty = item !== null && JSON.stringify(editedSpans) !==
    JSON.stringify(item.content?.content_type === 'text_ner' ? item.content.spans : [])
  const tagsDirty = item !== null && JSON.stringify(editedTags) !==
    JSON.stringify(item.content?.content_type === 'text_multilabel' ? item.content.tags : [])
  const contentUnsaved = spansDirty || tagsDirty || categoryDirty || Boolean(tagInput.trim())
  const noteDirty = item !== null && note !== (item.review_notes ?? '')
  const hasUnsavedEdits = contentUnsaved || noteDirty
  const blocker = useBlocker(({ nextLocation }) => {
    if (!hasUnsavedEdits || allowSavedNavigation.current) return false
    const successor = draftToPreserve.current?.expectedLabelId
    return !successor || nextLocation.pathname !== path(`review/${encodeURIComponent(successor)}`)
  })
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm('Unsaved changes — discard?')) blocker.proceed()
    else blocker.reset()
  }, [blocker])
  useEffect(() => {
    if (!hasUnsavedEdits) return
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const beforeProject = (event: Event) => {
      if (event.cancelable && !window.confirm('Unsaved changes — discard?')) event.preventDefault()
    }
    window.addEventListener('beforeunload', beforeUnload)
    window.addEventListener('dlj-before-project-change', beforeProject)
    return () => {
      window.removeEventListener('beforeunload', beforeUnload)
      window.removeEventListener('dlj-before-project-change', beforeProject)
    }
  }, [hasUnsavedEdits])
  useEffect(() => {
    const clear = () => {
      loadController.current?.abort(); mutationOwner.current?.finish()
      preserveDraft.current = false; draftToPreserve.current = null
      setItem(null); setEditedSpans([]); setEditedTags([]); setTagInput(''); setNote(''); setCategoryDirty(false)
    }
    window.addEventListener('dlj-account-changing', clear)
    return () => window.removeEventListener('dlj-account-changing', clear)
  }, [])
  const keepDraft = (expectedLabelId?: string, savedSpans = false, savedTags = false) => {
    preserveDraft.current = true
    draftToPreserve.current = { domainId, sourceLabelId: labelId ?? '', expectedLabelId,
      tagInput, tags: editedTags, spans: editedSpans,
      tagsDirty: tagsDirty && !savedTags, spansDirty: spansDirty && !savedSpans }
  }
  const saveSpans = async () => {
    if (!item || !domainId || item.label_id !== labelId || !item.category || item.verified_at || !spansDirty || busy || !startMutation()) return
    setBusy(true); setError(null); setMessage('')
    try {
      const owner = mutationOwner.current
      const result = await relabelItem(domainId, labelId, {
        category: item.category, idempotency_token: item.revision_id, spans: editedSpans,
      }, owner?.credential ?? undefined, owner?.signal, projectId)
      if (!owner?.isCurrent() || currentRoute.current.domainId !== domainId || currentRoute.current.labelId !== labelId) return
      keepDraft(result.label_id !== labelId ? result.label_id : undefined, true)
      if (result.label_id !== labelId) navigate(path(`review/${encodeURIComponent(result.label_id)}`), { replace: true })
      else { await load(); setMessage('Spans saved.') }
    } catch (cause) {
      if (mutationOwner.current?.isCurrent() && cause instanceof ApiError && cause.status === 409) {
        keepDraft()
        await load()
        setError('This label changed. Review the latest spans before editing again.')
      } else if (mutationOwner.current?.isCurrent()) setError(String(cause))
    } finally { endMutation(); setBusy(false) }
  }
  const saveTags = async () => {
    if (!item || !domainId || item.label_id !== labelId || !item.category || item.verified_at || !tagsDirty || busy || !startMutation()) return
    setBusy(true); setError(null); setMessage('')
    try {
      const owner = mutationOwner.current
      const result = await relabelItem(domainId, labelId, {
        category: item.category, idempotency_token: item.revision_id, tags: editedTags,
      }, owner?.credential ?? undefined, owner?.signal, projectId)
      if (!owner?.isCurrent() || currentRoute.current.domainId !== domainId || currentRoute.current.labelId !== labelId) return
      keepDraft(result.label_id !== labelId ? result.label_id : undefined, false, true)
      if (result.label_id !== labelId) { preserveTagInputFor.current = { domainId, labelId: result.label_id }; navigate(path(`review/${encodeURIComponent(result.label_id)}`), { replace: true }) }
      else { await load(); setMessage('Tags saved.') }
    } catch (cause) {
      if (mutationOwner.current?.isCurrent() && cause instanceof ApiError && cause.status === 409) {
        keepDraft()
        await load()
        setError('This label changed. Review the latest tags before editing again.')
      } else if (mutationOwner.current?.isCurrent()) setError(String(cause))
    } finally { endMutation(); setBusy(false) }
  }
  const submit = async (action: string) => {
    if (!item || !domainId || !labelId || item.verified_at || item.status !== 'scored') return
    if (item.label_id !== labelId) { setError('Label data is stale, please refresh.'); return }
    if (domainId !== loadedDomain) { setError('Domain changed. Please reload.'); return }
    if (contentUnsaved) { setMessage('Save changes before approving'); return }
    if (busy || mutationLock.current) return
    if (!outcome) { setError('Select the verified ground-truth outcome before reviewing.'); return }
    if (!startMutation()) return
    setBusy(true); setError(null)
    try {
      const owner = mutationOwner.current
      await verifyLabel({ domain_id: domainId, label_id: labelId, actual_action: action,
        verified_outcome: outcome === 'correct', notes: note.trim() || undefined }, owner?.credential ?? undefined, owner?.signal, projectId)
      if (!owner?.isCurrent() || currentRoute.current.domainId !== domainId || currentRoute.current.labelId !== labelId) return
      allowSavedNavigation.current = true
      setMessage(`Verified ${labelId}.`)
      if (smartReview && projectId) {
        // The verification can change centroid ordering. Fetch the next priority after commit.
        try {
          const batch = await getNextBatch(projectId, 1, owner.credential ?? undefined, owner.signal)
          if (owner.isCurrent()) navigate(batch.items.length
            ? path(`review/${encodeURIComponent(batch.items[0].id)}?queue=smart`) : path('queue'), { replace: true })
        } catch { if (owner.isCurrent()) navigate(path('queue'), { replace: true }) }
        return
      }
      const next = pending.find(row => row.label_id !== labelId)
      if (next) navigate(path(`review/${encodeURIComponent(next.label_id)}`), { replace: true })
      else navigate(path('queue'), { replace: true })
    } catch (cause) {
      if (mutationOwner.current?.isCurrent() && cause instanceof ApiError && cause.status === 409) {
        await load()
        setError('This label has changed. Review its current status before continuing.')
      } else if (mutationOwner.current?.isCurrent()) setError(String(cause))
    } finally { endMutation(); setBusy(false) }
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (item?.verified_at || item?.status !== 'scored' || event.target instanceof HTMLInputElement ||
          event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement ||
          (event.target instanceof HTMLElement && event.target.isContentEditable) ||
          event.metaKey || event.ctrlKey || event.altKey) return
      if (contentUnsaved && ['a', 'o', 'e'].includes(event.key.toLowerCase())) {
        setMessage('Save changes before approving')
        return
      }
      if (event.key.toLowerCase() === 'a') void submit(item?.recommended_action ?? '')
      if (event.key.toLowerCase() === 'o' && override) void submit(override)
      if (event.key.toLowerCase() === 'e') setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')
    }
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler)
  })
  const alternatives = ['approve', 'reject'].filter(action => action !== item?.recommended_action)
  const afterCategorySaved = async (newLabelId: string) => {
    if (currentRoute.current.domainId !== domainId || currentRoute.current.labelId !== labelId) return
    if (!mutationOwner.current?.isCurrent()) return
    keepDraft(newLabelId !== labelId ? newLabelId : undefined)
    setCategoryDirty(false)
    if (newLabelId !== labelId) { preserveTagInputFor.current = { domainId, labelId: newLabelId }; navigate(path(`review/${encodeURIComponent(newLabelId)}`), { replace: true }) }
    else await load()
  }
  return <div className="page"><div className="eyebrow">03 / Verification</div><h1>Review label</h1><p className="subtitle">Confirm or correct the recommended action using a known ground-truth outcome.</p>
    <button className="button secondary" aria-expanded={showGuidelines} onClick={() => setShowGuidelines(value => !value)}>Guidelines</button>
    {showGuidelines && <GuidelinesPanel guidelines={guidelines} />}
    <ErrorBanner message={error} />{message && <div className="notice" role="status">{message}</div>}{busy && !item && <LoadingSpinner />}
    {item && loadedDomain === domainId && item.label_id === labelId ? <div className="grid-2"><div className="card card-pad"><div className="eyebrow">Label</div><h2 style={{ margin: '10px 0 3px' }}>{item.label_id}</h2><p className="muted">{item.category ?? 'Pending classification'} · Annotator {item.annotator_id ?? 'unknown'}</p>
      {item.notes && <div className="label-note"><strong>Annotator note</strong><p>{item.notes}</p></div>}
      {item.content?.content_type === 'image_classification' && item.content.image_url && <ImageViewer
        key={`${item.revision_id}:${item.content.image_url}`} imageUrl={item.content.image_url}
        altText={item.text || `Image label ${item.label_id}`} category={item.category} readOnly />}
      {item.content?.content_type !== 'image_classification' && <TextViewer text={item.text} />}
       {item.text !== null && (item.content === null || item.content.content_type === 'text_ner') && <><NEREditor key={item.revision_id} text={item.text} spans={editedSpans} entityTypes={entityTypes} onSpansChange={setEditedSpans} disabled={isMutating || categoryDirty} readOnly={Boolean(item.verified_at)} />{!item.verified_at && <div className="button-row" style={{ marginTop: 12 }}>{spansDirty && <span className="muted" role="status">Unsaved changes</span>}<button className="button secondary" onClick={() => void saveSpans()} disabled={busy || isMutating || !spansDirty || !item.category}>Save Spans</button>{!item.category && <span className="muted">Choose a category before saving spans.</span>}</div>}</>}
       {item.content?.content_type === 'text_multilabel' && <><TagSelector key={item.revision_id} tags={editedTags} availableTags={[...entityTypes, ...item.content.tags]} onTagsChange={setEditedTags} input={tagInput} onInputChange={setTagInput} disabled={isMutating || categoryDirty} readOnly={Boolean(item.verified_at)} />{!item.verified_at && <div className="button-row" style={{ marginTop: 12 }}>{tagsDirty && <span className="muted" role="status">Unsaved changes</span>}<button className="button secondary" onClick={() => void saveTags()} disabled={busy || isMutating || !tagsDirty || !item.category}>Save Tags</button></div>}</>}
       {(item.text !== null || item.content?.content_type === 'image_classification') && !spansDirty && !tagsDirty && <CategorySelector domainId={domainId} projectId={projectId} labelId={labelId} revisionId={item.revision_id} category={item.category} previousCategory={item.previous_category} onSaved={afterCategorySaved} disabled={isMutating || busy} onDraftChange={setCategoryDirty} operation={() => mutationOwner.current} onSavingChange={saving => saving ? startMutation() : endMutation()} />}
      <hr style={{ border: 0, borderTop: '1px solid #e7ecf2', margin: '22px 0' }} /><h3 className="section-title">Factor signals</h3>{Object.entries(item.factors).map(([factor, value]) => <FactorBar key={factor} factor={factor} value={value} />)}</div>
      <div className="stack">{item.status === 'scored' && item.confidence !== null && <div className="card card-pad"><div className="eyebrow">JM recommendation</div><h2 style={{ textTransform: 'capitalize' }}>{item.recommended_action}</h2><ConfidenceIndicator value={item.confidence} /><div className="button-row" style={{ marginTop: 20 }}>{tier && <TierBadge tier={tier.tier} />}<span className="muted">Conservation: {tier?.conservation_reason ?? (tier?.conservation_gate_pass ? 'clear' : 'unknown')}</span></div></div>}
        {item.status !== 'scored' ? <div className="card card-pad"><h3 className="section-title">Pending classification</h3><p className="muted">Choose a category before verification.</p></div> : item.verified_at ? <div className="card card-pad"><h3 className="section-title">Already reviewed</h3><p className="muted">Verified outcome: {item.verified_outcome ? 'Correct' : 'Incorrect'} · Action: {item.actual_action ?? 'unknown'}</p>{item.review_notes && <div className="label-note"><strong>Reviewer note</strong><p>{item.review_notes}</p></div>}</div> :
          <div className="card card-pad"><h3 className="section-title">Your verification</h3><p className="muted">Outcome means whether the label was correct against ground truth. Approval alone does not establish correctness.</p><label className="field">Known outcome<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}><option value="">Select outcome…</option><option value="correct">Correct</option><option value="incorrect">Incorrect</option></select></label><div className="button-row" style={{ marginTop: 18 }}><span title={contentUnsaved ? 'Save changes before approving' : undefined}><button className="button" title={contentUnsaved ? 'Save changes before approving' : undefined} disabled={busy || contentUnsaved || !outcome || !item.recommended_action} onClick={() => void submit(item.recommended_action ?? '')}>Approve recommendation (A)</button></span><select className="select" aria-label="Override action" value={override} onChange={event => setOverride(event.target.value)}><option value="">Choose override…</option>{alternatives.map(value => <option key={value}>{value}</option>)}</select><span title={contentUnsaved ? 'Save changes before approving' : undefined}><button className="button amber" title={contentUnsaved ? 'Save changes before approving' : undefined} disabled={busy || contentUnsaved || !outcome || !override} onClick={() => void submit(override)}>Override (O)</button></span><span title={contentUnsaved ? 'Save changes before approving' : undefined}><button className="button danger" title={contentUnsaved ? 'Save changes before approving' : undefined} disabled={busy || contentUnsaved} onClick={() => setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')}>Escalate (E)</button></span></div><label className="field note-field">Add a note (optional)<textarea value={note} maxLength={500} rows={4} disabled={busy || isMutating} onChange={event => setNote(event.target.value)} /><small className="muted">{note.length}/500</small></label></div>}
      </div></div> : !busy && <div className="card card-pad">Label not found. <button className="button secondary" onClick={() => navigate(path('queue'))}>Back to queue</button></div>}
  </div>
}
