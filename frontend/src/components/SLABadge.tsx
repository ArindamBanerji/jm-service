import { useEffect, useState } from 'react'
import { getProjectSla, type SlaResponse } from '../api'
import { captureOperation } from '../operationContext'

const copy = (sla: SlaResponse) => {
  if (sla.gate_status === 'inactive') return `SLA activates after ${sla.min_verified_for_sla} labels`
  if (sla.gate_status === 'safe') return `≥${sla.floor_pct?.toFixed(1)}% guaranteed`
  if (sla.gate_status === 'warning') return 'Approaching floor'
  return sla.gate_status === 'critical' ? 'Critical margin' : 'Quality paused'
}

export default function SLABadge({ projectId, domainId }: { projectId: string; domainId: string }) {
  const [sla, setSla] = useState<SlaResponse | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => {
    let live = true
    setSla(null); setUnavailable(false)
    const operation = captureOperation(domainId, projectId)
    getProjectSla(projectId, operation.credential ?? undefined, operation.signal)
      .then(result => { if (live && operation.isCurrent()) setSla(result) })
      .catch(() => { if (live && operation.isCurrent()) setUnavailable(true) })
      .finally(() => operation.finish())
    return () => { live = false; operation.finish() }
  }, [domainId, projectId])
  if (unavailable) return <div className="sla-badge sla-inactive" role="status"><span aria-hidden="true">◇</span><strong>Quality SLA unavailable</strong></div>
  if (!sla) return <div className="sla-badge sla-inactive" role="status"><span aria-hidden="true">◇</span><strong>Loading quality SLA…</strong></div>
  return <div className={`sla-badge sla-${sla.gate_status}`} role="status" title={sla.margin === null ? copy(sla) : `Margin: ${sla.margin.toFixed(1)} percentage points above the floor`} aria-label={`Quality SLA: ${copy(sla)}`}>
    <span className="sla-shield" aria-hidden="true">⬟</span><div><strong>{copy(sla)}</strong>
      {sla.gate_status !== 'inactive' && <small>{sla.current_accuracy.toFixed(1)}% current · {sla.margin?.toFixed(1)}pp margin</small>}
    </div>
  </div>
}
