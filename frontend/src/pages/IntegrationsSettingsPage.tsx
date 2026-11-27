import { useCallback, useEffect, useState } from 'react'
import { createWebhook, deleteWebhook, getWebhookDeliveries, getWebhookHealth, getWebhooks,
  rotateWebhook, testWebhook, updateWebhook, WEBHOOK_EVENTS, type DeliveryPage,
  type WebhookConfig, type WebhookEventType, type WebhookHealth } from '../api'
import DeliveryHealthIndicator from '../components/DeliveryHealthIndicator'
import ErrorBanner from '../components/ErrorBanner'
import { useDomain } from '../domain'
import { captureOperation } from '../operationContext'

const emptyEvents: WebhookEventType[] = ['label.verified']

export default function IntegrationsSettingsPage() {
  const { projectId, domainId } = useDomain()
  const [hooks, setHooks] = useState<WebhookConfig[]>([])
  const [health, setHealth] = useState<WebhookHealth | null>(null)
  const [history, setHistory] = useState<Record<string, DeliveryPage>>({})
  const [editing, setEditing] = useState<WebhookConfig | 'new' | null>(null)
  const [url, setUrl] = useState('https://')
  const [events, setEvents] = useState<WebhookEventType[]>(emptyEvents)
  const [active, setActive] = useState(true)
  const [secret, setSecret] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    if (!projectId) return
    const operation = captureOperation(domainId, projectId)
    try {
      const [rows, status] = await Promise.all([
        getWebhooks(projectId, operation.credential ?? undefined, operation.signal),
        getWebhookHealth(projectId, operation.credential ?? undefined, operation.signal),
      ])
      if (operation.isCurrent()) { setHooks(rows); setHealth(status) }
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish() }
  }, [domainId, projectId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const clear = () => { setHooks([]); setHealth(null); setHistory({}); setEditing(null); setSecret(null) }
    window.addEventListener('dlj-account-changing', clear)
    return () => window.removeEventListener('dlj-account-changing', clear)
  }, [])
  const begin = (value: WebhookConfig | 'new') => {
    setEditing(value); setUrl(value === 'new' ? 'https://' : value.url)
    setEvents(value === 'new' ? emptyEvents : value.subscribed_events); setActive(value === 'new' || value.active)
    setError(null); setSecret(null)
  }
  const save = async () => {
    if (!projectId || !editing || busy) return
    if (!/^https:\/\//i.test(url)) { setError('Webhook URL must use HTTPS.'); return }
    if (!events.length) { setError('Select at least one event type.'); return }
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      const result = editing === 'new' ? await createWebhook(projectId, { url, subscribed_events: events }, operation.credential ?? undefined, operation.signal) :
        await updateWebhook(projectId, editing.id, { url, subscribed_events: events, active }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      if (result.signing_secret) setSecret(result.signing_secret)
      setEditing(null); setNotice(editing === 'new' ? 'Webhook created.' : 'Webhook updated.'); await load()
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish(); setBusy(false) }
  }
  const act = async (hook: WebhookConfig, kind: 'delete' | 'test' | 'rotate') => {
    if (!projectId || busy) return
    if (kind === 'delete' && !confirm('Pause this webhook and cancel pending deliveries?')) return
    if (kind === 'rotate' && !confirm('Rotate the signing secret? Pending deliveries for the old version will be cancelled.')) return
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null); setSecret(null)
    try {
      if (kind === 'delete') await deleteWebhook(projectId, hook.id, operation.credential ?? undefined, operation.signal)
      else if (kind === 'test') await testWebhook(projectId, hook.id, operation.credential ?? undefined, operation.signal)
      else {
        const result = await rotateWebhook(projectId, hook.id, operation.credential ?? undefined, operation.signal)
        if (operation.isCurrent()) setSecret(result.signing_secret ?? null)
      }
      if (operation.isCurrent()) { setNotice(kind === 'test' ? 'Test event queued.' : kind === 'rotate' ? 'Secret rotated.' : 'Webhook paused.'); await load() }
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish(); setBusy(false) }
  }
  const toggleHistory = async (hook: WebhookConfig) => {
    if (!projectId) return
    if (history[hook.id]) { setHistory(value => { const copy = { ...value }; delete copy[hook.id]; return copy }); return }
    const operation = captureOperation(domainId, projectId)
    try {
      const page = await getWebhookDeliveries(projectId, hook.id, operation.credential ?? undefined, operation.signal)
      if (operation.isCurrent()) setHistory(value => ({ ...value, [hook.id]: page }))
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish() }
  }
  const healthById = new Map(health?.items.map(item => [item.webhook_id, item]))
  return <div className="page"><div className="eyebrow">Project settings</div><div className="integration-title"><div><h1>Integrations</h1><p className="subtitle">Signed, durable delivery for project events.</p></div><DeliveryHealthIndicator health={health} /></div>
    <ErrorBanner message={error} />{notice && <p className="success" role="status">{notice}</p>}
    {secret && <div className="notice secret-once" role="status"><strong>Save this signing secret now. It is shown once.</strong><code>{secret}</code><button className="button secondary" onClick={() => { void navigator.clipboard?.writeText(secret).then(() => setNotice('Signing secret copied.')).catch(() => setError('Select and copy the displayed signing secret.')) }}>Copy</button></div>}
    <div className="button-row"><button className="button" onClick={() => begin('new')}>Add webhook</button></div>
    {editing && <section className="card card-pad integration-form" aria-label="Webhook form"><h2>{editing === 'new' ? 'Add webhook' : 'Edit webhook'}</h2>
      <label className="field">HTTPS URL<input value={url} onChange={event => setUrl(event.target.value)} /></label>
      <fieldset><legend>Event types</legend>{WEBHOOK_EVENTS.map(value => <label key={value}><input type="checkbox" checked={events.includes(value)} onChange={event => setEvents(current => event.target.checked ? [...current, value] : current.filter(item => item !== value))} /> {value}</label>)}</fieldset>
      {editing !== 'new' && <label><input type="checkbox" checked={active} onChange={event => setActive(event.target.checked)} /> Active</label>}
      <div className="button-row"><button className="button" disabled={busy} onClick={() => void save()}>Save</button><button className="button secondary" disabled={busy} onClick={() => setEditing(null)}>Cancel</button></div></section>}
    <div className="stack integrations-list">{hooks.map(hook => { const delivery = healthById.get(hook.id); const page = history[hook.id]; return <section className="card card-pad" key={hook.id}>
      <div className="integration-row"><span className={`health-dot health-${delivery?.status ?? 'healthy'}`} aria-label={delivery?.status ?? 'healthy'}>●</span><div><strong>{hook.url}</strong><p className="muted">{hook.subscribed_events.join(', ')}</p></div><span className="pill">{hook.active ? 'active' : 'paused'}</span><span className="muted">Created {new Date(hook.created_at).toLocaleDateString()}</span></div>
      <p className="muted">{hook.signing_secret_masked} · key version {hook.key_version}{hook.rotated_at ? ` · rotated ${new Date(hook.rotated_at).toLocaleString()}` : ''}</p>
      <div className="button-row"><button className="button secondary" onClick={() => begin(hook)}>Edit</button><button className="button secondary" disabled={busy || !hook.active} onClick={() => void act(hook, 'test')}>Test send</button><button className="button secondary" disabled={busy} onClick={() => void act(hook, 'rotate')}>Rotate secret</button><button className="button secondary" onClick={() => void toggleHistory(hook)}>{page ? 'Hide' : 'View'} delivery history</button><button className="button danger" disabled={busy || !hook.active} onClick={() => void act(hook, 'delete')}>Delete</button></div>
      {page && <div className="table-wrap attempt-history"><table className="table"><thead><tr><th>Time</th><th>Event</th><th>Status</th><th>Duration</th><th>Retry</th></tr></thead><tbody>{page.attempt_history.map(attempt => <tr key={`${attempt.delivery_id}:${attempt.attempt_no}`}><td>{new Date(attempt.timestamp).toLocaleString()}</td><td>{attempt.event_type}<br /><small>{attempt.event_id}</small></td><td>{attempt.http_status ?? attempt.outcome ?? 'pending'} {attempt.error_summary}</td><td>{attempt.response_time_ms == null ? '—' : `${attempt.response_time_ms} ms`}</td><td>Attempt {attempt.attempt_no}{attempt.next_retry_at && ` · next ${new Date(attempt.next_retry_at).toLocaleString()}`}</td></tr>)}{!page.attempt_history.length && <tr><td colSpan={5} className="muted">No delivery attempts yet.</td></tr>}</tbody></table></div>}
    </section> })}</div>
  </div>
}
