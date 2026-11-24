import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, registerAccount, type RegistrationResponse } from '../api'
import ErrorBanner from '../components/ErrorBanner'

const deferredKey = 'dlj-deferred-registration'
const readDeferred = (): RegistrationResponse | null => {
  try {
    const stored = JSON.parse(sessionStorage.getItem(deferredKey) ?? 'null') as
      { result?: RegistrationResponse; startingKey?: string | null } | null
    if (!stored?.result || stored.startingKey !== localStorage.getItem('rgi-api-key')) {
      sessionStorage.removeItem(deferredKey)
      return null
    }
    return stored.result
  }
  catch { return null }
}

export default function Signup() {
  const navigate = useNavigate()
  const mounted = useRef(false)
  const registrationEpoch = useRef(0)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [key, setKey] = useState(() => readDeferred()?.api_key ?? '')
  const [deferred, setDeferred] = useState(() => readDeferred() !== null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    mounted.current = true
    const showDeferred = () => {
      const result = readDeferred()
      if (result) { setKey(result.api_key); setDeferred(true) }
    }
    const onKeyChange = () => {
      registrationEpoch.current += 1
      sessionStorage.removeItem(deferredKey)
      setDeferred(false)
      setCopied(false)
      setKey('')
      setBusy(false)
    }
    window.addEventListener('dlj-registration-deferred', showDeferred)
    window.addEventListener('dlj-account-changing', onKeyChange)
    return () => {
      mounted.current = false
      registrationEpoch.current += 1
      window.removeEventListener('dlj-registration-deferred', showDeferred)
      window.removeEventListener('dlj-account-changing', onKeyChange)
    }
  }, [])
  useEffect(() => {
    const clearOldReceipt = () => {
      if (key && localStorage.getItem('rgi-api-key') !== key) { setKey(''); setCopied(false) }
    }
    window.addEventListener('dlj-account-changing', clearOldReceipt)
    return () => window.removeEventListener('dlj-account-changing', clearOldReceipt)
  }, [key])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    registrationEpoch.current += 1
    const myEpoch = registrationEpoch.current
    setBusy(true); setError(null)
    const startingKey = localStorage.getItem('rgi-api-key')
    try {
      const result = await registerAccount(email, name)
      if (myEpoch !== registrationEpoch.current) return
      if (!mounted.current || !window.location.hash.startsWith('#/signup') ||
          localStorage.getItem('rgi-api-key') !== startingKey) {
        if (localStorage.getItem('rgi-api-key') !== startingKey) return
        sessionStorage.setItem(deferredKey, JSON.stringify({ result, startingKey }))
        window.dispatchEvent(new Event('dlj-registration-deferred'))
        return
      }
      sessionStorage.removeItem(deferredKey)
      localStorage.removeItem('rgi-domain')
      sessionStorage.removeItem('dlj-checkout-pending')
      localStorage.setItem('rgi-api-key', result.api_key)
      window.dispatchEvent(new Event('dlj-key-updated'))
      setKey(result.api_key)
      setDeferred(false)
    } catch (cause) {
      if (!mounted.current || myEpoch !== registrationEpoch.current) return
      if (cause instanceof ApiError && cause.status === 409) setError('An account with this email already exists. Contact support to recover your key.')
      else if (cause instanceof ApiError && cause.status === 429) setError('Too many attempts. Please try again in a minute.')
      else setError(cause instanceof Error ? cause.message : String(cause))
    } finally { if (mounted.current && myEpoch === registrationEpoch.current) setBusy(false) }
  }
  const useDeferredKey = () => {
    if (!key) return
    sessionStorage.removeItem(deferredKey)
    localStorage.setItem('rgi-api-key', key)
    window.dispatchEvent(new Event('dlj-key-updated'))
    setDeferred(false)
  }
  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(key)
    } catch {
      const input = document.createElement('textarea')
      input.value = key; input.style.position = 'fixed'; input.style.opacity = '0'
      document.body.appendChild(input); input.select()
      const worked = document.execCommand('copy')
      input.remove()
      if (!worked) { setError('Copy failed. Select the key above and copy it manually.'); return }
    }
    setCopied(true)
  }
  return <div className="page"><div className="eyebrow">Free trial</div><h1>Start your free trial.</h1><p className="subtitle">Create an account to score labels and review the results.</p>
    <div className="card card-pad signup-card">
      {key ? <div className="stack"><div className="success">{deferred ? 'Registration completed. This key is not active on this browser.' : 'Your trial is ready.'}</div><label className="field">Your API key<input aria-label="Your API key" value={key} readOnly onFocus={event => event.currentTarget.select()} /></label>
        <strong>Save this key — it cannot be recovered.</strong><div className="button-row"><button className="button" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy key'}</button>{deferred && <button className="button" onClick={useDeferredKey}>Use this key</button>}<button className="button secondary" onClick={() => navigate('/upload')}>Continue to Upload</button></div></div>
        : <form onSubmit={event => void submit(event)} className="stack"><label className="field">Email<input type="email" autoComplete="email" required maxLength={200} value={email} onChange={event => setEmail(event.target.value)} /></label><label className="field">Name (optional)<input autoComplete="name" maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label><button className="button" type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Start Free Trial'}</button></form>}
      <ErrorBanner message={error} />
    </div>
  </div>
}
