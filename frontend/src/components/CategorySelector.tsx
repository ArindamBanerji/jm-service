import { useEffect, useState } from 'react'
import { ApiError, getAutonomy, relabelItem } from '../api'
import ErrorBanner from './ErrorBanner'

interface Props {
  domainId: string
  labelId: string
  revisionId: string
  category: string | null
  previousCategory: string | null
  onSaved: (labelId: string) => Promise<void>
  onSavingChange: (saving: boolean) => void
}

export default function CategorySelector({ domainId, labelId, revisionId, category, previousCategory, onSaved, onSavingChange }: Props) {
  const [categories, setCategories] = useState<string[]>([])
  const [selected, setSelected] = useState(category ?? '')
  const [custom, setCustom] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setSelected(category ?? ''); setSaved(false); setError(null)
    void getAutonomy(domainId).then(result => setCategories(result.categories.map(row => row.category)))
      .catch(cause => setError(String(cause)))
  }, [domainId, labelId, revisionId, category])
  const submit = async () => {
    const next = selected === '__new__' ? custom.trim() : selected.trim()
    if (!next || busy) return
    setBusy(true); onSavingChange(true); setError(null)
    try {
      const result = await relabelItem(domainId, labelId, { category: next, idempotency_token: revisionId })
      setSaved(true)
      await onSaved(result.label_id)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) await onSaved(labelId)
      setError(String(cause))
    } finally { onSavingChange(false); setBusy(false) }
  }
  return <div className="stack" style={{ marginTop: 18 }}><h3 className="section-title">Category</h3>
    {previousCategory && <p className="muted"><s>{previousCategory}</s> → {category}</p>}
    <label className="field">Choose category<select value={selected} onChange={event => setSelected(event.target.value)} disabled={busy || saved}>
      <option value="">Select a category…</option>{categories.map(value => <option key={value} value={value}>{value}</option>)}
      <option value="__new__">New category…</option>
    </select></label>
    {selected === '__new__' && <label className="field">New category name<input value={custom} onChange={event => setCustom(event.target.value)} disabled={busy || saved} /></label>}
    <button className="button secondary" onClick={() => void submit()} disabled={busy || saved || !selected || (selected === '__new__' && !custom.trim()) || (selected === category)}>{category ? 'Relabel' : 'Classify and score'}</button>
    {saved && <p className="success">Category saved.</p>}<ErrorBanner message={error} />
  </div>
}
