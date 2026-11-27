import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getThroughput, type ThroughputResponse } from '../api'
import { captureOperation } from '../operationContext'

export default function ThroughputPanel({ projectId, domainId }: { projectId: string; domainId: string }) {
  const [days, setDays] = useState(7)
  const [data, setData] = useState<ThroughputResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setData(null); setError(null)
    const operation = captureOperation(domainId, projectId)
    getThroughput(projectId, days, operation.credential ?? undefined, operation.signal)
      .then(result => { if (operation.isCurrent()) setData(result) })
      .catch(cause => { if (operation.isCurrent()) setError(String(cause)) })
      .finally(() => operation.finish())
    return () => operation.finish()
  }, [days, domainId, projectId])
  return <section className="card card-pad analytics-panel" aria-labelledby="throughput-title">
    <div className="analytics-panel-head"><div><h2 id="throughput-title" className="section-title">Throughput</h2><p className="muted">Label activity and reviewer pace.</p></div>
      <label className="field analytics-period">Period<select value={days} onChange={event => setDays(Number(event.target.value))} aria-label="Throughput period"><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option></select></label></div>
    {error && <p className="error" role="alert">{error}</p>}
    {data && <><div className="throughput-summary"><strong>{data.summary.avg_per_day.toFixed(1)} labels/day average</strong>{data.summary.avg_time_sec !== null && <span>{data.summary.avg_time_sec.toFixed(0)}s average per label</span>}</div>
      <div className="throughput-chart" data-testid="throughput-chart"><ResponsiveContainer><LineChart data={data.daily}><CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid, #e9eef5)" /><XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={value => String(value).slice(5)} /><YAxis allowDecimals={false} width={34} tick={{ fontSize: 10 }} /><Tooltip /><Line type="monotone" dataKey="labels" name="Labels" stroke="#416de2" strokeWidth={3} dot={{ r: 3 }} /><Line type="monotone" dataKey="verified" name="Verified" stroke="#1f9d78" strokeWidth={2} dot={{ r: 2 }} /></LineChart></ResponsiveContainer></div>
      <div className="annotator-throughput"><h3>Annotators</h3>{data.annotators.map(annotator => <div className="annotator-bar" key={annotator.id}><span>{annotator.name}</span><div className="annotator-track"><span style={{ width: `${Math.max(4, 100 * annotator.labels_total / Math.max(...data.annotators.map(row => row.labels_total), 1))}%` }} /></div><strong>{annotator.labels_today} today · {annotator.labels_total} total</strong></div>)}{!data.annotators.length && <p className="muted">No attributed labels in this period.</p>}</div></>}
    {!data && !error && <p className="muted">Loading throughput…</p>}
  </section>
}
