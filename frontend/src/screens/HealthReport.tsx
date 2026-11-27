import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { downloadReportPdf, uploadForReport } from '../api'
import CsvDropzone from '../components/CsvDropzone'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import { takeReportFile } from '../reportHandoff'

export default function HealthReport() {
  const location = useLocation()
  const [file, setFile] = useState<File | null>(null)
  const [html, setHtml] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const pending = useRef<AbortController | null>(null)
  const analyze = async (next: File) => {
    const run = ++generation.current
    pending.current?.abort()
    pending.current = new AbortController()
    setFile(next); setError(null); setBusy(true); setHtml('')
    try { const result = await uploadForReport(next, pending.current.signal); if (run === generation.current) setHtml(result) }
    catch (cause) { if (run === generation.current) setError(String(cause)) }
    finally { if (run === generation.current) setBusy(false) }
  }
  useEffect(() => {
    const incoming = takeReportFile((location.state as { reportRef?: string } | null)?.reportRef)
    if (incoming) void analyze(incoming)
  }, [location.state])
  useEffect(() => {
    const invalidate = () => { ++generation.current; pending.current?.abort() }
    const clear = () => { invalidate(); setFile(null); setHtml(''); setBusy(false); setError(null) }
    window.addEventListener('dlj-account-changing', clear)
    return () => { window.removeEventListener('dlj-account-changing', clear); invalidate() }
  }, [])
  const download = async () => {
    if (!file) return
    const run = ++generation.current
    pending.current?.abort()
    pending.current = new AbortController()
    setError(null); setBusy(true)
    try {
      const blob = await downloadReportPdf(file, pending.current.signal)
      if (run !== generation.current) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a'); link.href = url; link.download = 'label_health_report.pdf'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (cause) { if (run === generation.current) setError(String(cause)) }
    finally { if (run === generation.current) setBusy(false) }
  }
  return <div className="page"><div className="eyebrow">Free analysis</div><h1>Label Health Report</h1><p className="subtitle">A shareable view of category risk, inversion signals, annotators and modeled cost.</p>
    <div className="card card-pad"><CsvDropzone onFile={analyze} busy={busy} />{file && <p className="muted">{file.name}</p>}{busy && <LoadingSpinner />}<ErrorBanner message={error} /></div>
    {html && <div className="card card-pad" style={{ marginTop: 20 }}><div className="button-row" style={{ justifyContent: 'space-between', marginBottom: 16 }}><h2 className="section-title" style={{ margin: 0 }}>Report preview</h2><button className="button" onClick={download} disabled={busy}>Download PDF</button></div><iframe title="Label Health Report" sandbox="" srcDoc={html} style={{ width: '100%', height: 700, border: '1px solid #e2e8f0', borderRadius: 8, background: 'white' }} /></div>}
  </div>
}
