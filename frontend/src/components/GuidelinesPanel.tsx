import { Fragment, type ReactNode } from 'react'

function inline(source: string): ReactNode[] {
  return source.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={index}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return part
  })
}

function textBlocks(source: string, keyPrefix: string): ReactNode[] {
  const lines = source.split('\n')
  const result: ReactNode[] = []
  for (let index = 0; index < lines.length;) {
    const line = lines[index]
    if (line.startsWith('- ')) {
      const items: ReactNode[] = []
      while (index < lines.length && lines[index].startsWith('- ')) {
        items.push(<li key={`${keyPrefix}-li-${index}`}>{inline(lines[index].slice(2))}</li>)
        index += 1
      }
      result.push(<ul key={`${keyPrefix}-ul-${index}`}>{items}</ul>)
      continue
    }
    if (line.startsWith('### ')) result.push(<h4 key={`${keyPrefix}-${index}`}>{inline(line.slice(4))}</h4>)
    else if (line.startsWith('## ')) result.push(<h3 key={`${keyPrefix}-${index}`}>{inline(line.slice(3))}</h3>)
    else if (line.startsWith('# ')) result.push(<h2 key={`${keyPrefix}-${index}`}>{inline(line.slice(2))}</h2>)
    else result.push(<p key={`${keyPrefix}-${index}`}>{line ? inline(line) : '\u00a0'}</p>)
    index += 1
  }
  return result
}

export function MarkdownContent({ source }: { source: string }) {
  return <div className="guidelines-markdown">{source.split('```').map((block, index) =>
    index % 2 ? <pre key={index}><code>{block.replace(/^\w*\n/, '')}</code></pre> :
      <Fragment key={index}>{textBlocks(block, `block-${index}`)}</Fragment>)}</div>
}

export default function GuidelinesPanel({ guidelines }: { guidelines: string | null }) {
  return <section className="card card-pad guidelines-panel" aria-label="Annotation guidelines">
    <h3 className="section-title">Annotation guidelines</h3>
    {guidelines ? <MarkdownContent source={guidelines} /> :
      <p>No guidelines yet. Add labeling instructions for your team.</p>}
  </section>
}
