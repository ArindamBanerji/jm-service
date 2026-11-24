import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { NerSpan } from '../api'
import NERViewer, { nerColor } from './NERViewer'

interface Props {
  text: string
  spans: NerSpan[]
  entityTypes: string[]
  onSpansChange: (spans: NerSpan[]) => void
  readOnly?: boolean
}
type Popup = { kind: 'create'; start: number; end: number; x: number; y: number } |
  { kind: 'edit'; index: number; x: number; y: number }

export default function NEREditor({ text, spans, entityTypes, onSpansChange, readOnly = false }: Props) {
  const root = useRef<HTMLDivElement>(null)
  const [popup, setPopup] = useState<Popup | null>(null)
  const [customType, setCustomType] = useState('')
  useEffect(() => { setPopup(null); setCustomType('') }, [text])
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setPopup(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])
  if (readOnly) return <NERViewer text={text} spans={spans} />

  const points = Array.from(text)
  const ordered = spans.map((span, index) => ({ span, index })).sort((a, b) => a.span.start - b.span.start || a.span.end - b.span.end)
  const segment = (value: string, start: number) => <span data-ner-segment data-start={start}><span data-ner-text>{value}</span></span>
  const parts: ReactNode[] = []
  let position = 0
  for (const { span, index } of ordered) {
    if (span.start > position) parts.push(<span key={`plain-${position}`}>{segment(points.slice(position, span.start).join(''), position)}</span>)
    const mention = points.slice(span.start, span.end).join('')
    parts.push(<mark key={`entity-${index}`} data-ner-segment data-start={span.start} tabIndex={0}
      aria-label={`${span.label}: ${mention}. Edit entity`}
      style={{ background: nerColor(span.label), color: '#172033', borderRadius: 4, padding: '2px 3px', boxDecorationBreak: 'clone', cursor: 'pointer' }}
      onClick={event => {
        if (!window.getSelection()?.isCollapsed) return
        setPopup({ kind: 'edit', index, x: event.clientX, y: event.clientY })
      }}
      onKeyDown={event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          const rect = event.currentTarget.getBoundingClientRect()
          setPopup({ kind: 'edit', index, x: rect.left, y: rect.bottom })
        }
      }}><span data-ner-text>{mention}</span><span aria-hidden="true" style={{ marginLeft: 4, fontSize: '0.7em', fontWeight: 700, userSelect: 'none' }}>{span.label}</span></mark>)
    position = span.end
  }
  if (position < points.length) parts.push(<span key={`plain-${position}`}>{segment(points.slice(position).join(''), position)}</span>)

  const offset = (node: Node, nodeOffset: number): number | null => {
    const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement
    const wrapper = element?.closest<HTMLElement>('[data-ner-segment]')
    if (!wrapper || !root.current?.contains(wrapper)) return null
    const start = Number(wrapper.dataset.start)
    const content = wrapper.querySelector<HTMLElement>('[data-ner-text]')
    if (!content) return null
    if (node === wrapper) return start + (nodeOffset === 0 ? 0 : Array.from(content.textContent ?? '').length)
    if (!content.contains(node)) return null
    const range = document.createRange()
    range.selectNodeContents(content)
    range.setEnd(node, nodeOffset)
    return start + Array.from(range.toString()).length
  }
  const selectionEnded = () => {
    const selection = window.getSelection()
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) return
    const range = selection.getRangeAt(0)
    const start = offset(range.startContainer, range.startOffset)
    const end = offset(range.endContainer, range.endOffset)
    if (start === null || end === null || start >= end ||
        spans.some(span => start < span.end && end > span.start)) return
    const rect = range.getBoundingClientRect()
    setPopup({ kind: 'create', start, end, x: rect.left, y: rect.bottom })
  }
  const update = (type: string) => {
    if (!popup || !type.trim()) return
    if (popup.kind === 'create') {
      onSpansChange([...spans, { start: popup.start, end: popup.end, label: type.trim(),
        text: points.slice(popup.start, popup.end).join('') }].sort((a, b) => a.start - b.start))
    } else {
      onSpansChange(spans.map((span, index) => index === popup.index ? { ...span, label: type.trim() } : span))
    }
    window.getSelection()?.removeAllRanges()
    setPopup(null); setCustomType('')
  }
  const remove = () => {
    if (popup?.kind !== 'edit') return
    onSpansChange(spans.filter((_, index) => index !== popup.index))
    setPopup(null)
  }
  const types = [...new Set(entityTypes)].filter(Boolean)
  const selected = popup?.kind === 'edit' ? spans[popup.index] : null
  return <section aria-label="Edit named entities" style={{ marginTop: 20 }}>
    <h3 className="section-title">Named entities</h3>
    <p className="muted">Drag to select text, then choose its entity type. Click a highlight to change or delete it.</p>
    <div ref={root} className="card-pad" onMouseUp={selectionEnded}
      style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: '#f7f9fc', borderRadius: 8, userSelect: 'text' }}>{parts}</div>
    {popup && <div className="ner-popup" role="dialog" aria-label={popup.kind === 'create' ? 'Choose entity type' : 'Edit entity'}
      style={{ left: Math.min(popup.x, window.innerWidth - 260), top: Math.min(popup.y + 8, window.innerHeight - 130) }}
      onMouseDown={event => event.preventDefault()}>
      <strong>{popup.kind === 'create' ? 'Entity type' : `Edit ${selected?.label ?? 'entity'}`}</strong>
      <div className="ner-popup-types">{types.map(type => <button key={type} type="button" style={{ background: nerColor(type) }} onClick={() => update(type)}>{type}</button>)}</div>
      {!types.length && <div className="ner-popup-custom"><input aria-label="Custom entity type" value={customType} maxLength={200} onChange={event => setCustomType(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') update(customType) }} /><button type="button" onClick={() => update(customType)} disabled={!customType.trim()}>Apply</button></div>}
      {popup.kind === 'edit' && <button type="button" className="ner-delete" onClick={remove}>Delete</button>}
    </div>}
  </section>
}
