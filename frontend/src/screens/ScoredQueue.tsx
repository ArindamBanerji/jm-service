import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Papa from 'papaparse'
import { getAutonomy, getPendingPage, type PendingLabel, type PendingSort } from '../api'
import { useDomain } from '../domain'
import ConfidenceIndicator from '../components/ConfidenceIndicator'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import SignupBanner from '../components/SignupBanner'

const columns: { key: PendingSort; title: string }[] = [
  { key: 'label_id', title: 'Label ID' }, { key: 'category', title: 'Category' },
  { key: 'annotator_id', title: 'Annotator' }, { key: 'confidence', title: 'Confidence' },
  { key: 'recommended_action', title: 'Recommendation' },
]

export default function ScoredQueue() {
  const { domainId } = useDomain()
  const [items, setItems] = useState<PendingLabel[]>([])
  const [total, setTotal] = useState(0)
  const [categories, setCategories] = useState<string[]>([])
  const [category, setCategory] = useState('')
  const [sortBy, setSortBy] = useState<PendingSort | undefined>()
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [pageSize, setPageSize] = useState(50)
  const [offset, setOffset] = useState(0)
  const [showPreview, setShowPreview] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const requestId = useRef(0)

  useEffect(() => { setCategory(''); setSortBy(undefined); setSortOrder('asc'); setOffset(0) }, [domainId])
  useEffect(() => {
    setCategories([])
    if (!domainId) return
    let live = true
    getAutonomy(domainId).then(result => {
      if (live) setCategories(result.categories.map(item => item.category).sort())
    }).catch(() => { if (live) setCategories([]) })
    return () => { live = false }
  }, [domainId])

  const refresh = useCallback(async () => {
    const current = ++requestId.current
    if (!domainId) { setItems([]); setTotal(0); setBusy(false); return }
    setBusy(true); setError(null)
    try {
      const page = await getPendingPage(domainId, {
        category: category || undefined, limit: pageSize, offset,
        sort_by: sortBy, sort_order: sortOrder,
      })
      if (current !== requestId.current) return
      setTotal(page.total)
      if (offset > 0 && offset >= page.total) {
        setOffset(page.total ? Math.floor((page.total - 1) / pageSize) * pageSize : 0)
        return
      }
      setItems(page.rows)
    } catch (cause) { if (current === requestId.current) setError(String(cause)) }
    finally { if (current === requestId.current) setBusy(false) }
  }, [domainId, category, pageSize, offset, sortBy, sortOrder])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 30000)
    return () => { clearInterval(timer); ++requestId.current }
  }, [refresh])

  const changeSort = (key: PendingSort) => {
    setSortOrder(sortBy === key && sortOrder === 'asc' ? 'desc' : 'asc')
    setSortBy(key); setOffset(0)
  }
  const exportPage = () => {
    const rows = items.map(item => ({
      label_id: item.label_id, category: item.category, annotator_id: item.annotator_id ?? '',
      confidence: item.confidence, recommended_action: item.recommended_action,
      text_preview: item.text_preview ?? '',
    }))
    const csv = Papa.unparse(rows, { escapeFormulae: true })
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `pending-${domainId.replace(/[^a-zA-Z0-9_-]/g, '_')}-page-${Math.floor(offset / pageSize) + 1}.csv`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const first = total ? offset + 1 : 0
  const last = Math.min(offset + items.length, total)
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return <div className="page"><div className="eyebrow">02 / Review workflow</div><h1>Scored Queue <span className="pill">{total} unverified</span></h1><p className="subtitle">Most uncertain labels first. The list refreshes every 30 seconds and keeps your current page.</p><SignupBanner />
    <div className="toolbar"><label className="field">Category<select value={category} onChange={event => { setCategory(event.target.value); setOffset(0) }}><option value="">All categories</option>{categories.map(value => <option key={value} value={value}>{value}</option>)}</select></label><label className="field">Status<select value="pending" disabled><option value="pending">Unverified only</option></select></label><label className="field">Rows per page<select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setOffset(0) }}>{[50, 100, 200].map(value => <option key={value} value={value}>{value}</option>)}</select></label><label className="field"><span>Source preview</span><input type="checkbox" checked={showPreview} onChange={event => setShowPreview(event.target.checked)} /></label><button className="button secondary" onClick={() => void refresh()} disabled={busy}>Refresh</button><button className="button secondary" onClick={exportPage} disabled={busy || !items.length}>Export this page</button></div>
    <ErrorBanner message={error} />{busy && !items.length && <LoadingSpinner />}
    <div className="card table-wrap"><table className="table"><thead><tr>{columns.map(column => <th key={column.key}><button className="table-sort" onClick={() => changeSort(column.key)} aria-label={`Sort by ${column.title}`}>{column.title}{sortBy === column.key ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>)}{showPreview && <th>Source preview</th>}<th>Review</th></tr></thead><tbody>{items.map(item => <tr key={item.label_id}><td><strong>{item.label_id}</strong></td><td>{item.category}</td><td>{item.annotator_id ?? '—'}</td><td><ConfidenceIndicator value={item.confidence} /></td><td>{item.recommended_action}</td>{showPreview && <td className="preview-cell">{item.text_preview ?? 'Source text unavailable.'}</td>}<td><Link className="button secondary" to={`/review/${encodeURIComponent(item.label_id)}`} state={{ label: item, domainId }}>Review →</Link></td></tr>)}</tbody></table>
      {!items.length && !busy && <div className="loading">{domainId ? 'No pending labels in this view.' : 'Enter a domain ID to see its queue.'}</div>}
    </div><div className="toolbar queue-pages"><span className="muted">Showing {first}–{last} of {total} · Page {Math.floor(offset / pageSize) + 1} of {pages}</span><button className="button secondary" onClick={() => setOffset(Math.max(0, offset - pageSize))} disabled={busy || offset === 0}>Previous</button><button className="button secondary" onClick={() => setOffset(offset + pageSize)} disabled={busy || offset + pageSize >= total}>Next</button></div>
    <p className="muted">Export this page downloads only the displayed pending labels in their current order.</p>
  </div>
}
