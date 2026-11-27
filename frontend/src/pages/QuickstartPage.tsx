import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { createProject, ingestBatch, verifyLabel, type IngestResponse, type ProjectSummary } from '../api'
import ErrorBanner from '../components/ErrorBanner'

import Papa from 'papaparse'
import { captureOperation, type OperationContext } from '../operationContext'

const EXAMPLES = `AI chip demand lifts technology shares
Small businesses prepare for holiday shoppers
Home team wins the championship final
Researchers discover a promising battery material
Cloud software company announces new tools`
const FACTORS = ['clarity', 'relevance', 'specificity', 'evidence', 'consistency', 'urgency']

export default function QuickstartPage() {
  const [step, setStep] = useState(1)
  const [name, setName] = useState('Quickstart Demo')
  const [categoryText, setCategoryText] = useState('Technology, Business, Sports, Science')
  const [source, setSource] = useState(EXAMPLES)
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [results, setResults] = useState<IngestResponse[]>([])
  const [selected, setSelected] = useState<IngestResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const categories = useMemo(() => categoryText.split(',').map(value => value.trim()).filter(Boolean), [categoryText])

  const batchKey = useRef(crypto.randomUUID())
  const pending = useRef<OperationContext | null>(null)
  const fileRead = useRef<FileReader | null>(null)
  const [readingFile, setReadingFile] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => () => {
    pending.current?.finish(); pending.current = null
    if (fileRead.current) { fileRead.current.onloadend = null; fileRead.current.abort() }
  }, [])
  useEffect(() => { if (step > 1) heading.current?.focus() }, [step])
  const run = async (work: (op: OperationContext) => Promise<void>) => {
    if (pending.current) return
    const op = captureOperation(localStorage.getItem('rgi-domain') ?? '', null)
    pending.current = op
    setBusy(true); setError(null)
    try { await work(op) }
    catch (cause) { if (op.isCurrent()) setError(String(cause)) }
    finally {
      if (pending.current === op) { pending.current = null; setBusy(false) }
      op.finish()
    }
  }
  const create = () => run(async op => {
    if (!name.trim() || !categories.length) return
    const created = await createProject({ name: name.trim(), public_domain_id: `quickstart-${crypto.randomUUID()}`,
      factors: FACTORS, categories, actions: ['approve', 'reject'], content_type: 'text', label_schema: 'single' }, op.credential ?? undefined, op.signal)
    if (op.isCurrent()) { setProject(created); setStep(2) }
  })
  const lines = useMemo(() => source.split(/\r?\n/).map(value => value.trim()).filter(Boolean), [source])
  const changeSource = (value: string) => { batchKey.current = crypto.randomUUID(); setSource(value) }
  const upload = () => run(async op => {
    if (!project?.public_domain_id) return
    if (lines.length < 1 || lines.length > 100) { setError('Enter between 1 and 100 items.'); return }
    const response = await ingestBatch({ domain_id: project.public_domain_id, items: lines.map((text, index) => ({
      label_id: `quickstart-${index + 1}`, category: categories[index % categories.length], text,
      factors: Object.fromEntries(FACTORS.map((factor, factorIndex) => [factor, .35 + ((index + factorIndex) % 6) * .1])),
    })) }, op.credential ?? undefined, op.signal, project.id, batchKey.current)
    if (op.isCurrent()) { setResults(response.results); setStep(3) }
  })
  const choose = (item: IngestResponse) => { setSelected(item); setStep(4) }
  const verify = (correct: boolean) => run(async op => {
    if (!project?.public_domain_id || !selected) return
    await verifyLabel({ domain_id: project.public_domain_id, label_id: selected.label_id,
      actual_action: correct ? 'approve' : 'reject', verified_outcome: correct },
      op.credential ?? undefined, op.signal, project.id)
    if (op.isCurrent()) setStep(5)
  })
  const loadCsv = (file: File | undefined) => {
    if (!file) return
    fileRead.current?.abort()
    setReadingFile(false)
    if (file.size > 1024 * 1024) { setError('Choose a CSV under 1 MiB.'); return }
    const reader = new FileReader()
    fileRead.current = reader
    setReadingFile(true)
    reader.onloadend = () => { if (fileRead.current === reader) setReadingFile(false) }
    reader.onload = () => {
      const parsed = Papa.parse<string[]>(String(reader.result ?? ''), { skipEmptyLines: 'greedy', delimiter: ',' })
      const values = parsed.data.map(row => row[0]?.trim() ?? '')
      if (parsed.errors.length || values.some(value => !value || /[\r\n]/.test(value))) {
        setError('Use one text item per CSV row in the first column.'); return
      }
      setError(null); changeSource(values.join('\n'))
    }
    reader.onerror = () => setError('The CSV could not be read.')
    reader.readAsText(file)
  }

  return <div className="page quickstart-page"><div className="eyebrow">First five minutes</div><h1>Quickstart</h1>
    <p className="subtitle">Create a real demo project, score sample labels, and teach the engine with one verification.</p>
    <div className="quickstart-progress" aria-label={`Step ${step} of 5`}><strong>Step {step} of 5</strong><span><i style={{ width: `${step * 20}%` }} /></span></div>
    <ErrorBanner message={error} />
    <section className={`card card-pad quickstart-step ${step === 1 ? 'current' : ''}`}><div className="step-number">1</div><div><h2>Create your first project</h2>
      {step === 1 ? <div className="quickstart-form"><label className="field">Project name<input disabled={busy} value={name} maxLength={200} onChange={event => setName(event.target.value)} /></label>
        <label className="field">Categories<input disabled={busy} value={categoryText} onChange={event => setCategoryText(event.target.value)} aria-describedby="category-help" /></label><small id="category-help" className="muted">Separate categories with commas.</small>
        <button className="button" disabled={busy || !name.trim() || !categories.length} onClick={() => void create()}>{busy ? 'Creating…' : 'Create project'}</button></div> : <p className="success">{project?.name} created ✓</p>}
    </div></section>
    {step >= 2 && <section className={`card card-pad quickstart-step ${step === 2 ? 'current' : ''}`}><div className="step-number">2</div><div><h2 ref={step === 2 ? heading : undefined} tabIndex={-1}>Upload sample data</h2>
      {step === 2 ? <><label className="field">One item per line<textarea rows={7} disabled={busy} value={source} onChange={event => { fileRead.current?.abort(); changeSource(event.target.value) }} /></label>
        <div className="button-row"><button className="button secondary" disabled={busy} onClick={() => fileRef.current?.click()}>Upload CSV</button><input ref={fileRef} hidden type="file" accept=".csv,text/csv" onChange={event => loadCsv(event.target.files?.[0])} /><button className="button" disabled={busy || readingFile} onClick={() => void upload()}>{busy ? 'Uploading…' : 'Upload'}</button></div></> : <p className="success">{results.length} {results.length === 1 ? 'item' : 'items'} uploaded ✓</p>}
    </div></section>}
    {step >= 3 && <section className={`card card-pad quickstart-step ${step === 3 ? 'current' : ''}`}><div className="step-number">3</div><div><h2 ref={step === 3 ? heading : undefined} tabIndex={-1}>See your first score</h2><p className="muted">Every label gets scored in real-time against 6 learned factors.</p>
      <div className="quickstart-items">{results.map((item, index) => <button disabled={busy || step === 5} key={item.label_id} className={selected?.label_id === item.label_id ? 'selected' : ''} onClick={() => choose(item)}><span>{lines[index]}</span><strong>{Math.round(item.confidence * 100)}% · {item.recommended_action}</strong></button>)}</div>
      {selected && <div className="quickstart-factors">{Object.entries(selected.factors_used).map(([factor, value]) => <div className="factor" key={factor}><div className="factor-top"><span>{factor}</span><strong>{Math.round(value * 100)}%</strong></div><div className="track"><div className="fill" style={{ width: `${value * 100}%` }} /></div></div>)}</div>}
    </div></section>}
    {step >= 4 && <section className={`card card-pad quickstart-step ${step === 4 ? 'current' : ''}`}><div className="step-number">4</div><div><h2 ref={step === 4 ? heading : undefined} tabIndex={-1}>Verify a label</h2>
      {step === 4 ? <><p>Is <strong>{selected?.category}</strong> the correct category for this item? Verify a correct label or revise an incorrect label.</p><div className="button-row"><button className="button" disabled={busy} onClick={() => void verify(true)}>Verify</button><button className="button secondary" disabled={busy} onClick={() => void verify(false)}>Revise</button></div></> : <p className="success">The engine just learned from your verification. Scores will improve.</p>}
    </div></section>}
    {step >= 5 && <section className="card card-pad quickstart-step current"><div className="step-number">5</div><div><h2 ref={step === 5 ? heading : undefined} tabIndex={-1}>What’s next</h2><div className="quickstart-links">
      <Link to={`/projects/${project?.id}/dashboard`}>Project dashboard →</Link><Link to={`/projects/${project?.id}/upload`}>Upload your real data →</Link><Link to="/docs?section=webhooks">Connect your pipeline →</Link><a href="/dlj_client.py" download>Download the Python client →</a><Link to="/docs?section=predictions">Set up predictions →</Link>
    </div></div></section>}
  </div>
}
