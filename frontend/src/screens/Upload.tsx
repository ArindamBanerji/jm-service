import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Papa from 'papaparse'
import { createTextTask, hasApiKey, ingestBatch, seedSample, uploadForAnalysis, type HealthReport } from '../api'
import { parseIngestCsv } from '../csv'
import { useDomain } from '../domain'
import CsvDropzone from '../components/CsvDropzone'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import SignupBanner from '../components/SignupBanner'
import { storeReportFile } from '../reportHandoff'

export default function Upload() {
  const { domainId, setDomainId } = useDomain()
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<HealthReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [sample, setSample] = useState(false)
  const [taskId, setTaskId] = useState('')
  const [taskText, setTaskText] = useState('')
  const [taskCategory, setTaskCategory] = useState('')
  const [dropzoneVersion, setDropzoneVersion] = useState(0)
  const importController = useRef<AbortController | null>(null)
  const importCounts = useRef({ committed: 0, total: 0 })
  const analysisRun = useRef(0)
  const clearUpload = () => {
    ++analysisRun.current
    setFile(null); setReport(null); setProgress(0); setSample(false)
    setTaskId(''); setTaskText(''); setTaskCategory('')
    setDropzoneVersion(value => value + 1)
  }
  useEffect(() => {
    const accountChanging = () => {
      const active = importController.current
      active?.abort()
      clearUpload()
      if (active) setError(`Import stopped: account changed during upload. ${importCounts.current.committed} of ${importCounts.current.total} rows were committed to the original account.`)
      importCounts.current = { committed: 0, total: 0 }
    }
    window.addEventListener('dlj-account-changing', accountChanging)
    return () => {
      window.removeEventListener('dlj-account-changing', accountChanging)
      importController.current?.abort()
    }
  }, [])
  const createTask = async () => {
    if (!domainId || !taskId.trim() || !taskText) { setError('Enter a domain, label ID and source text.'); return }
    setBusy(true); setError(null)
    try {
      await createTextTask(domainId, { label_id: taskId.trim(), text: taskText, category: taskCategory.trim() || undefined })
      navigate(`/review/${encodeURIComponent(taskId.trim())}`)
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }
  const analyze = async (next: File, isSample = false) => {
    const run = ++analysisRun.current
    setSample(isSample); setFile(next); setReport(null); setError(null); setBusy(true); setProgress(0)
    try { const result = await uploadForAnalysis(next); if (run === analysisRun.current) setReport(result) }
    catch (cause) { if (run === analysisRun.current) setError(String(cause)) }
    finally { if (run === analysisRun.current) setBusy(false) }
  }
  const trySample = async () => {
    setBusy(true); setError(null)
    try {
      const response = await fetch('/demo/sample_data.json')
      if (!response.ok) throw new Error('Sample data could not be loaded')
      const fixture = await response.json() as { domain_id: string; rows: Record<string, unknown>[] }
      if (fixture.domain_id !== 'medical-ner-demo-v1' || fixture.rows.length !== 500) throw new Error('Sample data is invalid')
      const rows = fixture.rows.map(row => ({
        label_id: row.label_id, category: row.category, annotator_id: row.annotator_id,
        factor_model_confidence: row.factor_model_confidence,
        factor_item_difficulty: row.factor_item_difficulty,
        verified_outcome: row.verified_outcome == null ? '' : row.verified_outcome,
        text: row.text,
      }))
      const csv = new File([Papa.unparse(rows)], 'medical-ner-demo-v1.csv', { type: 'text/csv' })
      await analyze(csv, true)
    } catch (cause) { setError(String(cause)); setBusy(false) }
  }
  const scoreSample = async () => {
    if (!hasApiKey()) { setError('Enter a labeling API key in the sidebar to score 12 sample labels.'); return }
    setBusy(true); setError(null)
    try {
      const result = await seedSample('medical-ner-demo-v1')
      setDomainId(result.domain_id)
      navigate('/queue')
    } catch (cause) { setError(String(cause)) } finally { setBusy(false) }
  }
  const startScoring = async () => {
    if (!file || !domainId) { setError('Enter an active domain ID in the sidebar.'); return }
    const capturedKey = localStorage.getItem('rgi-api-key')
    if (!capturedKey) { setError('Enter an API key before importing labels.'); return }
    const controller = new AbortController()
    importController.current = controller
    sessionStorage.setItem('dlj-import-active', '1')
    let committed = 0
    let total = 0
    importCounts.current = { committed, total }
    setBusy(true); setError(null)
    try {
      const rows = await parseIngestCsv(file)
      total = rows.length
      importCounts.current.total = total
      for (let start = 0; start < rows.length; start += 100) {
        if (controller.signal.aborted || localStorage.getItem('rgi-api-key') !== capturedKey) {
          clearUpload()
          setError(`Import stopped: account changed during upload. ${committed} of ${rows.length} rows were committed to the original account.`)
          return
        }
        await ingestBatch({ domain_id: domainId, items: rows.slice(start, start + 100) }, capturedKey, controller.signal)
        committed = Math.min(start + 100, rows.length)
        importCounts.current.committed = committed
        setProgress(committed)
      }
      if (controller.signal.aborted || localStorage.getItem('rgi-api-key') !== capturedKey) {
        clearUpload()
        setError(`Import stopped: account changed during upload. ${committed} of ${rows.length} rows were committed to the original account.`)
        return
      }
      navigate('/queue')
    } catch (cause) {
      if (localStorage.getItem('rgi-api-key') !== capturedKey) {
        clearUpload()
        setError(`Import stopped: account changed during upload. ${committed} of ${total} rows were committed to the original account.`)
      } else if (!controller.signal.aborted) setError(`${String(cause)}${committed ? ` (${committed} rows already ingested)` : ''}`)
    } finally {
      if (importController.current === controller) importController.current = null
      sessionStorage.removeItem('dlj-import-active')
      setBusy(false)
    }
  }
  return <div className="page"><div className="eyebrow">01 / Onboarding</div><h1>Start with your labels.</h1><p className="subtitle">Upload an existing CSV. See its health first, then score labels into a review queue.</p><SignupBanner />
    <div className="card card-pad"><CsvDropzone key={dropzoneVersion} onFile={next => { void analyze(next) }} busy={busy} /><p className="muted">CSV requires at least 200 rows, label_id, category, verified outcome, and two numeric factor columns. The health report is free and does not save your data.</p>
      <button className="button secondary" onClick={trySample} disabled={busy}>Try with sample data</button><p className="muted">Explore 500 fictional medical labels without an API key.</p>
      {file && <p><strong>{file.name}</strong> <span className="muted">· {(file.size / 1024).toFixed(0)} KB</span></p>}
      {busy && <LoadingSpinner />}{progress > 0 && <p className="muted">Scored {progress} rows</p>}<ErrorBanner message={error} />
      {report && <div className="stack"><div className="success">Analysis ready · {report.metadata.row_count} labels · {report.metadata.verified_count} verified · {report.metadata.factor_count} factors</div>
        {report.warnings?.map((warning, index) => <div className="notice" key={index}>{warning}</div>)}
        <div className="button-row">{sample ? (hasApiKey() && <button className="button" onClick={scoreSample} disabled={busy}>Score 12 sample labels</button>) : <button className="button" onClick={startScoring} disabled={busy || !domainId}>Start scoring these labels</button>}<button className="button secondary" onClick={() => { if (file) navigate('/health', { state: { reportRef: storeReportFile(file) } }) }}>View full report</button></div>
        <p className="muted">{sample ? 'Scoring uses 12 labels of your plan quota and requires a labeling API key. The report shows synthetic historical outcomes; live labels remain pending until you verify them.' : 'Scoring creates pending review items in batches of 100. Verification outcomes in this CSV are used for the report; they are not imported into live training.'}</p>
      </div>}
    </div>
    <section className="card card-pad" style={{ marginTop: 18 }}><h2 className="section-title">Create a text task</h2><p className="muted">Add source text for the active domain. Leave category blank to classify it in review, or enter a category to score it now.</p>
      <label className="field">Label ID<input value={taskId} onChange={event => setTaskId(event.target.value)} /></label>
      <label className="field">Source text<textarea value={taskText} onChange={event => setTaskText(event.target.value)} rows={5} /></label>
      <label className="field">Category (optional)<input value={taskCategory} onChange={event => setTaskCategory(event.target.value)} /></label>
      <button className="button" onClick={() => void createTask()} disabled={busy || !hasApiKey()}>Create text task</button>
    </section>
  </div>
}
