import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getAutonomy, getPending, verifyLabel, type PendingLabel, type TierStatus } from '../api'
import { useDomain } from '../domain'
import ConfidenceIndicator from '../components/ConfidenceIndicator'
import ErrorBanner from '../components/ErrorBanner'
import FactorBar from '../components/FactorBar'
import LoadingSpinner from '../components/LoadingSpinner'
import TierBadge from '../components/TierBadge'

export default function ReviewCard() {
  const { domainId } = useDomain()
  const { labelId } = useParams()
  const currentDomain = useRef(domainId)
  currentDomain.current = domainId
  const navigate = useNavigate()
  const [item, setItem] = useState<PendingLabel | null>(null)
  const [loadedDomain, setLoadedDomain] = useState('')
  const [pending, setPending] = useState<PendingLabel[]>([])
  const [tier, setTier] = useState<TierStatus | null>(null)
  const [outcome, setOutcome] = useState<'' | 'correct' | 'incorrect'>('')
  const [override, setOverride] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setOutcome(''); setOverride(''); setMessage(''); setItem(null); setLoadedDomain('') }, [domainId, labelId])
  const load = useCallback(async () => {
    if (!domainId) return
    setBusy(true); setError(null)
    try {
      const [rows, autonomy] = await Promise.all([getPending(domainId, { limit: 200 }), getAutonomy(domainId)])
      if (currentDomain.current !== domainId) return
      setPending(rows)
      const found = rows.find(row => row.label_id === labelId) ?? null
      setItem(found)
      setLoadedDomain(found ? domainId : '')
      setTier(autonomy.categories.find(status => status.category === found?.category) ?? null)
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }, [domainId, labelId])
  useEffect(() => { void load() }, [load])
  const submit = async (action: string) => {
    if (!item || !domainId) return
    if (domainId !== loadedDomain) { setError('Domain changed. Please reload.'); return }
    if (busy) return
    if (!outcome) { setError('Select the verified ground-truth outcome before reviewing.'); return }
    setBusy(true); setError(null)
    try {
      await verifyLabel({ domain_id: domainId, label_id: item.label_id, actual_action: action, verified_outcome: outcome === 'correct' })
      setMessage(`Verified ${item.label_id}.`)
      const next = pending.find(row => row.label_id !== item.label_id)
      if (next) navigate(`/review/${encodeURIComponent(next.label_id)}`, { replace: true, state: { label: next, domainId } })
      else navigate('/queue', { replace: true })
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.metaKey || event.ctrlKey) return
      if (event.key.toLowerCase() === 'a') void submit(item?.recommended_action ?? '')
      if (event.key.toLowerCase() === 'o' && override) void submit(override)
      if (event.key.toLowerCase() === 'e') setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')
    }
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler)
  })
  const alternatives = ['approve', 'reject'].filter(action => action !== item?.recommended_action)
  return <div className="page"><div className="eyebrow">03 / Verification</div><h1>Review label</h1><p className="subtitle">Confirm or correct the recommended action using a known ground-truth outcome.</p>
    <ErrorBanner message={error} />{message && <div className="notice">{message}</div>}{busy && !item && <LoadingSpinner />}
    {item && loadedDomain === domainId ? <div className="grid-2"><div className="card card-pad"><div className="eyebrow">Label</div><h2 style={{ margin: '10px 0 3px' }}>{item.label_id}</h2><p className="muted">{item.category} · Annotator {item.annotator_id ?? 'unknown'}</p><hr style={{ border: 0, borderTop: '1px solid #e7ecf2', margin: '22px 0' }} /><h3 className="section-title">Factor signals</h3>{Object.entries(item.factors).map(([factor, value]) => <FactorBar key={factor} factor={factor} value={value} />)}</div>
      <div className="stack"><div className="card card-pad"><div className="eyebrow">JM recommendation</div><h2 style={{ textTransform: 'capitalize' }}>{item.recommended_action}</h2><ConfidenceIndicator value={item.confidence} /><div className="button-row" style={{ marginTop: 20 }}>{tier && <TierBadge tier={tier.tier} />}<span className="muted">Conservation: {tier?.conservation_reason ?? (tier?.conservation_gate_pass ? 'clear' : 'unknown')}</span></div></div>
        <div className="card card-pad"><h3 className="section-title">Your verification</h3><p className="muted">Outcome means whether the label was correct against ground truth. Approval alone does not establish correctness.</p><label className="field">Known outcome<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}><option value="">Select outcome…</option><option value="correct">Correct</option><option value="incorrect">Incorrect</option></select></label><div className="button-row" style={{ marginTop: 18 }}><button className="button" disabled={busy || !outcome} onClick={() => void submit(item.recommended_action)}>Approve recommendation (A)</button><select className="select" aria-label="Override action" value={override} onChange={event => setOverride(event.target.value)}><option value="">Choose override…</option>{alternatives.map(value => <option key={value}>{value}</option>)}</select><button className="button amber" disabled={busy || !outcome || !override} onClick={() => void submit(override)}>Override (O)</button><button className="button danger" onClick={() => setMessage('Escalation needs a configured backend action. This label remains pending for analyst review.')}>Escalate (E)</button></div></div>
      </div></div> : !busy && <div className="card card-pad">Label not found in the current pending page. <button className="button secondary" onClick={() => navigate('/queue')}>Back to queue</button></div>}
  </div>
}
