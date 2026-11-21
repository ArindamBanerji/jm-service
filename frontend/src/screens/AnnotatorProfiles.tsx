import { Fragment, useEffect, useState } from 'react'
import { getAnnotators, type AnnotatorProfile } from '../api'
import { useDomain } from '../domain'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'

type Key = keyof Pick<AnnotatorProfile, 'annotator_id' | 'total_labels' | 'accuracy' | 'strongest_category' | 'weakest_category' | 'last_active'>
export default function AnnotatorProfiles() {
  const { domainId } = useDomain()
  const [items, setItems] = useState<AnnotatorProfile[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sort, setSort] = useState<Key>('total_labels')
  const [desc, setDesc] = useState(true)
  const [expanded, setExpanded] = useState<string | null>(null)
  useEffect(() => {
    if (!domainId) { setItems([]); return }
    let live = true; setBusy(true); setError(null)
    getAnnotators(domainId, 100).then(response => { if (live) setItems(response.annotators) }).catch(cause => { if (live) setError(String(cause)) }).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [domainId])
  const ordered = [...items].sort((a, b) => { const first = a[sort], second = b[sort]; const result = typeof first === 'number' && typeof second === 'number' ? first - second : String(first ?? '').localeCompare(String(second ?? '')); return desc ? -result : result })
  const header = (key: Key, label: string) => <th onClick={() => { if (sort === key) setDesc(!desc); else { setSort(key); setDesc(key === 'total_labels') } }} tabIndex={0} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); if (sort === key) setDesc(!desc); else setSort(key) } }}>{label}{sort === key ? (desc ? ' ↓' : ' ↑') : ''}</th>
  return <div className="page"><div className="eyebrow">05 / People signals</div><h1>Annotator Profiles</h1><p className="subtitle">Understand whose labels are strongest and where extra review helps.</p><ErrorBanner message={error} />{busy && <LoadingSpinner />}
    <div className="card table-wrap"><table className="table"><thead><tr>{header('annotator_id', 'Annotator')}{header('total_labels', 'Total labels')}<th>Verified</th>{header('accuracy', 'Accuracy')}{header('strongest_category', 'Strongest')}{header('weakest_category', 'Weakest')}{header('last_active', 'Last active')}</tr></thead><tbody>{ordered.map(item => <Fragment key={item.annotator_id}><tr onClick={() => setExpanded(expanded === item.annotator_id ? null : item.annotator_id)} style={{ cursor: 'pointer' }}><td><strong>{item.annotator_id}</strong></td><td>{item.total_labels}</td><td>{item.verified_count}</td><td>{item.accuracy === null ? '—' : `${(item.accuracy * 100).toFixed(1)}%`}</td><td>{item.strongest_category ?? '—'}</td><td>{item.weakest_category ?? '—'}</td><td>{new Date(item.last_active).toLocaleDateString()}</td></tr>{expanded === item.annotator_id && <tr><td colSpan={7} className="muted">The current annotator API provides strongest and weakest categories. Per-category accuracy breakdown is not available yet.</td></tr>}</Fragment>)}</tbody></table>{!busy && !items.length && <div className="loading">{domainId ? 'No annotator profiles yet.' : 'Enter a domain ID to view annotators.'}</div>}</div>
  </div>
}
