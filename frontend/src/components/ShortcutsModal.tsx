import { useEffect, useRef } from 'react'

const groups = [
  ['Global', ['?', 'Show this help'], ['g u', 'Upload'], ['g q', 'Queue'],
    ['g d', 'Dashboard'], ['g s', 'Settings'], ['g h', 'Health report']],
  ['Queue', ['j / k', 'Move through labels'], ['Enter', 'Open focused label'],
    ['Ctrl+A', 'Select visible labels'], ['Esc', 'Clear selection']],
  ['Review', ['A', 'Approve'], ['O', 'Override'], ['E', 'Escalate']],
]

export default function ShortcutsModal({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null)
  useEffect(() => {
    dialog.current?.focus()
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
    }
    window.addEventListener('keydown', close, true)
    return () => window.removeEventListener('keydown', close, true)
  }, [onClose])
  return <div className="modal-backdrop" onMouseDown={event => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <div className="shortcuts-modal card" role="dialog" aria-modal="true"
      aria-label="Keyboard shortcuts" tabIndex={-1} ref={dialog}>
      <div className="button-row" style={{ justifyContent: 'space-between' }}>
        <h2>Keyboard shortcuts</h2><button className="button secondary" onClick={onClose}>Close</button>
      </div>
      <div className="shortcuts-grid">{groups.map(([title, ...entries]) =>
        <section key={title as string}><h3>{title}</h3>{entries.map(([key, label]) =>
          <div className="shortcut-row" key={key}><kbd>{key}</kbd><span>{label}</span></div>)}</section>)}</div>
    </div>
  </div>
}
