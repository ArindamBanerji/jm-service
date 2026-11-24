export default function TextViewer({ text }: { text: string | null }) {
  return <section aria-label="Source text"><h3 className="section-title">Source text</h3>
    {text === null ? <p className="muted">Source text unavailable.</p> :
      <div className="card-pad" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: '#f7f9fc', borderRadius: 8 }}>{text}</div>}
  </section>
}
