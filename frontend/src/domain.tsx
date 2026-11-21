import { createContext, useContext } from 'react'
export interface DomainContext { domainId: string; setDomainId: (value: string) => void }
export const Domain = createContext<DomainContext>({ domainId: '', setDomainId: () => undefined })
export const useDomain = () => useContext(Domain)
