const contract: Record<string, { name: string; low: string; high: string; description: string }> = {
  model_confidence: { name: 'Model confidence', low: '0.20 · guessing', high: '0.95 · very confident', description: 'The pre-label model’s confidence in its proposed class.' },
  annotator_calibration: { name: 'Annotator calibration', low: '0.50 · half correct', high: '0.95 · reliable', description: 'Prior verified accuracy for this annotator and category.' },
  item_difficulty: { name: 'Item difficulty', low: '0.15 · simple', high: '0.80 · difficult', description: 'Estimated difficulty of this item.' },
  schema_complexity: { name: 'Schema complexity', low: '0.20 · small, flat schema', high: '0.90 · complex schema', description: 'Active classes and nesting depth.' },
}
export default function FactorBar({ factor, value }: { factor: string; value: number }) {
  const display = contract[factor]
  return <div className="factor"><div className="factor-top"><span>{display?.name ?? factor.replaceAll('_', ' ')}</span><strong>{value.toFixed(2)}</strong></div><div className="track"><div className="fill" style={{ width: `${Math.max(0, Math.min(100, value * 100))}%` }} /></div>{display && <><div className="factor-top muted" style={{ fontSize: 10, marginTop: 5 }}><span>{display.low}</span><span>{display.high}</span></div><p className="muted" style={{ margin: '2px 0 0', fontSize: 11 }}>{display.description}</p></>}</div>
}
