import type { NerSpan } from '../api'

const palette = ['#dbeafe', '#fde68a', '#d1fae5', '#f5d0fe', '#fed7aa', '#fecdd3']
export function nerColor(label: string): string {
  let hash = 0
  for (const point of Array.from(label)) hash = (hash * 31 + (point.codePointAt(0) ?? 0)) >>> 0
  return palette[hash % palette.length]
}

export default function NERViewer({ text, spans }: { text: string; spans: NerSpan[] }) {
  const points = Array.from(text)
  const ordered = [...spans].sort((a, b) => a.start - b.start || a.end - b.end)
  const labels = [...new Set(ordered.map(span => span.label))].sort()
  const color = nerColor
  let position = 0
  const parts = ordered.map((span, index) => {
    const before = points.slice(position, span.start).join('')
    const mention = points.slice(span.start, span.end).join('')
    position = span.end
    return <span key={`${span.start}-${span.end}-${index}`}>
      {before}<mark tabIndex={0} aria-label={`${span.label}: ${mention}, characters ${span.start} to ${span.end}`}
        style={{ background: color(span.label), color: '#172033', borderRadius: 4,
                 padding: '2px 3px', boxDecorationBreak: 'clone' }}>
        {mention}<span aria-hidden="true" style={{ marginLeft: 4, fontSize: '0.7em', fontWeight: 700 }}>{span.label}</span>
      </mark>
    </span>
  })
  return <section aria-label="Named entities" style={{ marginTop: 20 }}>
    <h3 className="section-title">Named entities</h3>
    <div className="card-pad" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
      background: '#f7f9fc', borderRadius: 8 }}>{parts}{points.slice(position).join('')}</div>
    <div className="muted" style={{ marginTop: 12 }}>Entity legend</div>
    <ul>{labels.map(label => <li key={label}><span aria-hidden="true" style={{ background: color(label),
      padding: '1px 10px', borderRadius: 4, marginRight: 8 }} />{label}</li>)}</ul>
    <ol>{ordered.map((span, index) => <li key={`${span.start}-${span.end}-${index}`}>
      {span.label}: “{span.text}” ({span.start}–{span.end})
    </li>)}</ol>
  </section>
}
