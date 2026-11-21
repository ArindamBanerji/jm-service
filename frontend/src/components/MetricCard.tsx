import type { ReactNode } from 'react'
export default function MetricCard({ value, label, detail }: { value: ReactNode; label: string; detail?: string }) {
  return <div className="metric card"><div className="metric-label">{label}</div><div className="metric-value">{value}</div>{detail && <div className="muted">{detail}</div>}</div>
}
