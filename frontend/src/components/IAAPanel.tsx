import type { AgreementResponse } from '../api'

function interpretation(value: number) {
  if (value < 0.2) return 'Poor'
  if (value < 0.4) return 'Fair'
  if (value < 0.6) return 'Moderate'
  if (value < 0.8) return 'Good'
  return 'Excellent'
}

export default function IAAPanel({ data }: { data: AgreementResponse | null }) {
  return <section className="card card-pad" style={{ marginTop: 18 }}>
    <h2 className="section-title">Inter-annotator agreement</h2>
    {!data?.pairs.length ? <p className="muted">Need 2+ annotators with overlapping labels to calculate agreement</p> :
      <>
        <p>Overall Cohen’s κ: <strong>{data.overall_kappa?.toFixed(2) ?? '—'}</strong>
          {data.overall_kappa !== null && <span className="pill" style={{ marginLeft: 8 }}>
            {interpretation(data.overall_kappa)}</span>}</p>
        <p className="muted">{data.total_overlapping_labels} pairwise overlapping labels</p>
        <div className="table-wrap"><table className="table"><thead><tr>
          <th>Annotator A</th><th>Annotator B</th><th>Kappa</th><th>Overlap</th>
        </tr></thead><tbody>{data.pairs.map(pair => <tr key={pair.annotator_a + pair.annotator_b}>
          <td>{pair.annotator_a}</td><td>{pair.annotator_b}</td>
          <td>{pair.kappa === null ? '—' : <span className="pill">{pair.kappa.toFixed(2)} · {interpretation(pair.kappa)}</span>}</td>
          <td>{pair.overlap_count}</td>
        </tr>)}</tbody></table></div>
      </>}
  </section>
}
