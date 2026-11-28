import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, confirmAccount, confirmRecovery, recoverKey, registerAccount, type KeyReceipt } from '../api'
import ErrorBanner from '../components/ErrorBanner'
import { copyKey } from '../copyKey'

import { getAccountGeneration } from '../operationContext'

const deferredKey = 'dlj-deferred-registration'
type StoredReceipt = { result: KeyReceipt; startingKey: string | null; active?: boolean }
const readDeferred = (): StoredReceipt | null => {
  try {
    const stored = JSON.parse(sessionStorage.getItem(deferredKey) ?? 'null') as StoredReceipt | null
    if (!stored?.result || stored.startingKey !== localStorage.getItem('rgi-api-key')) {
      sessionStorage.removeItem(deferredKey)
      return null
    }
    return stored
  }
  catch { return null }
}

export default function Signup() {
  const navigate = useNavigate()
  const recoveryLink = new URLSearchParams(useLocation().search).get('recover') === '1'
  const [recovering, setRecovering] = useState(recoveryLink)
  const keyInput = useRef<HTMLInputElement>(null)
  const mounted = useRef(false)
  const registrationEpoch = useRef(0)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [key, setKey] = useState(() => recoveryLink ? '' : readDeferred()?.result.api_key ?? '')
  const [deferred, setDeferred] = useState(() => readDeferred()?.active !== true && readDeferred() !== null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmationPending, setConfirmationPending] = useState(false)
  const [token, setToken] = useState('')
  useEffect(() => {
    mounted.current = true
    const showDeferred = () => {
      const result = readDeferred()
      if (result) { setKey(result.result.api_key); setDeferred(result.active !== true) }
    }
    const onKeyChange = () => {
      registrationEpoch.current += 1
      sessionStorage.removeItem(deferredKey)
      setEmail(''); setName(''); setError(null)
      setDeferred(false)
      setCopied(false)
      setKey('')
      setBusy(false)
      setConfirmationPending(false)
      setToken('')
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
    try {
      if (recovering) await recoverKey(email)
      else await registerAccount(email, name)
      if (myEpoch !== registrationEpoch.current) return
      if (mounted.current && window.location.hash.startsWith('#/signup')) setConfirmationPending(true)
    } catch (cause) {
      if (!mounted.current || myEpoch !== registrationEpoch.current) return
      if (!recovering && cause instanceof ApiError && cause.status === 409 && cause.message === 'Email already registered') setRecovering(true)
      else if (cause instanceof ApiError && cause.status === 429) setError(recovering ? 'Too many recovery requests. Try again in one hour.' : 'Too many attempts. Please try again in a minute.')
      else setError(cause instanceof Error ? cause.message : String(cause))
    } finally { if (mounted.current && myEpoch === registrationEpoch.current) setBusy(false) }
  }
  const confirm = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    registrationEpoch.current += 1
    const myEpoch = registrationEpoch.current
    setBusy(true); setError(null)
    const accountGeneration = getAccountGeneration()
    const startingKey = localStorage.getItem('rgi-api-key')
    try {
      const result = recovering ? await confirmRecovery(token.trim()) : await confirmAccount(token.trim())
      if (accountGeneration !== getAccountGeneration() || localStorage.getItem('rgi-api-key') !== startingKey) return
      if (mounted.current && myEpoch !== registrationEpoch.current) return
      if (!mounted.current || !window.location.hash.startsWith('#/signup') ||
          localStorage.getItem('rgi-api-key') !== startingKey) {
        if (localStorage.getItem('rgi-api-key') !== startingKey) return
        sessionStorage.setItem(deferredKey, JSON.stringify({ result, startingKey, active: false }))
        window.dispatchEvent(new Event('dlj-registration-deferred'))
        return
      }
      sessionStorage.removeItem(deferredKey)
      localStorage.removeItem('rgi-domain')
      sessionStorage.removeItem('dlj-checkout-pending')
      localStorage.setItem('rgi-api-key', result.api_key)
      window.dispatchEvent(new Event('dlj-key-updated'))
      sessionStorage.setItem(deferredKey, JSON.stringify({ result, startingKey: result.api_key, active: true }))
      setKey(result.api_key)
      setDeferred(false)
      setConfirmationPending(false)
    } catch (cause) {
      if (!mounted.current || myEpoch !== registrationEpoch.current) return
      setError(cause instanceof Error ? cause.message : String(cause))
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
    if (!keyInput.current) return
    const epoch = registrationEpoch.current
    const worked = await copyKey(keyInput.current)
    if (!mounted.current || epoch !== registrationEpoch.current) return
    if (worked) setCopied(true)
    else setError('Select the key and copy it manually.')
  }
  return <div className="page"><div className="eyebrow">{recovering ? 'Account access' : 'Free trial'}</div><h1>{recovering ? 'Recover your API key' : 'Start your free trial.'}</h1><p className="subtitle">{recovering ? 'Use your verified signup email. Confirming the code replaces your old key and keeps your projects and subscription.' : 'Create an account to score labels and review the results.'}</p>
    <div className="card card-pad signup-card">
      {key ? <div className="stack"><div className="success">{deferred ? 'This key is ready to use. Choose Use this key to activate it in this browser.' : recovering ? 'Your replacement key is ready. Update any apps using the old key.' : 'Your account is ready.'}</div><label className="field">Your API key<input ref={keyInput} aria-label="Your API key" value={key} readOnly onFocus={event => event.currentTarget.select()} /></label>
        <strong>Save this key securely. You can copy the active key from the sidebar.</strong><div className="button-row"><button className="button" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy key'}</button>{deferred && <button className="button" onClick={useDeferredKey}>Use this key</button>}<button className="button secondary" onClick={() => navigate('/upload')}>Continue to Upload</button><Link to="/projects">Manage projects</Link></div></div>
        : confirmationPending ? <form onSubmit={event => void confirm(event)} className="stack"><p>{recovering ? 'Check your email for a recovery code. Use the latest code within 15 minutes.' : 'Check your email for a confirmation code.'}</p><label className="field">{recovering ? 'Recovery code' : 'Confirmation code'}<input autoComplete="one-time-code" required minLength={64} maxLength={64} value={token} onChange={event => setToken(event.target.value)} /></label><button className="button" type="submit" disabled={busy}>{busy ? 'Confirming…' : recovering ? 'Replace API key' : 'Confirm email'}</button><button className="button secondary" type="button" disabled={busy} onClick={() => { setToken(''); setError(null); setConfirmationPending(false) }}>Request another code</button></form>
        : <div className="stack"><form onSubmit={event => void submit(event)} className="stack"><label className="field">Email<input type="email" autoComplete="email" required maxLength={200} value={email} onChange={event => setEmail(event.target.value)} /></label>{!recovering && <label className="field">Name (optional)<input autoComplete="name" maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label>}<button className="button" type="submit" disabled={busy}>{busy ? 'Sending email…' : recovering ? 'Recover your key' : 'Start Free Trial'}</button></form><button className="button secondary" type="button" disabled={busy} onClick={() => { setToken(''); setError(null); setConfirmationPending(true) }}>I already have a code</button><button className="button secondary" type="button" disabled={busy} onClick={() => { setRecovering(!recovering); setError(null) }}>{recovering ? 'Create a new account' : 'Lost your API key?'}</button></div>}
      <ErrorBanner message={error} />
    </div>
  </div>
}
