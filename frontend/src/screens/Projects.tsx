import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createProject, fetchCapabilities, type ContentType, type ProjectCapabilities } from '../api'
import ErrorBanner from '../components/ErrorBanner'
import { useDomain } from '../domain'
import { captureOperation } from '../operationContext'

export default function Projects() {
  const navigate = useNavigate()
  const { domainId, projects, projectsLoaded, projectError } = useDomain()
  const [name, setName] = useState('')
  const [alias, setAlias] = useState('')
  const [factors, setFactors] = useState('factor_quality, factor_difficulty')
  const [categories, setCategories] = useState('default')
  const [contentType, setContentType] = useState<ContentType>('text')
  const [capabilities, setCapabilities] = useState<ProjectCapabilities | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const key = localStorage.getItem('rgi-api-key')
    if (!key) return
    const current = () => !controller.signal.aborted && localStorage.getItem('rgi-api-key') === key
    void fetchCapabilities(controller.signal).then(enabled => { if (current()) setCapabilities(enabled) })
      .catch(() => { if (current()) setError('Project creation options could not be loaded. Refresh to retry.') })
    const clear = () => { controller.abort(); setCapabilities(null); setName(''); setAlias(''); setContentType('text'); setError(null) }
    window.addEventListener('dlj-account-changing', clear)
    return () => { controller.abort(); window.removeEventListener('dlj-account-changing', clear) }
  }, [])
  const create = async () => {
    const key = localStorage.getItem('rgi-api-key')
    if (!key || busy) return
    const operation = captureOperation(domainId, null)
    setBusy(true); setError(null)
    try {
      const project = await createProject({ name: name.trim(), public_domain_id: alias.trim(),
        factors: factors.split(',').map(value => value.trim()).filter(Boolean),
        categories: categories.split(',').map(value => value.trim()).filter(Boolean),
        content_type: contentType, label_schema: 'single' }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      navigate(`/projects/${encodeURIComponent(project.id)}/queue`)
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish(); setBusy(false) }
  }
  return <div className="page"><div className="eyebrow">Workspace</div><h1>Projects</h1>
    <p className="subtitle">Choose a project to review its labels and settings.</p><ErrorBanner message={error} />
    {!projectsLoaded && <p role="status">Loading projects…</p>}
    {projectError && <p role="alert">Projects could not be loaded. <button onClick={() => window.location.reload()}>Retry</button></p>}
    {projectsLoaded && !projectError && !projects.length && <p className="muted">{localStorage.getItem('rgi-api-key') ? 'Create your first project below.' : 'Enter your API key to view your projects.'}</p>}
    <div className="stack">{projects.map(project => project.public_domain_id ? <Link className="card card-pad" key={project.id} to={`/projects/${encodeURIComponent(project.id)}/queue`}>
      <strong>{project.name} {project.content_type === 'image' && <span className="pill">Image</span>}</strong><p className="muted">{project.public_domain_id} · {project.status}</p></Link> :
      <div className="card card-pad" key={project.id}><strong>{project.name}</strong><p className="muted">Assign a public domain name in account Settings before opening this older project.</p></div>)}</div>
    <section className="card card-pad" style={{ marginTop: 20 }}><h2>Create project</h2>
      <label className="field">Project name<input value={name} maxLength={200} onChange={event => setName(event.target.value)} /></label>
      <label className="field">Public ID<input value={alias} maxLength={200} onChange={event => setAlias(event.target.value)} /></label>
      <label className="field">Factors, comma separated<input value={factors} onChange={event => setFactors(event.target.value)} /></label>
      <label className="field">Categories, comma separated<input value={categories} onChange={event => setCategories(event.target.value)} /></label>
      {capabilities?.combinations.some(pair => pair.content_type === 'image' && pair.label_schema === 'single') && <label className="field">Content type<select value={contentType} onChange={event => setContentType(event.target.value as ContentType)}><option value="text">Text</option><option value="image">Image</option></select></label>}
      <label className="field">Label schema<select value="single" disabled><option value="single">Single</option><option disabled>Multi — Coming soon</option><option disabled>NER — Coming soon</option></select></label>
      <p className="muted">Choose what reviewers will label. This locks after the first item.</p>
      {contentType === 'image' && <div className="notice">Upload items with image URLs. DLJ scores the annotator&apos;s category decisions, not the image content.</div>}
      <button className="button" disabled={busy || !name.trim() || !alias.trim()} onClick={() => void create()}>Create project</button>
    </section></div>
}
