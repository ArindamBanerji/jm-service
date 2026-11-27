import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError, fetchCapabilities, getProject, inviteProjectMember, updateProject,
  type ContentType, type ProjectCapabilities, type ProjectSummary } from '../api'
import ErrorBanner from '../components/ErrorBanner'
import { useDomain } from '../domain'
import { captureOperation } from '../operationContext'
import GuidelinesPanel from '../components/GuidelinesPanel'

export default function ProjectSettings() {
  const { projectId = '' } = useParams()
  const { domainId } = useDomain()
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [description, setDescription] = useState('')
  const [contentType, setContentType] = useState<ContentType>('text')
  const [capabilities, setCapabilities] = useState<ProjectCapabilities | null>(null)
  const [guidelines, setGuidelines] = useState('')
  const [guidelineDraft, setGuidelineDraft] = useState('')
  const [editingGuidelines, setEditingGuidelines] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'admin' | 'reviewer' | 'annotator'>('reviewer')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const key = localStorage.getItem('rgi-api-key')
    setProject(null); setError(null); setDescription(''); setGuidelines(''); setGuidelineDraft(''); setEditingGuidelines(false); setEmail('')
    setCapabilities(null)
    void getProject(projectId, controller.signal).then(async value => {
      if (controller.signal.aborted || localStorage.getItem('rgi-api-key') !== key) return
      setProject(value); setContentType(value.content_type ?? 'text')
      setDescription(value.description ?? ''); setGuidelines(value.guidelines ?? ''); setGuidelineDraft(value.guidelines ?? '')
      if (value.content_type && !value.modality_locked && (value.role === 'owner' || value.role === 'admin')) {
        const enabled = await fetchCapabilities(controller.signal)
        if (!controller.signal.aborted && localStorage.getItem('rgi-api-key') === key) setCapabilities(enabled)
      }
    }).catch(cause => { if (!controller.signal.aborted) setError(String(cause)) })
    const clear = () => { controller.abort(); setProject(null); setCapabilities(null); setContentType('text'); setDescription(''); setGuidelines(''); setGuidelineDraft(''); setEditingGuidelines(false); setEmail('') }
    window.addEventListener('dlj-account-changing', clear)
    return () => { controller.abort(); window.removeEventListener('dlj-account-changing', clear) }
  }, [projectId])
  const save = async () => {
    if (!project || busy) return
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      await updateProject(projectId, project.settings_version, {
        description,
        ...(contentType !== (project.content_type ?? 'text') ? { content_type: contentType, label_schema: 'single' as const } : {}),
      }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      const fresh = await getProject(projectId, operation.signal, operation.credential ?? undefined)
      if (!operation.isCurrent()) return
      setProject(fresh); setContentType(fresh.content_type ?? 'text'); setNotice('Project settings saved.')
    } catch (cause) {
      if (!operation.isCurrent()) return
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          const fresh = await getProject(projectId, operation.signal, operation.credential ?? undefined)
          if (operation.isCurrent()) {
            setProject(fresh); setContentType(fresh.content_type ?? 'text')
            setNotice('Settings changed elsewhere. Review the current version before saving your draft.')
          }
        } catch (refreshError) { if (operation.isCurrent()) setError(String(refreshError)) }
      } else setError(String(cause))
    } finally { operation.finish(); setBusy(false) }
  }
  const invite = async () => {
    if (!email.trim() || busy) return
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null)
    try {
      await inviteProjectMember(projectId, email.trim(), role, operation.credential ?? undefined, operation.signal)
      if (operation.isCurrent()) { setEmail(''); setNotice('Invitation created.') }
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish(); setBusy(false) }
  }
  const saveGuidelines = async () => {
    if (!project || busy || new TextEncoder().encode(guidelineDraft).length > 10 * 1024) return
    const operation = captureOperation(domainId, projectId)
    setBusy(true); setError(null); setNotice('')
    try {
      await updateProject(projectId, project.settings_version, { guidelines: guidelineDraft || null }, operation.credential ?? undefined, operation.signal)
      if (!operation.isCurrent()) return
      const fresh = await getProject(projectId, operation.signal, operation.credential ?? undefined)
      if (!operation.isCurrent()) return
      setProject(fresh); setGuidelines(fresh.guidelines ?? ''); setGuidelineDraft(fresh.guidelines ?? '')
      setEditingGuidelines(false); setNotice('Guidelines saved.')
    } catch (cause) { if (operation.isCurrent()) setError(String(cause)) }
    finally { operation.finish(); setBusy(false) }
  }
  const canAdmin = project?.role === 'owner' || project?.role === 'admin'
  return <div className="page"><div className="eyebrow">Project</div><h1>Project settings</h1><ErrorBanner message={error} />
    {notice && <p className="success" role="status">{notice}</p>}{project && <><div className="card card-pad">
      <h2>{project.name}</h2><p className="muted">{project.public_domain_id} · {project.status} · {project.role}</p>
      <label className="field">Description<textarea value={description} maxLength={10000} onChange={event => setDescription(event.target.value)} /></label>
      <div className="project-modality"><h3 className="section-title">Labeling modality</h3>
        {project.modality_locked ? <p><strong>Content type:</strong> {project.content_type ?? 'text'} · <strong>Label schema:</strong> {project.label_schema ?? 'single'} <span className="pill">Locked after first item</span></p> : <>
          <label className="field">Content type<select value={contentType} disabled={!canAdmin || !capabilities} onChange={event => setContentType(event.target.value as ContentType)}><option value="text">Text</option>{(project.content_type === 'image' || capabilities?.combinations.some(pair => pair.content_type === 'image' && pair.label_schema === 'single')) && <option value="image">Image</option>}</select></label>
          <label className="field">Label schema<select value="single" disabled><option>Single</option></select></label>
          <p className="muted">Choose what reviewers will label. This locks after the first item.</p></>}
      </div>
      <button className="button" disabled={busy || !canAdmin} onClick={() => void save()}>Save project settings</button>
    </div><section className="card card-pad project-guidelines" style={{ marginTop: 20 }} aria-labelledby="project-guidelines-title"><div className="project-panel-head"><div><h2 id="project-guidelines-title">Guidelines</h2>{project.guidelines_updated_at && <p className="muted">Last updated: {new Date(project.guidelines_updated_at).toLocaleString()}</p>}</div>{canAdmin && !editingGuidelines && <button className="button secondary" onClick={() => { setGuidelineDraft(guidelines); setEditingGuidelines(true) }}>Edit</button>}</div>
      {editingGuidelines ? <><label className="field">Markdown guidelines<textarea aria-label="Markdown guidelines" rows={12} value={guidelineDraft} onChange={event => setGuidelineDraft(event.target.value)} /></label><div className="guideline-editor-meta"><span className={new TextEncoder().encode(guidelineDraft).length > 10 * 1024 ? 'error' : 'muted'}>{new TextEncoder().encode(guidelineDraft).length.toLocaleString()} / 10,240 bytes</span></div><div className="button-row"><button className="button" disabled={busy || new TextEncoder().encode(guidelineDraft).length > 10 * 1024} onClick={() => void saveGuidelines()}>Save guidelines</button><button className="button secondary" disabled={busy} onClick={() => { setGuidelineDraft(guidelines); setEditingGuidelines(false) }}>Cancel</button></div></> : <GuidelinesPanel guidelines={guidelines || null} />}
    </section><div className="card card-pad" style={{ marginTop: 20 }}><h2>Team</h2>
      <label className="field">Invitation email<input type="email" value={email} onChange={event => setEmail(event.target.value)} /></label>
      <label className="field">Role<select value={role} onChange={event => setRole(event.target.value as typeof role)}><option value="reviewer">Reviewer</option><option value="annotator">Annotator</option><option value="admin">Admin</option></select></label>
      <button className="button" disabled={busy || !email.trim() || (project.role !== 'owner' && project.role !== 'admin')} onClick={() => void invite()}>Invite member</button>
    </div></>}</div>
}
