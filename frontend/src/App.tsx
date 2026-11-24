import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { Domain } from './domain'
import Upload from './screens/Upload'
import ScoredQueue from './screens/ScoredQueue'
import ReviewCard from './screens/ReviewCard'
import AnnotatorProfiles from './screens/AnnotatorProfiles'
import HealthReport from './screens/HealthReport'
import LoadingSpinner from './components/LoadingSpinner'
import Signup from './screens/Signup'

const Dashboard = lazy(() => import('./screens/Dashboard'))

const links = [
  ['upload', 'Upload', '↥'], ['queue', 'Scored Queue', '☷'], ['dashboard', 'Dashboard', '◫'],
  ['annotators', 'Annotator Profiles', '♙'], ['health', 'Label Health Report', '◇'],
]
export default function App() {
  const [domainId, updateDomain] = useState(() => localStorage.getItem('rgi-domain') ?? '')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('rgi-api-key') ?? '')
  useEffect(() => {
    const refreshKey = () => setApiKey(localStorage.getItem('rgi-api-key') ?? '')
    window.addEventListener('dlj-key-updated', refreshKey)
    window.addEventListener('storage', refreshKey)
    return () => { window.removeEventListener('dlj-key-updated', refreshKey); window.removeEventListener('storage', refreshKey) }
  }, [])
  const setDomainId = (value: string) => { updateDomain(value); localStorage.setItem('rgi-domain', value) }
  return <Domain.Provider value={{ domainId, setDomainId }}>
    <div className="shell">
      <button className="mobile-menu" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle navigation">☰</button>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
        <div className="brand"><span className="brand-mark">RGI</span><div><strong>Data Label Judgment</strong><small>Verification workspace</small></div></div>
        <label className="sidebar-label" htmlFor="domain">ACTIVE DOMAIN</label>
        <input id="domain" className="domain-input" list="recent-domains" value={domainId} onChange={event => setDomainId(event.target.value.trim())} placeholder="Enter domain ID" />
        <label className="sidebar-label" htmlFor="api-key">API KEY</label>
        <input id="api-key" className="domain-input" type="password" autoComplete="off" value={apiKey} onChange={event => { setApiKey(event.target.value); localStorage.setItem('rgi-api-key', event.target.value) }} placeholder="Enter your API key" />
        <datalist id="recent-domains">{domainId && <option value={domainId} />}</datalist>
        <nav aria-label="Main navigation">{links.map(([path, label, icon]) => <NavLink key={path} to={`/${path}`} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><span aria-hidden>{icon}</span>{label}</NavLink>)}</nav>
        <NavLink to="/signup" onClick={() => setMobileOpen(false)} className="button signup-link">Sign Up</NavLink>
        <div className="sidebar-foot">Review what matters.<br />Learn from every verified label.</div>
      </aside>
      <main className="main"><Suspense fallback={<LoadingSpinner />}><Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/queue" element={<ScoredQueue />} />
        <Route path="/review/:labelId" element={<ReviewCard />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/annotators" element={<AnnotatorProfiles />} />
        <Route path="/health" element={<HealthReport />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes></Suspense></main>
    </div>
  </Domain.Provider>
}
