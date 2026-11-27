import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Papa from 'papaparse'
import { createTextTask, hasApiKey, ingestBatch, seedSample, uploadForAnalysis, type HealthReport, type IngestItem } from '../api'
import { parseIngestFile } from '../csv'
import { useDomain } from '../domain'
import CsvDropzone from '../components/CsvDropzone'
import ErrorBanner from '../components/ErrorBanner'
import LoadingSpinner from '../components/LoadingSpinner'
import SignupBanner from '../components/SignupBanner'
import { storeReportFile } from '../reportHandoff'
import { captureOperation } from '../operationContext'

export default function Upload() {
  const { domainId, setDomainId, projectId, project, projectsLoaded } = useDomain()
  const path = (page: string) => `${projectId ? `/projects/${encodeURIComponent(projectId)}` : ''}/${page}`
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
  const [preparedRows, setPreparedRows] = useState<IngestItem[] | null>(null)
  const importController = useRef<AbortController | null>(null)
  const importCounts = useRef({ committed: 0, total: 0 })
  const analysisRun = useRef(0)
  const clearUpload = () => {
    ++analysisRun.current
    setFile(null); setReport(null); setPreparedRows(null); setProgress(0); setSample(false)
    setTaskId(''); setTaskText(''); setTaskCategory('')
    setDropzoneVersion(value => value + 1)
  }
  useEffect(() => {
    const accountChanging = () => {
      const active = importController.current
      active?.abort()
      importController.current = null
      sessionStorage.removeItem('dlj-import-active')
      clearUpload(); setBusy(false); setError(null)
      if (active) setError(`Import stopped: account changed during upload. ${importCounts.current.committed} of ${importCounts.current.total} rows were committed to the original account.`)
      importCounts.current = { committed: 0, total: 0 }
    }
    window.addEventListener('dlj-account-changing', accountChanging)
    window.addEventListener('dlj-project-changing', accountChanging)
    return () => {
      window.removeEventListener('dlj-account-changing', accountChanging)
      window.removeEventListener('dlj-project-changing', accountChanging)
      ++analysisRun.current
      importController.current?.abort()
    }
  }, [])
  const createTask = async () => {
    if (!domainId || !taskId.trim() || !taskText) { setError('Enter a domain, label ID and source text.'); return }
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      await createTextTask(domainId, { label_id: taskId.trim(), text: taskText, category: taskCategory.trim() || undefined }, operation.credential ?? undefined, operation.signal, projectId)
      if (operation.isCurrent()) navigate(path(`review/${encodeURIComponent(taskId.trim())}`))
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) } finally { operation.finish(); setBusy(false) }
  }
  const analyze = async (next: File, isSample = false) => {
    const run = ++analysisRun.current
    const operation = captureOperation(domainId, projectId)
    setSample(isSample); setFile(next); setReport(null); setError(null); setBusy(true); setProgress(0)
    try { const result = await uploadForAnalysis(next, operation.signal); if (operation.isCurrent() && run === analysisRun.current) setReport(result) }
    catch (cause) { if (run === analysisRun.current) setError(String(cause)) }
    finally { if (run === analysisRun.current) setBusy(false); operation.finish() }
  }
  const chooseFile = async (next: File) => {
    if (!projectId || project?.content_type !== 'image') { await analyze(next); return }
    const run = ++analysisRun.current
    setFile(next); setReport(null); setPreparedRows(null); setError(null); setBusy(true); setProgress(0); setSample(false)
    try {
      const rows = await parseIngestFile(next, 'image')
      if (run === analysisRun.current) setPreparedRows(rows)
    } catch (cause) { if (run === analysisRun.current) { setFile(null); setError(String(cause)) } }
    finally { if (run === analysisRun.current) setBusy(false) }
  }
  const trySample = async () => {
    const run = analysisRun.current
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      const response = await fetch('/demo/sample_data.json', { signal: operation.signal })
      if (run !== analysisRun.current || !operation.isCurrent()) return
      if (!response.ok) throw new Error('Sample data could not be loaded')
      const fixture = await response.json() as { domain_id: string; rows: Record<string, unknown>[] }
      if (run !== analysisRun.current || !operation.isCurrent()) return
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
    } catch (cause) { if (operation.isCurrent() && run === analysisRun.current) { setError(String(cause)); setBusy(false) } }
    finally { operation.finish() }
  }
  const scoreSample = async () => {
    if (!hasApiKey()) { setError('Enter a labeling API key in the sidebar to score 12 sample labels.'); return }
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      const result = await seedSample('medical-ner-demo-v1', operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      setDomainId(result.domain_id)
      navigate('/queue')
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) } finally { operation.finish(); setBusy(false) }
  }
  const startScoring = async () => {
    if (!file || !domainId) { setError('Enter an active domain ID in the sidebar.'); return }
    const operation = captureOperation(domainId, projectId)
    const capturedKey = operation.credential
    if (!capturedKey) { operation.finish(); setError('Enter an API key before importing labels.'); return }
    const controller = new AbortController()
    operation.signal.addEventListener('abort', () => controller.abort(), { once: true })
    importController.current = controller
    sessionStorage.setItem('dlj-import-active', '1')
    let committed = 0
    let total = 0
    importCounts.current = { committed, total }
    setBusy(true); setError(null)
    try {
      const rows = preparedRows ?? await parseIngestFile(file, project?.content_type ?? 'text')
      total = rows.length
      if (!operation.isCurrent() || controller.signal.aborted) return
      importCounts.current.total = total
      for (let start = 0; start < rows.length;) {
        if (controller.signal.aborted || !operation.isCurrent()) {
          clearUpload()
          setError(`Import stopped: account changed during upload. ${committed} of ${rows.length} rows were committed to the original account.`)
          return
        }
        let end = Math.min(start + 100, rows.length)
        if (project?.content_type === 'image') {
          let decoded = 0
          for (let i = start; i < end; i++) {
            const uri = rows[i].content?.image_url
            if (!uri?.startsWith('data:')) continue
            const length = uri.length - uri.indexOf(',') - 1
            decoded += length / 4 * 3 - (uri.endsWith('==') ? 2 : uri.endsWith('=') ? 1 : 0)
            if (decoded > 10 * 1024 * 1024) {
              if (i === start) throw new Error(`Row ${i + 2}: Embedded images exceed 10 MiB`)
              end = i
              break
            }
          }
          // Count the bytes of the actual JSON envelope (including escaped captions).
          while (new TextEncoder().encode(JSON.stringify({
            request_key: `${operation.operationId}-${start}`, items: rows.slice(start, end),
          })).length > 20 * 1024 * 1024) {
            if (end === start + 1) throw new Error(`Row ${start + 2}: Media request exceeds 20 MiB`)
            end = start + Math.ceil((end - start) / 2)
          }
        }
        await ingestBatch({ domain_id: operation.domainId, items: rows.slice(start, end) }, capturedKey, controller.signal,
          projectId, `${operation.operationId}-${start}`)
        if (!operation.isCurrent()) return
        start = end
        committed = end
        importCounts.current.committed = committed
        setProgress(committed)
      }
      if (controller.signal.aborted || !operation.isCurrent()) {
        clearUpload()
        setError(`Import stopped: account changed during upload. ${committed} of ${rows.length} rows were committed to the original account.`)
        return
      }
      navigate(path('queue'))
    } catch (cause) {
      if (operation.isCurrent() && !controller.signal.aborted) {
        const rowError = String(cause).replace(/Item (\d+):/g, (_, value: string) => `Row ${Number(value) + 2}:`)
        setError(`${rowError}${committed ? ` (${committed} rows already ingested)` : ''}`)
      }
    } finally {
      if (importController.current === controller) {
        importController.current = null
        sessionStorage.removeItem('dlj-import-active')
        setBusy(false)
      }
      operation.finish()
    }
  }
  const imageProject = Boolean(projectId && project?.content_type === 'image')
  if (projectId && !projectsLoaded) return <div className="page"><LoadingSpinner /><p className="muted">Loading project media settings…</p></div>
  if (projectId && !project) return <div className="page"><ErrorBanner message="This project could not be loaded. Check your access and try again." /></div>
  return <div className="page"><div className="eyebrow">01 / Onboarding</div><h1>Start with your labels.</h1><p className="subtitle">{imageProject ? 'Import image URLs and captions directly into this project.' : 'Upload an existing CSV. See its health first, then score labels into a review queue.'}</p><SignupBanner />
    <div className="card card-pad"><CsvDropzone key={dropzoneVersion} onFile={next => { void chooseFile(next) }} busy={busy} allowJson={imageProject} /><p className="muted">{imageProject ? 'CSV/JSON requires label_id, category, item_media_url, optional item_text, and at least two numeric factor columns. Imports are authenticated and processed in chunks of 100.' : 'CSV requires at least 200 rows, label_id, category, verified outcome, and two numeric factor columns. The health report is free and does not save your data.'}</p>
      {imageProject ? <div className="notice">External images load from their original host during review, which shares the reviewer&apos;s IP address with that host. Image files are never sent to anonymous report analysis.</div> : <><button className="button secondary" onClick={trySample} disabled={busy}>Try with sample data</button><p className="muted">Explore 500 fictional medical labels without an API key.</p></>}
      {file && <p><strong>{file.name}</strong> <span className="muted">· {(file.size / 1024).toFixed(0)} KB</span></p>}
      {busy && <LoadingSpinner />}{progress > 0 && <p className="muted">Scored {progress} rows</p>}<ErrorBanner message={error} />
      {imageProject && preparedRows && <div className="image-import-preview" aria-label="Image import preview"><div className="success">{preparedRows.length} image items ready to import</div>{preparedRows.slice(0, 5).map(row => <div key={row.label_id} className="image-import-row"><strong>{row.text || row.label_id}</strong><span className="pill">Image URL</span></div>)}{preparedRows.length > 5 && <p className="muted">+ {preparedRows.length - 5} more rows</p>}<button className="button" onClick={startScoring} disabled={busy || !domainId}>Import image labels</button></div>}
      {report && <div className="stack"><div className="success">Analysis ready · {report.metadata.row_count} labels · {report.metadata.verified_count} verified · {report.metadata.factor_count} factors</div>
        {report.warnings?.map((warning, index) => <div className="notice" key={index}>{warning}</div>)}
        <div className="button-row">{sample ? (hasApiKey() && <button className="button" onClick={scoreSample} disabled={busy}>Score 12 sample labels</button>) : <button className="button" onClick={startScoring} disabled={busy || !domainId}>Start scoring these labels</button>}<button className="button secondary" onClick={() => { if (file) navigate('/health', { state: { reportRef: storeReportFile(file) } }) }}>View full report</button></div>
        <p className="muted">{sample ? 'Scoring uses 12 labels of your plan quota and requires a labeling API key. The report shows synthetic historical outcomes; live labels remain pending until you verify them.' : 'Scoring creates pending review items in batches of 100. Verification outcomes in this CSV are used for the report; they are not imported into live training.'}</p>
      </div>}
    </div>
    {!imageProject && <section className="card card-pad" style={{ marginTop: 18 }}><h2 className="section-title">Create a text task</h2><p className="muted">Add source text for the active domain. Leave category blank to classify it in review, or enter a category to score it now.</p>
      <label className="field">Label ID<input value={taskId} onChange={event => setTaskId(event.target.value)} /></label>
      <label className="field">Source text<textarea value={taskText} onChange={event => setTaskText(event.target.value)} rows={5} /></label>
      <label className="field">Category (optional)<input value={taskCategory} onChange={event => setTaskCategory(event.target.value)} /></label>
      <button className="button" onClick={() => void createTask()} disabled={busy || !hasApiKey()}>Create text task</button>
    </section>}
  </div>
}
