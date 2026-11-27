import { createContext, useContext } from 'react'
import type { ProjectSummary } from './api'
export interface DomainContext {
  domainId: string
  setDomainId: (value: string) => void
  projectId: string | null
  project: ProjectSummary | null
  projects: ProjectSummary[]
  projectError: boolean
  projectsLoaded: boolean
}
export const Domain = createContext<DomainContext>({ domainId: '', setDomainId: () => undefined, projectId: null, project: null, projects: [], projectError: false, projectsLoaded: false })
export const useDomain = () => useContext(Domain)
