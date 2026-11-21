import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ingestBatch, uploadForAnalysis, type HealthReport } from '../api'
import { parseIngestCsv } from '../csv'
import { useDomain } from '../domain'
import CsvDropzone from '../components/CsvDropzone'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'

export default function Upload() {
  const { domainId } = useDomain()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<HealthReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const analyze = async (next: File) => {
    setFile(next); setReport(null); setError(null); setBusy(true); setProgress(0)
    try { setReport(await uploadForAnalysis(next)) } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }
  const startScoring = async () => {
    if (!file || !domainId) { setError('Enter an active domain ID in the sidebar.'); return }
    setBusy(true); setError(null)
    try {
      const rows = await parseIngestCsv(file)
      for (let start = 0; start < rows.length; start += 100) {
        await ingestBatch({ domain_id: domainId, items: rows.slice(start, start + 100) })
        setProgress(Math.min(start + 100, rows.length))
      }
      navigate('/queue')
    } catch (cause) { setError(`${String(cause)}${progress ? ` (${progress} rows already ingested)` : ''}`) } finally { setBusy(false) }
  }
  return <div className="page"><div className="eyebrow">01 / Onboarding</div><h1>Start with your labels.</h1><p className="subtitle">Upload an existing CSV. See its health first, then score labels into a review queue.</p>
    <div className="card card-pad"><CsvDropzone onFile={analyze} busy={busy} /><p className="muted">CSV requires at least 200 rows, label_id, category, verified outcome, and two numeric factor columns. The health report is free and does not save your data.</p>
      {file && <p><strong>{file.name}</strong> <span className="muted">· {(file.size / 1024).toFixed(0)} KB</span></p>}
      {busy && <LoadingSpinner />}{progress > 0 && <p className="muted">Scored {progress} rows</p>}<ErrorBanner message={error} />
      {report && <div className="stack"><div className="success">Analysis ready · {report.metadata.row_count} labels · {report.metadata.verified_count} verified · {report.metadata.factor_count} factors</div>
        {report.warnings?.map((warning, index) => <div className="notice" key={index}>{warning}</div>)}
        <div className="button-row"><button className="button" onClick={startScoring} disabled={busy || !domainId}>Start scoring these labels</button><button className="button secondary" onClick={() => navigate('/health', { state: { file } })}>View full report</button></div>
        <p className="muted">Scoring creates pending review items in batches of 100. Verification outcomes in this CSV are used for the report; they are not imported into live training.</p>
      </div>}
    </div>
  </div>
}
