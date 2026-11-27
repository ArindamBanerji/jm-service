import { useRef, useState } from 'react'
export default function CsvDropzone({ onFile, busy = false, allowJson = false }: { onFile: (file: File) => void; busy?: boolean; allowJson?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [active, setActive] = useState(false)
  const accept = (file?: File) => { if (file && !busy) onFile(file) }
  return <div className={`dropzone ${active ? 'active' : ''}`} onDragOver={event => { event.preventDefault(); if (!busy) setActive(true) }} onDragLeave={() => setActive(false)} onDrop={event => { event.preventDefault(); setActive(false); accept(event.dataTransfer.files[0]) }}>
    <div style={{ fontSize: 32 }} aria-hidden>↥</div><strong>Drop a {allowJson ? 'CSV or JSON' : 'CSV'} here</strong><span>or choose a file from your computer</span>
    <button className="button secondary" disabled={busy} onClick={() => input.current?.click()}>Choose {allowJson ? 'CSV or JSON' : 'CSV'}</button>
    <input ref={input} hidden type="file" accept={allowJson ? '.csv,.json,text/csv,application/json' : '.csv,text/csv'} onChange={event => accept(event.target.files?.[0])} />
  </div>
}
