import { useEffect, useMemo, useState } from 'react'
import { getAnalyticsAgreement, getConfusion, type AnalyticsAgreementResponse, type ConfusionResponse, type ConfusionSource } from '../api'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import SignupBanner from '../components/SignupBanner'
import { useDomain } from '../domain'
import { captureOperation } from '../operationContext'

const percent = (value: number) => `${Math.round(value * 100)}%`

function ConfusionMatrix({ data }: { data: ConfusionResponse }) {
  const maximum = Math.max(...data.matrix.flat(), 1)
  return <><div className="matrix-wrap" data-testid="confusion-matrix"><table className="analytics-matrix"><thead><tr><th scope="col">Actual ↓ / Labeled →</th>{data.categories.map(category => <th scope="col" key={category}>{category}</th>)}</tr></thead><tbody>{data.categories.map((from, row) => <tr key={from}><th scope="row">{from}</th>{data.categories.map((to, column) => { const count = data.matrix[row]?.[column] ?? 0; const rowTotal = data.matrix[row]?.reduce((sum, value) => sum + value, 0) ?? 0; const pct = rowTotal ? 100 * count / rowTotal : 0; const diagonal = row === column; return <td key={to} title={`${count} ${from} items were labeled as ${to} (${pct.toFixed(1)}%)`} aria-label={`${count} ${from} items were labeled as ${to}, ${pct.toFixed(1)} percent`} style={{ background: diagonal ? `rgba(31,157,120,${.12 + .55 * count / maximum})` : `rgba(209,79,103,${.06 + .65 * count / maximum})` }}>{count}</td> })}</tr>)}</tbody></table></div>
    <div className="top-confusions"><h3>Top confusion pairs</h3>{data.top_confusions.map(pair => <p key={`${pair.from}-${pair.to}`}><strong>{pair.from} → {pair.to}</strong><span>{pair.count} labels · {pair.pct.toFixed(1)}%</span></p>)}{!data.top_confusions.length && <p className="muted">No category confusions recorded.</p>}</div></>
}

function AgreementHeatmap({ data }: { data: AnalyticsAgreementResponse }) {
  const [category, setCategory] = useState('overall')
  useEffect(() => setCategory('overall'), [data])
  const matrix = category === 'overall' ? data.matrix : data.per_category[category] ?? data.matrix
  return <><label className="field analytics-category">Category<select value={category} onChange={event => setCategory(event.target.value)}><option value="overall">Overall</option>{Object.keys(data.per_category).map(name => <option key={name}>{name}</option>)}</select></label>
    {data.annotators.length ? <div className="matrix-wrap" data-testid="agreement-heatmap"><table className="analytics-matrix agreement-matrix"><thead><tr><th scope="col">Annotator</th>{data.annotators.map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead><tbody>{data.annotators.map((left, row) => <tr key={left}><th scope="row">{left}</th>{data.annotators.map((right, column) => { const value = matrix[row]?.[column] ?? 0; const diagonal = row === column; const hue = value >= .9 ? '31,157,120' : value >= .7 ? '214,129,47' : '209,79,103'; return <td key={right} title={`${left} and ${right} agree ${percent(value)} ${category}`} aria-label={`${left} and ${right} agree ${percent(value)} ${category}`} className={diagonal ? 'self-agreement' : ''} style={{ background: diagonal ? undefined : `rgba(${hue},${.16 + value * .55})` }}>{percent(value)}</td> })}</tr>)}</tbody></table></div> : <p className="notice">{data.note}</p>}
    {data.lowest_pair && <p className="lowest-agreement"><strong>Lowest agreement:</strong> {data.lowest_pair.a} ↔ {data.lowest_pair.b} at {percent(data.lowest_pair.agreement)}{data.lowest_pair.worst_category && ` (worst on ${data.lowest_pair.worst_category})`}</p>}</>
}

export default function AnalyticsPage() {
  const { projectId, domainId } = useDomain()
  const [source, setSource] = useState<ConfusionSource>('all')
  const [confusion, setConfusion] = useState<ConfusionResponse | null>(null)
  const [agreement, setAgreement] = useState<AnalyticsAgreementResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const sources = useMemo(() => ['human', 'prediction', 'all'] as const, [])
  useEffect(() => {
    setConfusion(null); setError(null)
    if (!projectId || !domainId) return
    const operation = captureOperation(domainId, projectId)
    getConfusion(projectId, source, operation.credential ?? undefined, operation.signal)
      .then(result => { if (operation.isCurrent()) setConfusion(result) })
      .catch(cause => { if (operation.isCurrent()) setError(String(cause)) })
      .finally(() => operation.finish())
    return () => operation.finish()
  }, [domainId, projectId, source])
  useEffect(() => {
    setAgreement(null)
    if (!projectId || !domainId) return
    const operation = captureOperation(domainId, projectId)
    getAnalyticsAgreement(projectId, operation.credential ?? undefined, operation.signal)
      .then(result => { if (operation.isCurrent()) setAgreement(result) })
      .catch(cause => { if (operation.isCurrent()) setError(String(cause)) })
      .finally(() => operation.finish())
    return () => operation.finish()
  }, [domainId, projectId])
  return <div className="page"><div className="eyebrow">Analysis</div><h1>Analytics</h1><p className="subtitle">Find category confusion and reviewer alignment in the evidence you already collect.</p><SignupBanner /><ErrorBanner message={error} />
    {!projectId && <div className="notice">Select a project to view analytics.</div>}
    {projectId && <div className="stack"><section className="card card-pad analytics-panel"><div className="analytics-panel-head"><div><h2 className="section-title">Confusion Matrix</h2><p className="muted">Original category by verified or corrected category.</p></div><div className="segmented" role="group" aria-label="Confusion source">{sources.map(value => <button key={value} className={source === value ? 'active' : ''} onClick={() => setSource(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div></div>{confusion ? <ConfusionMatrix data={confusion} /> : !error && <LoadingSpinner />}</section>
      <section className="card card-pad analytics-panel"><h2 className="section-title">Agreement</h2><p className="muted">Category and action agreement on items reviewed by the same annotators.</p>{agreement ? <AgreementHeatmap data={agreement} /> : !error && <LoadingSpinner />}</section></div>}
  </div>
}
