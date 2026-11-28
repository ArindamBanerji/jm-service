import { useEffect, useRef, useState } from 'react'
import { copyKey } from '../copyKey'

interface Props {
  value: string
  saved: string
  onChange: (value: string) => void
  onCommit: () => void
}

export default function SidebarKey({ value, saved, onChange, onCommit }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [visible, setVisible] = useState(false)
  const [feedback, setFeedback] = useState('')
  const configured = Boolean(saved) && saved === value
  useEffect(() => {
    if (!feedback) return
    const timer = window.setTimeout(() => setFeedback(''), 3500)
    return () => window.clearTimeout(timer)
  }, [feedback])
  useEffect(() => {
    if (!visible) return
    input.current?.focus()
    input.current?.select()
    const conceal = () => setVisible(false)
    window.addEventListener('blur', conceal)
    return () => window.removeEventListener('blur', conceal)
  }, [visible])
  const copy = async () => {
    const field = input.current
    if (!configured || !field || localStorage.getItem('rgi-api-key') !== saved) return
    const worked = await copyKey(field)
    if (field.isConnected && field.value === saved && localStorage.getItem('rgi-api-key') === saved) {
      setFeedback(worked ? 'Copied' : 'Key selected. Choose Show to copy manually.')
    }
  }
  return <>
    <label className="sidebar-label" htmlFor="api-key">API KEY</label>
    <input id="api-key" ref={input} className="domain-input" type={visible ? 'text' : 'password'}
      autoComplete="off" spellCheck={false} value={value} placeholder="Enter your API key"
      onChange={event => { setFeedback(''); setVisible(false); onChange(event.target.value) }}
      onClick={() => { if (!visible) void copy() }} onBlur={onCommit}
      onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} />
    {configured && <div className="button-row">
      <button type="button" className="theme-toggle" aria-label="Copy API key" onClick={() => void copy()}>Copy</button>
      <button type="button" className="theme-toggle" aria-pressed={visible} aria-label={visible ? 'Hide API key' : 'Show API key'}
        onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'}</button>
    </div>}
    {feedback && <small role="status">{feedback}</small>}
  </>
}
