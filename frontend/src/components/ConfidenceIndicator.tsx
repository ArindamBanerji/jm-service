export default function ConfidenceIndicator({ value }: { value: number }) {
  return <div className="confidence"><strong>{Math.round(value * 100)}%</strong><div className="track"><div className="fill" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} /></div></div>
}
