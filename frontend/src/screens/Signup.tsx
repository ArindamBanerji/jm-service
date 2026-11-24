import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, registerAccount } from '../api'
import ErrorBanner from '../components/ErrorBanner'

export default function Signup() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
    setBusy(true); setError(null)
    try {
      const result = await registerAccount(email, name)
      localStorage.removeItem('rgi-domain')
      sessionStorage.removeItem('dlj-checkout-pending')
      localStorage.setItem('rgi-api-key', result.api_key)
      window.dispatchEvent(new Event('dlj-key-updated'))
      setKey(result.api_key)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) setError('An account with this email already exists. Contact support to recover your key.')
      else if (cause instanceof ApiError && cause.status === 429) setError('Too many attempts. Please try again in a minute.')
      else setError(cause instanceof Error ? cause.message : String(cause))
    } finally { setBusy(false) }
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
      {key ? <div className="stack"><div className="success">Your trial is ready.</div><label className="field">Your API key<input aria-label="Your API key" value={key} readOnly onFocus={event => event.currentTarget.select()} /></label>
        <strong>Save this key — it cannot be recovered.</strong><div className="button-row"><button className="button" onClick={() => void copy()}>{copied ? 'Copied' : 'Copy key'}</button><button className="button secondary" onClick={() => navigate('/upload')}>Continue to Upload</button></div></div>
        : <form onSubmit={event => void submit(event)} className="stack"><label className="field">Email<input type="email" autoComplete="email" required maxLength={200} value={email} onChange={event => setEmail(event.target.value)} /></label><label className="field">Name (optional)<input autoComplete="name" maxLength={200} value={name} onChange={event => setName(event.target.value)} /></label><button className="button" type="submit" disabled={busy}>{busy ? 'Creating account…' : 'Start Free Trial'}</button></form>}
      <ErrorBanner message={error} />
    </div>
  </div>
}
