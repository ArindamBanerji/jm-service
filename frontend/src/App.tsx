import { Component, lazy, Suspense, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Domain } from './domain'
import { getProjects, type ProjectSummary } from './api'
import Upload from './screens/Upload'
import ScoredQueue from './screens/ScoredQueue'
import ReviewCard from './screens/ReviewCard'
import AnnotatorProfiles from './screens/AnnotatorProfiles'
import HealthReport from './screens/HealthReport'
import LoadingSpinner from './components/LoadingSpinner'
import Signup from './screens/Signup'
import Settings from './screens/Settings'
import Pricing from './screens/Pricing'
import KeyboardShortcuts from './components/KeyboardShortcuts'
import Projects from './screens/Projects'
import ProjectSettings from './screens/ProjectSettings'

const Dashboard = lazy(() => import('./screens/Dashboard'))
const GuidePage = lazy(() => import('./pages/GuidePage'))
const PredictionReviewPage = lazy(() => import('./pages/PredictionReviewPage'))
const IntegrationsSettingsPage = lazy(() => import('./pages/IntegrationsSettingsPage'))
const QuickstartPage = lazy(() => import('./pages/QuickstartPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))

class RouteBoundary extends Component<{ children: ReactNode; routeKey: string }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidUpdate(previous: { routeKey: string }) {
    if (this.state.failed && previous.routeKey !== this.props.routeKey) this.setState({ failed: false })
  }
  render() {
    if (this.state.failed) return <section className="card card-pad" role="alert"><h2>This screen could not be shown.</h2>
      <p>Refresh to try again. Navigation remains available in the sidebar.</p>
      <button className="button" onClick={() => window.location.reload()}>Retry</button></section>
    return this.props.children
  }
}

const links = [
  ['upload', 'Upload', '↥'], ['queue', 'Scored Queue', '☷'], ['dashboard', 'Dashboard', '◫'],
  ['annotators', 'Annotator Profiles', '♙'], ['health', 'Label Health Report', '◇'],
  ['settings', 'Settings', '⚙'],
]
export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [domainId, updateDomain] = useState(() => localStorage.getItem('rgi-domain') ?? '')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('rgi-api-key') ?? '')
  const activeKey = useRef(localStorage.getItem('rgi-api-key') ?? '')
  const [projectError, setProjectError] = useState(false)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectsLoaded, setProjectsLoaded] = useState(false)
  const [keyGeneration, setKeyGeneration] = useState(0)
  const projectId = /^\/projects\/([^/]+)/.exec(location.pathname)?.[1] ?? null
  const project = projects.find(row => row.id === projectId)
  const inProjectDirectory = location.pathname === '/projects'
  const activeDomainId = projectId ? project?.public_domain_id ?? '' : domainId
  const previousRoute = useRef(location.pathname)
  useLayoutEffect(() => {
    if (previousRoute.current !== location.pathname) {
      previousRoute.current = location.pathname
      window.dispatchEvent(new Event('dlj-route-changing'))
    }
  }, [location.pathname])
  useEffect(() => {
    const controller = new AbortController()
    const key = localStorage.getItem('rgi-api-key')
    setProjectError(false)
    setProjectsLoaded(false)
    if (!key) setProjectsLoaded(true)
    else void getProjects(controller.signal, key).then(rows => {
      if (!controller.signal.aborted && localStorage.getItem('rgi-api-key') === key) setProjects(rows)
    }).catch(() => { if (!controller.signal.aborted) setProjectError(true) })
      .finally(() => { if (!controller.signal.aborted) setProjectsLoaded(true) })
    return () => controller.abort()
  }, [keyGeneration, projectId, inProjectDirectory])
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('dlj-theme')
    return saved === 'light' || saved === 'dark' ? saved :
      window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('dlj-theme', theme)
  }, [theme])
  useEffect(() => {
    const applyKeyChange = (next: string) => {
      const importWasActive = sessionStorage.getItem('dlj-import-active') === '1'
      activeKey.current = next
      window.dispatchEvent(new Event('dlj-account-changing'))
      setProjects([]); setProjectsLoaded(false); setKeyGeneration(value => value + 1)
      sessionStorage.removeItem('dlj-checkout-pending')
      sessionStorage.removeItem('dlj-deferred-registration')
      Object.keys(sessionStorage).filter(key => key.startsWith('dlj-image-consent:')).forEach(key => sessionStorage.removeItem(key))
      if (location.pathname === '/signup') {
        setApiKey(next); updateDomain(''); localStorage.removeItem('rgi-domain')
        return
      }
      localStorage.removeItem('rgi-domain')
      if (location.pathname === '/upload' && importWasActive) {
        setApiKey(next); updateDomain('')
        return
      }
      window.location.hash = '#/upload'
      window.location.reload()
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'rgi-api-key') applyKeyChange(localStorage.getItem('rgi-api-key') ?? '')
      else if (event.key === null) applyKeyChange('')
    }
    const onLocalKeyUpdate = () => {
      const next = localStorage.getItem('rgi-api-key') ?? ''
      if (next !== activeKey.current) applyKeyChange(next)
    }
    window.addEventListener('dlj-key-updated', onLocalKeyUpdate)
    window.addEventListener('storage', onStorage)
    return () => { window.removeEventListener('dlj-key-updated', onLocalKeyUpdate); window.removeEventListener('storage', onStorage) }
  }, [location.pathname])
  const setDomainId = (value: string) => {
    if (value !== domainId && !window.dispatchEvent(new Event('dlj-before-project-change', { cancelable: true }))) return
    if (value !== domainId) window.dispatchEvent(new Event('dlj-project-changing'))
    updateDomain(value); localStorage.setItem('rgi-domain', value)
  }
  const commitKey = () => {
    if (apiKey === activeKey.current) return
    if (apiKey) localStorage.setItem('rgi-api-key', apiKey)
    else localStorage.removeItem('rgi-api-key')
    window.dispatchEvent(new Event('dlj-key-updated'))
  }
  const root = projectId ? `/projects/${encodeURIComponent(projectId)}` : ''
  return <Domain.Provider value={{ domainId: activeDomainId, setDomainId, projectId, project: project ?? null, projects, projectError, projectsLoaded }}>
    <KeyboardShortcuts />
    <div className="shell">
      <button className="mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle navigation">☰</button>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="brand"><span className="brand-mark">RGI</span><div><strong>Data Label Judgment</strong><small>Verification workspace</small></div></div>
        <label className="sidebar-label" htmlFor="domain">ACTIVE DOMAIN</label>
        {projectId ? <div className="domain-input">{project?.name ?? 'Loading project…'}</div> :
          <input id="domain" className="domain-input" list="recent-domains" value={domainId} onChange={event => setDomainId(event.target.value.trim())} placeholder="Enter domain ID" />}
        <label className="sidebar-label" htmlFor="project-chooser">PROJECT</label>
        <select id="project-chooser" className="domain-input" value={projectId ?? ''} onChange={event => { navigate(event.target.value ? `/projects/${encodeURIComponent(event.target.value)}/queue` : '/upload') }}>
          <option value="">Legacy domain</option>{projects.filter(row => row.public_domain_id).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>
        {projectId && projectError && <p role="alert">Projects could not be loaded. <button onClick={() => setKeyGeneration(value => value + 1)}>Retry</button></p>}
        <NavLink to="/projects" className="nav-link">Manage projects</NavLink>
        <label className="sidebar-label" htmlFor="api-key">API KEY</label>
        <input id="api-key" className="domain-input" type="password" autoComplete="off" value={apiKey} onChange={event => setApiKey(event.target.value)} onBlur={commitKey} onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} placeholder="Enter your API key" />
        <datalist id="recent-domains">{domainId && <option value={domainId} />}</datalist>
        <nav aria-label="Main navigation">{links.map(([path, label, icon]) => <NavLink key={path} to={path === 'health' || path === 'settings' ? `/${path}` : `${root}/${path}`} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span aria-hidden>{icon}</span>{label}</NavLink>)}
          {projectId && <><NavLink to={`${root}/analytics`} className="nav-link">Analytics</NavLink><NavLink to={`${root}/predictions`} className="nav-link">Prediction review</NavLink><NavLink to={`${root}/settings`} className="nav-link">Project settings</NavLink><NavLink to={`${root}/integrations`} className="nav-link">Integrations</NavLink></>}
          <NavLink to="/quickstart" onClick={() => setMobileOpen(false)} className="nav-link">Quickstart</NavLink><NavLink to="/docs" onClick={() => setMobileOpen(false)} className="nav-link">Docs</NavLink></nav>
        <NavLink to="/signup" onClick={() => setMobileOpen(false)} className="button signup-link">Sign Up</NavLink>
        <footer className="sidebar-foot">
          <button className="theme-toggle" aria-label="Toggle dark mode" onClick={() => setTheme(value => value === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}</button><br />Review what matters.<br />Learn from every verified label.
          <p>Contact: <a href="mailto:support@dakshineshwari.net">support@dakshineshwari.net</a></p>
          <nav aria-label="Pricing and policies">
            <NavLink to="/pricing" onClick={() => setMobileOpen(false)}>Pricing</NavLink>
            <a href="/terms">Terms of Service</a>
            <a href="/privacy">Privacy Policy</a>
            <a href="/refund">Refund Policy</a>
          </nav>
        </footer>
      </aside>
      <main className="main"><RouteBoundary key={projectId ?? 'legacy'} routeKey={location.pathname}><Suspense fallback={<LoadingSpinner />}><Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/queue" element={<ScoredQueue />} />
        <Route path="/review/:labelId" element={<ReviewCard />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/annotators" element={<AnnotatorProfiles />} />
        <Route path="/health" element={<HealthReport />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/docs" element={<GuidePage />} />
        <Route path="/quickstart" element={<QuickstartPage />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId/upload" element={<Upload />} />
        <Route path="/projects/:projectId/queue" element={<ScoredQueue />} />
        <Route path="/projects/:projectId/review/:labelId" element={<ReviewCard />} />
        <Route path="/projects/:projectId/dashboard" element={<Dashboard />} />
        <Route path="/projects/:projectId/analytics" element={<AnalyticsPage />} />
        <Route path="/projects/:projectId/annotators" element={<AnnotatorProfiles />} />
        <Route path="/projects/:projectId/settings" element={<ProjectSettings />} />
        <Route path="/projects/:projectId/predictions" element={<PredictionReviewPage />} />
        <Route path="/projects/:projectId/integrations" element={<IntegrationsSettingsPage />} />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes></Suspense></RouteBoundary></main>
    </div>
  </Domain.Provider>
}
