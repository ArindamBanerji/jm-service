import { useState } from 'react'
import { nerColor } from './NERViewer'

interface Props {
  tags: string[]
  availableTags: string[]
  onTagsChange: (tags: string[]) => void
  input: string
  onInputChange: (value: string) => void
  readOnly?: boolean
  disabled?: boolean
}

export default function TagSelector({ tags, availableTags, onTagsChange, input, onInputChange, readOnly = false, disabled = false }: Props) {
  const [open, setOpen] = useState(false)
  const present = new Set(tags.map(tag => tag.toLocaleLowerCase()))
  const suggestions = [...new Set(availableTags)].filter(tag =>
    !present.has(tag.toLocaleLowerCase()) && tag.toLocaleLowerCase().includes(input.trim().toLocaleLowerCase()))
  const add = (value: string) => {
    const tag = value.trim()
    if (disabled || !tag || tag.length > 50 || tags.length >= 20 || present.has(tag.toLocaleLowerCase())) return
    onTagsChange([...tags, tag])
    onInputChange(''); setOpen(false)
  }
  const remove = (index: number) => { if (!disabled) onTagsChange(tags.filter((_, position) => position !== index)) }
  return <section aria-label="Multi-label tags" className="tag-selector">
    <h3 className="section-title">Tags</h3>
    <div className="tag-selector-row">
      {tags.map((tag, index) => <span className="tag-chip" key={`${tag}-${index}`} style={{ background: nerColor(tag) }}>
        {tag}{!readOnly && <button type="button" disabled={disabled} aria-label={`Remove ${tag}`} onClick={() => remove(index)}>×</button>}
      </span>)}
      {!readOnly && <div className="tag-input-wrap"><input aria-label="Add tag" role="combobox" disabled={disabled} aria-expanded={open && suggestions.length > 0}
        aria-controls="tag-suggestions" value={input} maxLength={50} placeholder="Add a tag…"
        onFocus={() => setOpen(true)} onChange={event => { onInputChange(event.target.value); setOpen(true) }}
        onKeyDown={event => {
          if (event.key === 'Enter') { event.preventDefault(); add(input) }
          else if (event.key === 'Backspace' && !input && tags.length) remove(tags.length - 1)
          else if (event.key === 'Escape') setOpen(false)
        }} />
        {open && suggestions.length > 0 && <div id="tag-suggestions" className="tag-suggestions" role="listbox">
          {suggestions.map(tag => <button type="button" role="option" disabled={disabled} aria-selected={false} key={tag}
            onMouseDown={event => event.preventDefault()} onClick={() => add(tag)}>{tag}</button>)}
        </div>}
      </div>}
    </div>
    {!readOnly && <p className="muted">Choose a suggestion or type a new tag and press Enter. Up to 20 tags.</p>}
  </section>
}
