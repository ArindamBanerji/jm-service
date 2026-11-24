import { useEffect, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getCompounding, getCorrections, getOverview, type CompoundingResponse, type CorrectionsResponse, type OverviewResponse } from '../api'
import { useDomain } from '../domain'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import MetricCard from '../components/MetricCard'
import TierBadge from '../components/TierBadge'
import SignupBanner from '../components/SignupBanner'

const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`
export default function Dashboard() {
  const { domainId } = useDomain()
  const [overview, setOverview] = useState<OverviewResponse | null>(null)
  const [corrections, setCorrections] = useState<CorrectionsResponse | null>(null)
  const [curve, setCurve] = useState<CompoundingResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!domainId) { setOverview(null); return }
    let live = true; setBusy(true); setError(null)
    Promise.all([getOverview(domainId), getCorrections(domainId), getCompounding(domainId)])
      .then(([a, b, c]) => { if (live) { setOverview(a); setCorrections(b); setCurve(c) } })
      .catch(cause => { if (live) setError(String(cause)) }).finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [domainId])
  return <div className="page"><div className="eyebrow">04 / System intelligence</div><h1>Dashboard</h1><p className="subtitle">Watch verified evidence turn into earned autonomy, one category at a time.</p><SignupBanner /><ErrorBanner message={error} />
    {busy && <LoadingSpinner />}{!domainId && <div className="notice">Enter a domain ID to view its dashboard.</div>}
    {overview && <><div className="grid-3" style={{ marginBottom: 18 }}><MetricCard label="OVERALL ACCURACY" value={percent(overview.overall_accuracy)} detail="Verified labels" /><MetricCard label="VERIFIED" value={overview.total_verified.toLocaleString()} detail="Human-reviewed outcomes" /><MetricCard label="TOTAL LABELS" value={overview.total_labels.toLocaleString()} detail="Scored in this domain" /></div>
      <div className="grid-2"><div className="card card-pad"><h2 className="section-title">Autonomy ladder</h2><p className="muted">GREEN stays on confirmation. Only AUTONOMOUS is eligible for automatic acceptance.</p><div className="stack">{overview.categories.map(item => <div className="card card-pad" key={item.category} style={{ boxShadow: 'none', padding: 15 }}><div className="button-row" style={{ justifyContent: 'space-between' }}><strong>{item.category}</strong><TierBadge tier={item.tier} /></div><p className="muted" style={{ marginBottom: 4 }}>{percent(item.accuracy)} accuracy · {item.verified_count} verified</p><small className="muted">{item.next_tier_requirements ?? 'Highest tier reached'}{!item.conservation_gate_pass && ` · Gate: ${item.conservation_reason ?? 'paused'}`}</small></div>)}</div>{!overview.categories.length && <p className="muted">No categories yet.</p>}</div>
        <div className="card card-pad"><h2 className="section-title">Compounding accuracy</h2><p className="muted">Running verified accuracy · baseline {percent(curve?.baseline_accuracy ?? null)} · current {percent(curve?.current_accuracy ?? null)}</p><div style={{ width: '100%', height: 285 }}><ResponsiveContainer><LineChart data={overview.compounding_curve}><CartesianGrid strokeDasharray="3 3" stroke="#e9eef5" /><XAxis dataKey="verified_count" tick={{ fontSize: 11 }} /><YAxis domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} tick={{ fontSize: 11 }} /><Tooltip formatter={(v) => `${(Number(v) * 100).toFixed(1)}%`} /><Line type="monotone" dataKey="accuracy" stroke="#416de2" strokeWidth={3} dot={false} /></LineChart></ResponsiveContainer></div><p className="muted">Baseline to current: {curve?.improvement === null || curve?.improvement === undefined ? '—' : `${curve.improvement >= 0 ? '+' : ''}${curve.improvement.toFixed(1)} percentage points`}</p></div></div>
      {overview.inversion && <div className="card card-pad" style={{ marginTop: 18, background: '#fffaec', borderColor: '#f4d895' }}><div className="eyebrow" style={{ color: '#9d6811' }}>Signal inversion detected</div><h2 className="section-title" style={{ marginTop: 10 }}>Your annotators trust {overview.inversion.trusted_factor} most. But {overview.inversion.actual_signal_factor} is more predictive.</h2><p className="muted">{overview.inversion.interpretation}</p></div>}
      <div className="card card-pad" style={{ marginTop: 18 }}><div className="button-row" style={{ justifyContent: 'space-between' }}><h2 className="section-title">Correction patterns</h2><span className="pill">{corrections?.total_corrections ?? 0} corrections</span></div><p className="muted">Where human reviewers changed the system's recommendation.</p><div className="grid-3">{corrections?.patterns.slice(0, 3).map((pattern, index) => <div className="card card-pad" key={index} style={{ boxShadow: 'none' }}><strong>{pattern.category}</strong><p>{pattern.recommended_action} → {pattern.actual_action}</p><span className="muted">{pattern.count} corrections · {pattern.percentage_of_category.toFixed(1)}% of category corrections</span></div>)}</div>{!corrections?.patterns.length && <p className="muted">No action corrections recorded yet.</p>}</div>
    </>}
  </div>
}
