import { useRef, useState } from 'react'
export default function CsvDropzone({ onFile, busy = false }: { onFile: (file: File) => void; busy?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [active, setActive] = useState(false)
  const accept = (file?: File) => { if (file) onFile(file) }
  return <div className={`dropzone ${active ? 'active' : ''}`} onDragOver={event => { event.preventDefault(); setActive(true) }} onDragLeave={() => setActive(false)} onDrop={event => { event.preventDefault(); setActive(false); accept(event.dataTransfer.files[0]) }}>
    <div style={{ fontSize: 32 }} aria-hidden>↥</div><strong>Drop a CSV here</strong><span>or choose a file from your computer</span>
    <button className="button secondary" disabled={busy} onClick={() => input.current?.click()}>Choose CSV</button>
    <input ref={input} hidden type="file" accept=".csv,text/csv" onChange={event => accept(event.target.files?.[0])} />
  </div>
}
