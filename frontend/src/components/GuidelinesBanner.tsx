import { useEffect, useState } from 'react'
import { getGuidelines } from '../api'
import { captureOperation } from '../operationContext'
import { MarkdownContent } from './GuidelinesPanel'

export default function GuidelinesBanner({ domainId, projectId }: { domainId: string; projectId: string | null }) {
  const storageKey = `dlj-guidelines-collapsed:${projectId ?? domainId}`
  const [guidelines, setGuidelines] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(storageKey) !== 'false')
  useEffect(() => {
    setGuidelines(null)
    setCollapsed(localStorage.getItem(storageKey) !== 'false')
    if (!domainId) return
    const operation = captureOperation(domainId, projectId)
    getGuidelines(domainId, operation.signal, projectId, operation.credential ?? undefined)
      .then(result => { if (operation.isCurrent()) setGuidelines(result.guidelines) })
      .catch(() => { if (operation.isCurrent()) setGuidelines(null) })
      .finally(operation.finish)
    return operation.finish
  }, [domainId, projectId, storageKey])
  if (!guidelines) return null
  const lines = guidelines.split('\n')
  const displayed = collapsed ? lines.slice(0, 2).join('\n') : guidelines
  const toggle = () => setCollapsed(value => {
    localStorage.setItem(storageKey, value ? 'false' : 'true')
    return !value
  })
  return <aside className="guidelines-banner" aria-label="Project annotation guidelines">
    <div><strong>Annotation guidelines</strong><MarkdownContent source={displayed} /></div>
    {lines.length > 2 && <button className="button secondary" type="button" aria-expanded={!collapsed}
      onClick={toggle}>{collapsed ? 'Show full guidelines' : 'Collapse guidelines'}</button>}
  </aside>
}
