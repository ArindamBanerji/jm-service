import { useEffect, useRef, useState } from 'react'
import type { PredictionItem } from '../api'
import NERViewer from './NERViewer'
import FactorBar from './FactorBar'
import ImageViewer from './ImageViewer'

interface Props {
  item: PredictionItem
  busy: boolean
  onAccept: (spansReviewed: boolean) => void
  onCorrect: (category: string, action: string, spansReviewed: boolean) => void
  onReopen: () => void
  onNext: () => void
  onPrevious: () => void
  onClose: () => void
}

export default function PredictionReviewCard(props: Props) {
  const { item, busy } = props
  const root = useRef<HTMLDivElement>(null)
  const [focused, setFocused] = useState(false)
  const [attested, setAttested] = useState<string | null>(null)
  const checked = attested === item.current_label_log_id
  const canReview = !busy && item.state !== 'human_reviewed' && (!item.spans.length || checked)
  const [correcting, setCorrecting] = useState(false)
  const [category, setCategory] = useState(item.category ?? item.categories[0] ?? '')
  const [action, setAction] = useState(item.action ?? item.actions[0] ?? '')
  useEffect(() => {
    setCorrecting(false); setCategory(item.category ?? item.categories[0] ?? '')
    setAction(item.action ?? item.actions[0] ?? '')
  }, [item])
  useEffect(() => {
    if (!focused) return
    const keydown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || event.repeat) return
      const target = event.target as HTMLElement | null
      if (target?.matches('input, select, textarea')) {
        if (event.key === 'Escape') { setCorrecting(false); root.current?.focus() }
        return
      }
      const key = event.key.toLowerCase()
      if (event.key === 'Escape') correcting ? setCorrecting(false) : props.onClose()
      else if (!correcting && canReview && key === 'a') props.onAccept(checked)
      else if (!busy && item.state !== 'human_reviewed' && key === 'c') setCorrecting(true)
      else if (!correcting && !busy && item.state !== 'pending' && key === 'r') props.onReopen()
      else if (key === 'n' || event.key === 'ArrowRight') props.onNext()
      else if (key === 'p' || event.key === 'ArrowLeft') props.onPrevious()
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [focused, correcting, busy, props, item.state, checked, canReview])
  return <div className="card card-pad prediction-review-card" tabIndex={0} ref={root}
    aria-label="Prediction review card" onFocus={() => setFocused(true)}
    onBlur={event => { if (!root.current?.contains(event.relatedTarget as Node | null)) setFocused(false) }}>
    <div className="prediction-review-head"><div><span className="pill">{item.prediction_state.replace('_', ' ')}</span>
      <h2>{item.label_id}</h2><p className="muted">{item.source} · {item.model_version}</p></div>
      <button className="button secondary" onClick={props.onClose}>Close <kbd>Esc</kbd></button></div>
    {item.content?.content_type === 'image_classification' && item.content.image_url ?
      <ImageViewer key={`${item.current_label_log_id}:${item.content.image_url}`} imageUrl={item.content.image_url}
        altText={item.text || `Prediction image ${item.label_id}`} category={item.category} readOnly /> :
      <div className="prediction-text">{item.text || <span className="muted">No source text</span>}</div>}
    <div className="grid-2 prediction-facts"><div><strong>Current category</strong><p>{item.category ?? 'Unclassified'}</p></div>
      <div><strong>Recommended action</strong><p>{item.action ?? item.recommendation}</p></div>
      <div><strong>Model confidence</strong><p>{Math.round(item.model_confidence * 100)}%</p></div>
      <div><strong>DLJ confidence</strong><p>{Math.round(item.dlj_confidence * 100)}%</p></div></div>
    {item.spans.length > 0 && <section><NERViewer text={item.text ?? ''} spans={item.spans} />
      <label><input type="checkbox" disabled={busy} checked={checked} onChange={event => setAttested(event.target.checked ? item.current_label_log_id : null)} /> I reviewed these spans</label></section>}
    <section><h3>Factor breakdown</h3>{Object.entries(item.factors).map(([name, value]) => <FactorBar key={name} factor={name} value={value} />)}</section>
    {correcting && <div className="notice prediction-correct-dialog" role="dialog" aria-label="Correct prediction">
      <h3>Correct prediction</h3><div className="grid-2"><label className="field">Category<select value={category} onChange={event => setCategory(event.target.value)}>{item.categories.map(value => <option key={value}>{value}</option>)}</select></label>
        <label className="field">Action<select value={action} onChange={event => setAction(event.target.value)}>{item.actions.map(value => <option key={value}>{value}</option>)}</select></label></div>
      <div className="button-row"><button className="button" disabled={!canReview || !category || !action} onClick={() => props.onCorrect(category, action, checked)}>Confirm correction</button>
        <button className="button secondary" disabled={busy} onClick={() => setCorrecting(false)}>Cancel</button></div></div>}
    <div className="button-row prediction-actions">
      <button className="button" disabled={!canReview || correcting} onClick={() => props.onAccept(checked)}>Accept <kbd>A</kbd></button>
      <button className="button amber" disabled={busy || item.state === 'human_reviewed'} onClick={() => setCorrecting(true)}>Correct <kbd>C</kbd></button>
      <button className="button danger" disabled={busy || item.state === 'pending'} onClick={props.onReopen}>Reopen <kbd>R</kbd></button>
      <button className="button secondary" onClick={props.onPrevious}>Previous <kbd>P</kbd></button>
      <button className="button secondary" onClick={props.onNext}>Next <kbd>N</kbd></button>
    </div><p className="muted">Click this card to enable keyboard shortcuts.</p>
  </div>
}
