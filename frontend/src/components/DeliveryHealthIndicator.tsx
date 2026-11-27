import type { WebhookHealth } from '../api'

export default function DeliveryHealthIndicator({ health }: { health: WebhookHealth | null }) {
  if (!health) return <span className="pill">Delivery health unavailable</span>
  if (health.total === 0) return <span className="pill">No webhooks configured</span>
  if (health.items.every(item => item.status === 'paused' || item.status === 'awaiting')) return <span className="pill">No active delivery result yet</span>
  const status = health.failing ? 'failing' : health.retrying ? 'retrying' : 'healthy'
  const text = health.failing ? `${health.failing}/${health.total} failing` :
    health.retrying ? `${health.retrying}/${health.total} retrying` : `${health.healthy}/${health.total} healthy`
  return <span className={`health-summary health-${status}`}><span aria-hidden>●</span>{text}</span>
}
