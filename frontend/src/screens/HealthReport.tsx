import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { downloadReportPdf, uploadForReport } from '../api'
import CsvDropzone from '../components/CsvDropzone'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'

export default function HealthReport() {
  const location = useLocation()
  const [file, setFile] = useState<File | null>(null)
  const [html, setHtml] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const analyze = async (next: File) => { setFile(next); setError(null); setBusy(true); setHtml(''); try { setHtml(await uploadForReport(next)) } catch (cause) { setError(String(cause)) } finally { setBusy(false) } }
  useEffect(() => { const incoming = (location.state as { file?: File } | null)?.file; if (incoming) void analyze(incoming) }, [location.state])
  const download = async () => {
    if (!file) return
    setError(null); setBusy(true)
    try {
      const blob = await downloadReportPdf(file)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = 'label_health_report.pdf'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }
  return <div className="page"><div className="eyebrow">Free analysis</div><h1>Label Health Report</h1><p className="subtitle">A shareable view of category risk, inversion signals, annotators and modeled cost.</p>
    <div className="card card-pad"><CsvDropzone onFile={analyze} busy={busy} />{file && <p className="muted">{file.name}</p>}{busy && <LoadingSpinner />}<ErrorBanner message={error} /></div>
    {html && <div className="card card-pad" style={{ marginTop: 20 }}><div className="button-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}><h2 className="section-title" style={{ margin: 0 }}>Report preview</h2><button className="button" onClick={download} disabled={busy}>Download PDF</button></div><iframe title="Label Health Report" sandbox="" srcDoc={html} style={{ width: '100%', height: 700, border: '1px solid #e2e8f0', borderRadius: 8, background: 'white' }} /></div>}
  </div>
}
