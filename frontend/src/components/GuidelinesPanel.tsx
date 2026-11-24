function inline(source: string) {
  return source.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={index}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return part
  })
}

function markdownLines(source: string) {
  return source.split('\n').map((line, index) => {
    if (line.startsWith('### ')) return <h4 key={index}>{inline(line.slice(4))}</h4>
    if (line.startsWith('## ')) return <h3 key={index}>{inline(line.slice(3))}</h3>
    if (line.startsWith('# ')) return <h2 key={index}>{inline(line.slice(2))}</h2>
    if (line.startsWith('- ')) return <p key={index}>• {inline(line.slice(2))}</p>
    return <p key={index}>{line ? inline(line) : '\u00a0'}</p>
  })
}

export default function GuidelinesPanel({ guidelines }: { guidelines: string | null }) {
  return <section className="card card-pad guidelines-panel" aria-label="Annotation guidelines">
    <h3 className="section-title">Annotation guidelines</h3>
    {guidelines ? markdownLines(guidelines) :
      <p>No guidelines configured. Add them in Settings.</p>}
  </section>
}
