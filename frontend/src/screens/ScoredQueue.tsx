import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Papa from 'papaparse'
import { bulkVerify, downloadProjectCsv, getAutonomy, getNextBatch, getPendingPage, type PendingLabel, type PendingSort } from '../api'
import { useDomain } from '../domain'
import ConfidenceIndicator from '../components/ConfidenceIndicator'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import SignupBanner from '../components/SignupBanner'
import GuidelinesBanner from '../components/GuidelinesBanner'
import { captureOperation } from '../operationContext'

const columns: { key: PendingSort; title: string }[] = [
  { key: 'label_id', title: 'Label ID' }, { key: 'category', title: 'Category' },
  { key: 'annotator_id', title: 'Annotator' }, { key: 'confidence', title: 'Confidence' },
  { key: 'recommended_action', title: 'Recommendation' },
]

export default function ScoredQueue() {
  const navigate = useNavigate()
  const [focusedRow, setFocusedRow] = useState(0)
  const { domainId, projectId, project } = useDomain()
  const reviewPath = (label: string) => `${projectId ? `/projects/${encodeURIComponent(projectId)}` : ''}/review/${encodeURIComponent(label)}${smartQueue && projectId ? '?queue=smart' : ''}`
  const [storedItems, setItems] = useState<PendingLabel[]>([])
  const [loadedDomain, setLoadedDomain] = useState('')
  const [loadedQuery, setLoadedQuery] = useState('')
  const [total, setTotal] = useState(0)
  const [categories, setCategories] = useState<string[]>([])
  const [category, setCategory] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<PendingSort | undefined>()
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')
  const [pageSize, setPageSize] = useState(50)
  const [offset, setOffset] = useState(0)
  const [showPreview, setShowPreview] = useState(false)
  const [smartQueue, setSmartQueue] = useState(false)
  const [samplingNote, setSamplingNote] = useState<string | null>(null)
  const [samplingStrategy, setSamplingStrategy] = useState<'centroid_distance' | 'random' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkOutcome, setBulkOutcome] = useState<'' | 'correct' | 'incorrect'>('')
  const [toast, setToast] = useState('')
  const preferenceKey = projectId ? `dlj-smart:${projectId}` : null
  const requestId = useRef(0)
  const currentDomain = useRef(domainId)
  currentDomain.current = domainId
  const queryKey = JSON.stringify([projectId, domainId, category, searchInput.trim(), search, sortBy, sortOrder, pageSize, offset, smartQueue])
  const activeQuery = useRef(queryKey)
  activeQuery.current = queryKey
  const queryReady = searchInput.trim() === search
  const items = queryReady && loadedDomain === domainId && loadedQuery === queryKey ? storedItems : []

  useEffect(() => {
    ++requestId.current
    setItems([]); setTotal(0); setSelected(new Set()); setBulkOutcome(''); setLoadedDomain(''); setLoadedQuery('')
    setError(null); setToast(''); setFocusedRow(0); setPageSize(50)
    setSmartQueue(preferenceKey !== null && sessionStorage.getItem(preferenceKey) === 'on'); setSamplingNote(null); setSamplingStrategy(null)
    setCategory(''); setSortBy(undefined); setSortOrder('asc'); setSearchInput(''); setSearch(''); setOffset(0)
  }, [domainId, projectId])
  useEffect(() => {
    if (!domainId || !projectId) return
    let live = true
    const operation = captureOperation(domainId, projectId)
    getNextBatch(projectId, 1, operation.credential ?? undefined, operation.signal).then(result => {
      if (!live || !operation.isCurrent()) return
      setSamplingStrategy(result.strategy); setSamplingNote(result.note ?? null)
      if (preferenceKey && sessionStorage.getItem(preferenceKey) === null) setSmartQueue(result.strategy === 'centroid_distance')
    }).catch(() => {}).finally(() => operation.finish())
    return () => { live = false; operation.finish() }
  }, [domainId, projectId])
  useEffect(() => { setSelected(new Set()); setBulkOutcome('') }, [domainId, projectId, category, searchInput, search, sortBy, sortOrder, pageSize, offset])
  useEffect(() => { setFocusedRow(0) }, [domainId, projectId, category, search, sortBy, sortOrder, pageSize, offset])
  useEffect(() => {
    const nextSearch = searchInput.trim()
    if (nextSearch === search) return
    const timer = setTimeout(() => { setSearch(nextSearch); setOffset(0) }, 300)
    return () => clearTimeout(timer)
  }, [searchInput, search])
  useEffect(() => {
    const visible = new Set(items.map(item => item.label_id))
    setSelected(previous => {
      if ([...previous].every(id => visible.has(id))) return previous
      return new Set([...previous].filter(id => visible.has(id)))
    })
  }, [items])
  useEffect(() => {
    setCategories([])
    if (!domainId) return
    let live = true
    const operation = captureOperation(domainId, projectId)
    getAutonomy(domainId, operation.signal, projectId, operation.credential ?? undefined).then(result => {
      if (live && operation.isCurrent()) setCategories(result.categories.map(item => item.category).sort())
    }).catch(() => { if (live && operation.isCurrent()) setCategories([]) }).finally(() => operation.finish())
    return () => { live = false; operation.finish() }
  }, [domainId, projectId])

  const refresh = useCallback(async () => {
    const current = ++requestId.current
    if (!domainId) { setItems([]); setTotal(0); setBusy(false); return }
    if (!queryReady) { setBusy(false); return }
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      let page: { rows: PendingLabel[]; total: number }
      if (smartQueue && projectId) {
        const smart = await getNextBatch(projectId, pageSize, operation.credential ?? undefined, operation.signal,
          { offset, category: category || undefined, search: search || undefined })
        if (current !== requestId.current || !operation.isCurrent()) return
        page = { rows: smart.items.map(item => ({
          label_id: item.id, category: item.category, annotator_id: item.annotator_id,
          factors: {}, text: null, text_preview: item.text_preview,
          recommended_action: item.recommended_action, confidence: item.confidence,
          centroid_distance: item.centroid_distance, priority_rank: item.priority_rank,
          notes: item.notes, review_notes: item.review_notes,
          media_kind: item.media_kind,
        })), total: smart.total_pending }
        setSamplingNote(smart.note ?? null); setSamplingStrategy(smart.strategy)
      } else {
        page = await getPendingPage(domainId, {
          category: category || undefined, limit: pageSize, offset,
          sort_by: sortBy ?? 'scored_at', sort_order: sortBy ? sortOrder : 'asc', search: search || undefined,
        }, operation.credential ?? undefined, operation.signal, projectId)
      }
      if (current !== requestId.current || currentDomain.current !== domainId || !operation.isCurrent()) return
      setTotal(page.total)
      if (offset > 0 && offset >= page.total) {
        setOffset(page.total ? Math.floor((page.total - 1) / pageSize) * pageSize : 0)
        return
      }
      setItems(page.rows)
      setLoadedDomain(domainId)
      setLoadedQuery(queryKey)
    } catch (cause) {
      if (current === requestId.current && currentDomain.current === domainId && operation.isCurrent()) {
        setItems([]); setTotal(0); setSelected(new Set()); setLoadedDomain(''); setLoadedQuery('')
        setError(String(cause))
      }
    }
    finally { if (current === requestId.current) setBusy(false); operation.finish() }
  }, [domainId, projectId, category, search, pageSize, offset, sortBy, sortOrder, queryKey, queryReady, smartQueue])
  const refreshRef = useRef(refresh)
  refreshRef.current = refresh

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 30000)
    return () => { clearInterval(timer); ++requestId.current }
  }, [refresh])

  const changeSort = (key: PendingSort) => {
    if (preferenceKey) sessionStorage.setItem(preferenceKey, 'off')
    setSmartQueue(false)
    setSortOrder(sortBy === key && sortOrder === 'asc' ? 'desc' : 'asc')
    setSortBy(key); setOffset(0)
  }
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement || target instanceof HTMLButtonElement ||
        target instanceof HTMLAnchorElement || (target instanceof HTMLElement && target.isContentEditable)
      if (event.key === 'Escape') { setSelected(new Set()); return }
      if (!editing && !bulkBusy && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && items.length) {
        event.preventDefault()
        setSelected(new Set(items.map(item => item.label_id)))
      }
      if (editing || event.ctrlKey || event.metaKey || event.altKey || !items.length || bulkBusy) return
      if (event.key === 'j' || event.key === 'k') {
        event.preventDefault()
        setFocusedRow(current => Math.max(0, Math.min(items.length - 1, current + (event.key === 'j' ? 1 : -1))))
      }
      if (event.key === 'Enter') {
        event.preventDefault()
        navigate(reviewPath(items[focusedRow]?.label_id ?? ''))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items, bulkBusy, focusedRow, navigate, projectId])
  const toggleOne = (labelId: string) => setSelected(previous => {
    const next = new Set(previous)
    if (next.has(labelId)) next.delete(labelId)
    else next.add(labelId)
    return next
  })
  useEffect(() => { setBulkOutcome('') }, [selected])
  const allSelected = items.length > 0 && items.every(item => selected.has(item.label_id))
  const submitBulk = async (action: 'approve' | 'reject') => {
    if (!domainId || loadedDomain !== domainId || loadedQuery !== queryKey || busy || bulkBusy || selected.size === 0) return
    if (!bulkOutcome) { setError('Select a known outcome before bulk review.'); return }
    const ids = items.filter(item => selected.has(item.label_id)).map(item => item.label_id)
    if (!ids.length) { setSelected(new Set()); setError('Selection expired. Please re-select.'); return }
    const operation = captureOperation(domainId, projectId)
    setBulkBusy(true); setError(null); setToast('')
    try {
      const result = await bulkVerify(domainId, { label_ids: ids, action, outcome: bulkOutcome === 'correct' }, operation.credential ?? undefined, operation.signal, projectId)
      if (currentDomain.current !== domainId || activeQuery.current !== queryKey || !operation.isCurrent()) return
      setToast(`${action === 'approve' ? 'Approved' : 'Rejected'} ${result.processed}, skipped ${result.skipped}`)
      setSelected(new Set()); setBulkOutcome('')
      await refreshRef.current()
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) } finally { operation.finish(); setBulkBusy(false) }
  }
  const [downloading, setDownloading] = useState(false)
  const downloadCsv = async () => {
    if (!projectId || downloading) return
    const operation = captureOperation(domainId, projectId)
    try {
      if (!operation.credential || !operation.isCurrent()) return
      setDownloading(true)
      const blob = await downloadProjectCsv(projectId, operation.credential, operation.signal)
      if (!operation.isCurrent()) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${projectId}.csv`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) {
      if (operation.isCurrent()) setError(String(cause))
    } finally {
      if (operation.isCurrent()) setDownloading(false)
      operation.finish()
    }
  }
  const exportPage = () => {
    const rows = items.map(item => ({
      label_id: item.label_id, category: item.category, annotator_id: item.annotator_id ?? '',
      confidence: item.confidence, recommended_action: item.recommended_action,
      text_preview: item.text_preview ?? '',
      media_kind: item.media_kind ?? project?.content_type ?? 'text',
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
  return <div className="page"><div className="eyebrow">02 / Review workflow</div><h1>Scored Queue <span className="pill">{total} unverified</span></h1><p className="subtitle">Choose smart learning priority or original upload order. The list refreshes every 30 seconds.</p><SignupBanner /><GuidelinesBanner domainId={domainId} projectId={projectId} />
    <div className="toolbar"><label className="smart-toggle" title="Items are ordered by what the engine would learn most from."><input type="checkbox" checked={smartQueue && Boolean(projectId)} disabled={!projectId} onChange={event => { if (preferenceKey) sessionStorage.setItem(preferenceKey, event.target.checked ? 'on' : 'off'); setSmartQueue(event.target.checked); setOffset(0); setSortBy(undefined); setSamplingNote(null); setSamplingStrategy(null) }} /><span>Smart Queue</span></label><label className="field">Category<select value={category} onChange={event => { setCategory(event.target.value); setOffset(0) }}><option value="">All categories</option>{categories.map(value => <option key={value} value={value}>{value}</option>)}</select></label><label className="field">Status<select value="pending" disabled><option value="pending">Unverified only</option></select></label><label className="field">Rows per page<select value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setOffset(0) }}>{[50, 100, 200].map(value => <option key={value} value={value}>{value}</option>)}</select></label><label className="field"><span>Source preview</span><input type="checkbox" checked={showPreview} onChange={event => setShowPreview(event.target.checked)} /></label><button className="button secondary" onClick={() => void refresh()} disabled={busy}>Refresh</button><button className="button secondary" onClick={exportPage} disabled={busy || !items.length}>Export this page</button></div>
    {projectId && (smartQueue || samplingStrategy === 'random') && <p className="muted smart-queue-note" role="status">{samplingStrategy === 'centroid_distance' ? 'Smart priority: highest centroid distance first.' : samplingNote ?? 'Preparing smart priorities…'}</p>}
    {projectId && project?.role && ['owner', 'admin', 'reviewer'].includes(project.role) && <div className="button-row">
      <button className="button secondary" disabled={downloading} onClick={() => void downloadCsv()}>Download project CSV</button>
      {project.content_type === 'image' && <span className="muted">Export includes image URLs</span>}
    </div>}
    <div className="queue-search"><label htmlFor="queue-search-input">Search labels</label><div className="queue-search-control"><span aria-hidden="true">⌕</span><input id="queue-search-input" type="search" placeholder="Search labels..." value={searchInput} maxLength={200} onChange={event => setSearchInput(event.target.value)} />{searchInput && <button type="button" aria-label="Clear search" onClick={() => { setSearchInput(''); setSearch(''); setOffset(0) }}>×</button>}</div>{search && <span className="muted" role="status">{total} results for ‘{search}’</span>}</div>
    <ErrorBanner message={error} />{toast && <div className="success" role="status">{toast}</div>}{busy && !items.length && <LoadingSpinner />}
    <div className="card table-wrap"><table className="table"><thead><tr><th><input type="checkbox" aria-label="Select all on this page" checked={allSelected} disabled={busy || bulkBusy || !items.length} onChange={event => setSelected(event.target.checked ? new Set(items.map(item => item.label_id)) : new Set())} /></th>{smartQueue && projectId && <th>Learning value</th>}{columns.map(column => <th key={column.key}><button className="table-sort" onClick={() => changeSort(column.key)} aria-label={`Sort by ${column.title}`}>{column.title}{sortBy === column.key ? (sortOrder === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>)}{showPreview && <th>Source preview</th>}<th>Review</th></tr></thead><tbody>{items.map((item, index) => { const kind = item.media_kind ?? project?.content_type ?? 'text'; return <tr key={item.label_id} className={[selected.has(item.label_id) ? 'queue-selected' : '', focusedRow === index ? 'queue-focused' : ''].join(' ')}><td><input type="checkbox" aria-label={`Select ${item.label_id}`} checked={selected.has(item.label_id)} disabled={bulkBusy} onChange={() => toggleOne(item.label_id)} /></td>{smartQueue && projectId && <td><div className="distance-value"><span className="track" aria-hidden="true"><span className="fill" style={{ width: `${Math.min(100, (item.centroid_distance ?? 0) * 60)}%` }} /></span><strong>{item.centroid_distance === null || item.centroid_distance === undefined ? 'Random' : item.centroid_distance.toFixed(3)}</strong></div></td>}<td><strong>{item.label_id}</strong>{kind === 'image' && <><span className="pill media-badge">Image</span><small className="image-row-caption">{item.text_preview || 'Image'}</small></>}{(item.review_notes || item.notes) && <button type="button" className="note-indicator" title={item.review_notes ?? item.notes ?? ''} aria-label={`Note for ${item.label_id}`}>Note</button>}</td><td>{item.category}</td><td>{item.annotator_id ?? '—'}</td><td><ConfidenceIndicator value={item.confidence} /></td><td>{item.recommended_action}</td>{showPreview && <td className="preview-cell">{item.text_preview ?? (kind === 'image' ? 'Image' : 'Source text unavailable.')}</td>}<td><Link className="button secondary" to={reviewPath(item.label_id)}>Review →</Link></td></tr> })}</tbody></table>
      {!items.length && !busy && <div className="loading">{domainId ? 'No pending labels in this view.' : 'Enter a domain ID to see its queue.'}</div>}
    </div><div className="toolbar queue-pages"><span className="muted">Showing {first}–{last} of {total} · Page {Math.floor(offset / pageSize) + 1} of {pages}</span><button className="button secondary" onClick={() => setOffset(Math.max(0, offset - pageSize))} disabled={busy || offset === 0}>Previous</button><button className="button secondary" onClick={() => setOffset(offset + pageSize)} disabled={busy || offset + pageSize >= total}>Next</button></div>
    <p className="muted">Export this page downloads only the displayed pending labels in their current order. Bulk review uses one plan quota unit per processed label.</p>
    {loadedDomain === domainId && loadedQuery === queryKey && selected.size > 0 && <div className="bulk-action-bar" role="region" aria-label="Bulk review actions"><strong>{selected.size} selected</strong><label className="field">Known outcome for all selected labels<select aria-label="Bulk known outcome" value={bulkOutcome} onChange={event => setBulkOutcome(event.target.value as typeof bulkOutcome)} disabled={bulkBusy}><option value="">Select outcome…</option><option value="correct">Correct</option><option value="incorrect">Incorrect</option></select></label><button className="button bulk-approve" onClick={() => void submitBulk('approve')} disabled={bulkBusy || !bulkOutcome}>{bulkBusy && <span className="spinner spinner-small" aria-hidden="true" />}Approve All</button><button className="button danger" onClick={() => void submitBulk('reject')} disabled={bulkBusy || !bulkOutcome}>{bulkBusy && <span className="spinner spinner-small" aria-hidden="true" />}Reject All</button><button className="button secondary" onClick={() => { setSelected(new Set()); setBulkOutcome('') }} disabled={bulkBusy}>Clear Selection</button></div>}
  </div>
}
