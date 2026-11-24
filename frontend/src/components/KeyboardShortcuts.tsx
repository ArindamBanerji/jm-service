import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ShortcutsModal from './ShortcutsModal'

export default function KeyboardShortcuts() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const waiting = useRef(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement || (target instanceof HTMLElement && target.isContentEditable)
      if (editing || event.altKey || event.ctrlKey || event.metaKey || event.repeat) {
        waiting.current = false
        return
      }
      if (open) {
        if (event.key === '?') { event.preventDefault(); setOpen(false) }
        if (event.key !== 'Escape') event.stopPropagation()
        return
      }
      if (event.key === '?') {
        event.preventDefault()
        setOpen(true)
        return
      }
      if (waiting.current) {
        waiting.current = false
        window.clearTimeout(timer.current)
        const route: Record<string, string> = {
          u: '/upload', q: '/queue', d: '/dashboard', s: '/settings', h: '/health',
        }
        if (route[event.key.toLowerCase()]) {
          event.preventDefault()
          event.stopPropagation()
          navigate(route[event.key.toLowerCase()])
        }
        return
      }
      if (event.key.toLowerCase() === 'g') {
        waiting.current = true
        timer.current = window.setTimeout(() => { waiting.current = false }, 1000)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('keydown', onKey, true); window.clearTimeout(timer.current) }
  }, [navigate, open])
  return open && <ShortcutsModal onClose={() => setOpen(false)} />
}
