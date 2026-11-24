import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getAccount, getAccountDomains, getCheckoutUrl, getGuidelines, putGuidelines, resolveAccountDomain,
  type AccountDomain, type AccountSummary } from '../api'
import { useDomain } from '../domain'
import ErrorBanner from '../components/ErrorBanner'

const pendingKey = 'dlj-checkout-pending'
const tiers = ['starter', 'professional', 'business', 'scale']
const date = (value: string) => new Date(value).toLocaleDateString()
const emptyUsage: AccountSummary['usage'] = {
  labels_today: 0, labels_this_month: 0, daily_cap: null, monthly_cap: null, day_key: '—', month_key: '—',
}

class UsageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <section className="card card-pad"><h2 className="section-title">Key usage</h2><p className="muted">Usage is temporarily unavailable.</p></section>
    return this.props.children
  }
}

export default function Settings() {
  const { domainId, setDomainId } = useDomain()
  const [keyInput, setKeyInput] = useState('')
  const [configured, setConfigured] = useState(() => Boolean(localStorage.getItem('rgi-api-key')))
  const [account, setAccount] = useState<AccountSummary | null>(null)
  const [domains, setDomains] = useState<AccountDomain[]>([])
  const [domainName, setDomainName] = useState(domainId)
  const [tier, setTier] = useState('starter')
  const [pending, setPending] = useState(() => sessionStorage.getItem(pendingKey) !== null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [keyVersion, setKeyVersion] = useState(0)
  const [guidelines, setGuidelines] = useState('')
  const [guidelinesMessage, setGuidelinesMessage] = useState('')
  const [guidelinesLoading, setGuidelinesLoading] = useState(false)
  const [guidelinesDomain, setGuidelinesDomain] = useState('')
  const [guidelinesSaving, setGuidelinesSaving] = useState(false)
  const activeDomain = useRef(domainId)
  activeDomain.current = domainId
  useEffect(() => {
    setGuidelines(''); setGuidelinesDomain(''); setGuidelinesMessage('')
    if (!domainId || !configured) { setGuidelinesLoading(false); return }
    const controller = new AbortController()
    setGuidelinesLoading(true)
    getGuidelines(domainId, controller.signal).then(result => {
      if (controller.signal.aborted || activeDomain.current !== domainId) return
      setGuidelines(result.guidelines ?? ''); setGuidelinesDomain(domainId)
    }).catch(cause => {
      if (!controller.signal.aborted && activeDomain.current === domainId) setError(String(cause))
    }).finally(() => {
      if (!controller.signal.aborted && activeDomain.current === domainId) setGuidelinesLoading(false)
    })
    return () => controller.abort()
  }, [domainId, configured])
  const saveGuidelines = async () => {
    if (!domainId || guidelinesDomain !== domainId || guidelinesLoading || guidelinesSaving) return
    const savedDomain = domainId
    setGuidelinesSaving(true); setGuidelinesMessage(''); setError(null)
    try {
      await putGuidelines(savedDomain, guidelines)
      if (activeDomain.current === savedDomain) setGuidelinesMessage('Guidelines saved.')
    } catch (cause) {
      if (activeDomain.current === savedDomain) setError(String(cause))
    } finally { setGuidelinesSaving(false) }
  }

  const refresh = useCallback(async () => {
    if (!localStorage.getItem('rgi-api-key')) { setAccount(null); setDomains([]); return }
    try {
      const [summary, names] = await Promise.all([getAccount(), getAccountDomains()])
      setAccount(summary); setDomains(names); setError(null)
      const previous = sessionStorage.getItem(pendingKey)
      if (previous && summary.tier === previous) {
        sessionStorage.removeItem(pendingKey)
        setPending(false)
      }
    } catch (cause) { setAccount(null); setDomains([]); setError(String(cause)) }
  }, [])

  useEffect(() => {
    void refresh()
    const onFocus = () => void refresh()
    window.addEventListener('focus', onFocus)
    const timer = pending ? window.setInterval(() => void refresh(), 5000) : undefined
    const stop = pending ? window.setTimeout(() => { if (timer) window.clearInterval(timer) }, 60000) : undefined
    return () => { window.removeEventListener('focus', onFocus); if (timer) window.clearInterval(timer); if (stop) window.clearTimeout(stop) }
  }, [refresh, keyVersion, pending])

  const storeKey = () => {
    const next = keyInput.trim()
    if (!next) { setError('Enter an API key.'); return }
    localStorage.setItem('rgi-api-key', next)
    window.dispatchEvent(new Event('dlj-key-updated'))
    setKeyInput(''); setConfigured(true); setKeyVersion(value => value + 1)
  }
  const clearKey = () => {
    localStorage.removeItem('rgi-api-key')
    window.dispatchEvent(new Event('dlj-key-updated'))
    setAccount(null); setDomains([]); setConfigured(false)
    setKeyVersion(value => value + 1)
  }
  const useDomainName = async (value: string) => {
    const next = value.trim()
    if (!next) { setError('Enter a public domain name.'); return }
    setBusy(true); setError(null)
    try {
      await resolveAccountDomain(next)
      setDomains(await getAccountDomains())
    } catch (cause) {
      if (!(cause instanceof ApiError && cause.status === 404)) {
        setError(String(cause)); setBusy(false); return
      }
    }
    setDomainId(next); setDomainName(next); setBusy(false)
  }
  const checkout = async () => {
    setBusy(true); setError(null)
    try {
      const result = await getCheckoutUrl(tier)
      if (!result.checkout_url?.startsWith('https://')) throw new Error('Checkout URL is unavailable. Please try again later.')
      sessionStorage.setItem(pendingKey, tier)
      setPending(true)
      window.location.assign(result.checkout_url)
    } catch (cause) { setError(String(cause)); setBusy(false) }
  }
  const usage = account?.usage && typeof account.usage === 'object' ? account.usage : emptyUsage
  const labelsToday = usage.labels_today ?? 0
  const labelsMonth = usage.labels_this_month ?? 0
  const dailyCap = usage.daily_cap ?? null
  const monthlyCap = usage.monthly_cap ?? null
  const dayKey = usage.day_key ?? '—'
  const monthKey = usage.month_key ?? '—'
  return <div className="page"><div className="eyebrow">Account</div><h1>Settings</h1><p className="subtitle">Manage your local key, current domain, and subscription.</p>
    <div className="grid-2"><section className="card card-pad"><h2 className="section-title">API key</h2><p>{configured ? 'Key configured on this browser' : 'No key configured'}</p><p className="muted">Your key is stored locally in this browser. The service cannot show it again.</p><label className="field">{configured ? 'Replace local key' : 'Enter API key'}<input type="password" autoComplete="off" value={keyInput} onChange={event => setKeyInput(event.target.value)} /></label><div className="button-row" style={{ marginTop: 12 }}><button className="button" onClick={storeKey}>Save key</button>{configured && <button className="button secondary" onClick={clearKey}>Clear local key</button>}</div>{!configured && <p><Link to="/signup">Start a free trial →</Link></p>}</section>
      <section className="card card-pad"><h2 className="section-title">Account</h2>{account ? <><p><strong>{account.tenant_name}</strong> · {account.tier}</p><p className="muted">Key status: {account.is_active ? 'Active' : 'Inactive'}<br />Tenant ID: {account.tenant_id}<br />Created: {date(account.created_at)}</p>{account.cancelled_at && <div className="notice">Subscription cancelled on {date(account.cancelled_at)}. Your data is retained for 30 days.</div>}{account.tier === 'trial' && <div className="notice">{account.trial_expired ? 'Trial expired' : 'Free trial active'} · ends {account.trial_expires_at ? date(account.trial_expires_at) : '—'}. Trial scoring is limited to 50 labels per day.</div>}</> : <p className="muted">Add a valid key to see account details.</p>}<button className="button secondary" onClick={() => void refresh()} disabled={!configured}>Refresh account</button></section></div>
    {account && <div className="grid-2" style={{ marginTop: 18 }}><UsageBoundary key={account.tenant_id}><section className="card card-pad"><h2 className="section-title">Key usage</h2><p>Today ({dayKey} UTC): <strong>{labelsToday.toLocaleString()}</strong>{dailyCap !== null && ` / ${dailyCap.toLocaleString()}`}</p><p>This month ({monthKey} UTC): <strong>{labelsMonth.toLocaleString()}</strong> / {account.tier === 'trial' ? '50/day trial limit' : monthlyCap === null ? 'Unlimited' : monthlyCap.toLocaleString()}</p><p className="muted">These are counters for this API key. Domain totals are on the Dashboard.</p></section></UsageBoundary>
      <section className="card card-pad"><h2 className="section-title">Subscription</h2>{pending && <div className="notice">Awaiting checkout confirmation. Your tier will update when Paddle confirms the subscription.</div>}<p className="muted">Choose a plan to open Paddle checkout. Your current tier remains in effect until confirmed.</p><div className="button-row"><label className="field">Plan<select value={tier} onChange={event => setTier(event.target.value)}>{tiers.map(value => <option key={value} value={value}>{value}</option>)}</select></label><button className="button" onClick={() => void checkout()} disabled={busy}>Upgrade with Paddle</button></div></section></div>}
    <section className="card card-pad" style={{ marginTop: 18 }}><h2 className="section-title">Domains</h2><p className="muted">Select a known domain or enter a public name. A new domain is created when you first score a label.</p><div className="button-row"><label className="field">Public domain name<input value={domainName} onChange={event => setDomainName(event.target.value)} placeholder="Enter domain name" /></label><button className="button" onClick={() => void useDomainName(domainName)} disabled={busy || !configured}>Use domain</button></div><p>Active domain: <strong>{domainId || 'None'}</strong></p>{domains.map(row => row.public_domain_id ? <button className="button secondary domain-choice" key={row.id} onClick={() => void useDomainName(row.public_domain_id!)}>{row.public_domain_id}</button> : <p className="muted" key={row.id}>An older domain needs its public name. Enter that name above to recover it.</p>)}</section>
    <section className="card card-pad" style={{ marginTop: 18 }}><h2 className="section-title">Annotation guidelines</h2>
      <p className="muted">Instructions for reviewers in the active domain.</p>
      <label className="field">Guidelines<textarea rows={9} value={guidelinesDomain === domainId ? guidelines : ''} disabled={guidelinesLoading || guidelinesDomain !== domainId} onChange={event => { setGuidelines(event.target.value); setGuidelinesMessage('') }} /></label>
      <button className="button" disabled={!domainId || !configured || guidelinesLoading || guidelinesSaving || guidelinesDomain !== domainId || new TextEncoder().encode(guidelines).length > 10 * 1024}
        onClick={() => void saveGuidelines()}>Save guidelines</button>
      {guidelinesMessage && <p className="success">{guidelinesMessage}</p>}
    </section>
    <ErrorBanner message={error} />
  </div>
}
