import { useEffect, useState } from 'react'
import { ApiError, getAutonomy, relabelItem } from '../api'
import ErrorBanner from './ErrorBanner'
import { captureOperation, type OperationContext } from '../operationContext'

interface Props {
  domainId: string
  labelId: string
  revisionId: string
  category: string | null
  previousCategory: string | null
  disabled?: boolean
  onSaved: (labelId: string) => Promise<void>
  onSavingChange: (saving: boolean) => boolean | void
  onDraftChange?: (dirty: boolean) => void
  operation?: () => OperationContext | null
  projectId?: string | null
}

export default function CategorySelector({ domainId, labelId, revisionId, category, previousCategory, disabled = false, onSaved, onSavingChange, onDraftChange, operation, projectId }: Props) {
  const [categories, setCategories] = useState<string[]>([])
  const [selected, setSelected] = useState(category ?? '')
  const [custom, setCustom] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setSelected(category ?? ''); setSaved(false); setError(null); onDraftChange?.(false)
    const owner = captureOperation(domainId, projectId ?? null)
    setCategories([])
    void getAutonomy(domainId, owner.signal, projectId, owner.credential ?? undefined)
      .then(result => { if (owner.isCurrent()) setCategories(result.categories.map(row => row.category)) })
      .catch(cause => { if (owner.isCurrent()) setError(String(cause)) })
      .finally(owner.finish)
    return owner.finish
  }, [domainId, labelId, revisionId, category, projectId])
  const updateDraft = (value: string, customValue = custom) => {
    setSelected(value)
    onDraftChange?.((value === '__new__' ? customValue.trim() : value) !== (category ?? ''))
  }
  const submit = async () => {
    const next = selected === '__new__' ? custom.trim() : selected.trim()
    if (!next || busy || disabled) return
    if (onSavingChange(true) === false) return
    setBusy(true); setError(null)
    try {
      const owner = operation?.()
      const result = await relabelItem(domainId, labelId, { category: next, idempotency_token: revisionId }, owner?.credential ?? undefined, owner?.signal, projectId)
      if (owner && !owner.isCurrent()) return
      setSaved(true)
      await onSaved(result.label_id)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) await onSaved(labelId)
      setError(String(cause))
    } finally { onSavingChange(false); setBusy(false) }
  }
  return <div className="stack" style={{ marginTop: 18 }}><h3 className="section-title">Category</h3>
    {previousCategory && <p className="muted"><s>{previousCategory}</s> → {category}</p>}
    <label className="field">Choose category<select value={selected} onChange={event => updateDraft(event.target.value)} disabled={busy || saved || disabled}>
      <option value="">Select a category…</option>{categories.map(value => <option key={value} value={value}>{value}</option>)}
      <option value="__new__">New category…</option>
    </select></label>
    {selected === '__new__' && <label className="field">New category name<input value={custom} onChange={event => { setCustom(event.target.value); onDraftChange?.(event.target.value.trim() !== (category ?? '')) }} disabled={busy || saved || disabled} /></label>}
    <button className="button secondary" onClick={() => void submit()} disabled={busy || saved || disabled || !selected || (selected === '__new__' && !custom.trim()) || (selected === category)}>{category ? 'Relabel' : 'Classify and score'}</button>
    {saved && <p className="success">Category saved.</p>}<ErrorBanner message={error} />
  </div>
}
