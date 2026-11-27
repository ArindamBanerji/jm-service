import { useEffect, useState } from 'react'
import { getDistribution, type DistributionResponse } from '../api'
import { captureOperation } from '../operationContext'

const COLORS = ['#416de2', '#6d5bd0', '#1f9d78', '#d6812f', '#d14f67', '#2f8fa3']

export default function DistributionPanel({ projectId, domainId }: { projectId: string; domainId: string }) {
  const [data, setData] = useState<DistributionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setData(null); setError(null)
    const operation = captureOperation(domainId, projectId)
    getDistribution(projectId, operation.credential ?? undefined, operation.signal)
      .then(result => { if (operation.isCurrent()) setData(result) })
      .catch(cause => { if (operation.isCurrent()) setError(String(cause)) })
      .finally(() => operation.finish())
    return () => operation.finish()
  }, [domainId, projectId])
  return <section className="card card-pad analytics-panel" aria-labelledby="distribution-title">
    <h2 id="distribution-title" className="section-title">Label Distribution</h2>
    <p className="muted">Current labels by category and verification state.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {data?.imbalance_warning && <div className="analytics-warning" role="alert">⚠ {data.imbalance_warning}</div>}
    <div className="distribution-bars" data-testid="distribution-chart">
      {data?.categories.map((category, index) => <div className="distribution-row" key={category.name}>
        <div className="distribution-label"><strong>{category.name}</strong><span>{category.count.toLocaleString()} · {category.pct.toFixed(1)}%</span></div>
        <div className="distribution-track" role="img" aria-label={`${category.name}: ${category.count} labels, ${category.pct.toFixed(1)} percent`}>
          <span style={{ width: `${category.pct}%`, background: COLORS[index % COLORS.length] }} />
        </div>
        <small className="muted">{category.verified} verified · {category.pending} pending</small>
      </div>)}
      {data && !data.categories.length && <p className="muted">No labels yet.</p>}
      {!data && !error && <p className="muted">Loading distribution…</p>}
    </div>
  </section>
}
