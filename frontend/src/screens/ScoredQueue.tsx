import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getPending, type PendingLabel } from '../api'
import { useDomain } from '../domain'
import ConfidenceIndicator from '../components/ConfidenceIndicator'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'

export default function ScoredQueue() {
  const { domainId } = useDomain()
  const [items, setItems] = useState<PendingLabel[]>([])
  const [category, setCategory] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => {
    if (!domainId) { setItems([]); return }
    setBusy(true); setError(null)
    try { setItems((await getPending(domainId, { category: category || undefined, limit: 200 })).sort((a, b) => a.confidence - b.confidence)) }
    catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }, [domainId, category])
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 30000); return () => clearInterval(timer) }, [refresh])
  const categories = [...new Set(items.map(item => item.category))]
  return <div className="page"><div className="eyebrow">02 / Review workflow</div><h1>Scored Queue <span className="pill">{items.length} unverified</span></h1><p className="subtitle">Most uncertain labels first. The list refreshes every 30 seconds.</p>
    <div className="toolbar"><label className="field">Category<select value={category} onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(value => <option key={value}>{value}</option>)}</select></label><label className="field">Status<select value="pending" disabled><option value="pending">Unverified only</option></select></label><button className="button secondary" onClick={() => void refresh()} disabled={busy}>Refresh</button></div>
    <ErrorBanner message={error} />{busy && !items.length && <LoadingSpinner />}
    <div className="card table-wrap"><table className="table"><thead><tr><th>Label ID</th><th>Category</th><th>Annotator</th><th>Confidence</th><th>Recommendation</th><th></th></tr></thead><tbody>{items.map(item => <tr key={item.label_id}><td><strong>{item.label_id}</strong></td><td>{item.category}</td><td>{item.annotator_id ?? '—'}</td><td><ConfidenceIndicator value={item.confidence} /></td><td>{item.recommended_action}</td><td><Link className="button secondary" to={`/review/${encodeURIComponent(item.label_id)}`} state={{ label: item, domainId }}>Review →</Link></td></tr>)}</tbody></table>
      {!items.length && !busy && <div className="loading">{domainId ? 'No pending labels in this view.' : 'Enter a domain ID to see its queue.'}</div>}
    </div><p className="muted">This API returns at most 200 pending labels at a time. Category filtering is applied by the service.</p>
  </div>
}
