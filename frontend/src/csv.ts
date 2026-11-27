import Papa from 'papaparse'
import type { ContentType, IngestItem } from './api'

const RESERVED = new Set(['label_id', 'category', 'annotator_id', 'text', 'item_text', 'item_media_url',
  'content_type', 'image_url', 'spans', 'tags', 'proposed_action', 'actual_action', 'verified',
  'verified_outcome', 'action', 'timestamp', 'existing_label'])

function validateItem(item: IngestItem, index: number, contentType: ContentType): IngestItem {
  const row = index + 2
  if (!item.label_id?.trim() || !item.category?.trim()) throw new Error(`Row ${row}: label_id and category are required`)
  if (Object.keys(item.factors).length < 2) throw new Error(`Row ${row}: at least two factors are required`)
  for (const [name, value] of Object.entries(item.factors))
    if (!name || !Number.isFinite(value) || value < 0 || value > 1) throw new Error(`Row ${row}: ${name || 'factor'} must be between 0 and 1`)
  const text = item.text ?? item.item_text ?? null
  if (item.text != null && item.item_text != null && item.text !== item.item_text ||
      item.item_media_url != null && item.content?.image_url != null && item.item_media_url !== item.content.image_url)
    throw new Error(`Row ${row}: Conflicting values for text or image URL`)
  if (text && new TextEncoder().encode(text).length > 32 * 1024) throw new Error(`Row ${row}: text must be at most 32 KiB UTF-8`)
  if (contentType === 'image') {
    const imageUrl = item.item_media_url ?? item.content?.image_url
    if (!imageUrl) throw new Error(`Row ${row}: item_media_url is required for image projects`)
    if (item.content && (item.content.content_type !== 'image_classification' || item.content.tags?.length || item.content.spans?.length))
      throw new Error(`Row ${row}: Content does not match project modality`)
    return { ...item, text, item_text: undefined, item_media_url: undefined,
      content: { content_type: 'image_classification', image_url: imageUrl, spans: [], tags: [] } }
  }
  return { ...item, text, item_text: undefined }
}

export async function parseIngestCsv(file: File, contentType: ContentType = 'text'): Promise<IngestItem[]> {
  const text = await file.text()
  const header = Papa.parse<string[]>(text, { preview: 1 }).data[0] ?? []
  if (header.length !== new Set(header).size || header.some(field => !field.trim())) throw new Error('CSV headers must be unique and nonempty')
  const parsed = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true })
  if (parsed.errors.length) throw new Error(`CSV parse error: ${parsed.errors[0].message}`)
  const fields = parsed.meta.fields ?? []
  if (fields.length !== new Set(fields).size || fields.some(field => !field.trim())) throw new Error('CSV headers must be unique and nonempty')
  // Project downloads carry the original public ID, JSON factors, and CSV-safe text.
  // Provenance and past human decisions never become scoring inputs on re-import.
  if (contentType === 'image' && ['root_label_id', 'current_label_id', 'image_url'].every(key => fields.includes(key))) {
    if (!fields.includes('factors')) throw new Error('Re-export the project CSV with factors to import it')
    if (!parsed.data.length) throw new Error('CSV has no labels')
    const restore = (value: string) => /^'['=+@\-\t\r]/.test(value) ? value.slice(1) : value
    const seen = new Set<string>()
    return parsed.data.map((row, index) => {
      const labelId = restore(row.root_label_id)
      if (seen.has(labelId)) throw new Error(`Row ${index + 2}: duplicate label_id ${labelId}`)
      seen.add(labelId)
      let factors: unknown
      try { factors = JSON.parse(row.factors) } catch { throw new Error(`Row ${index + 2}: invalid exported factors`) }
      if (!factors || typeof factors !== 'object' || Array.isArray(factors))
        throw new Error(`Row ${index + 2}: invalid exported factors`)
      return validateItem({ label_id: labelId, category: restore(row.category ?? ''),
        text: restore(row.text ?? ''), annotator_id: restore(row.annotator_id ?? '') || null,
        item_media_url: row.image_url, factors: factors as Record<string, number> }, index, contentType)
    })
  }
  if (!['label_id', 'category'].every(field => fields.includes(field))) throw new Error('CSV needs label_id and category columns')
  if (parsed.data.length < 1) throw new Error('CSV has no labels')
  const prefixed = fields.filter(field => field.startsWith('factor_'))
  const factorColumns = prefixed.length ? prefixed : fields.filter(field => !RESERVED.has(field))
  const names = factorColumns.map(field => field.replace(/^factor_/, ''))
  if (names.length < 2 || new Set(names).size !== names.length) throw new Error('CSV needs at least two distinct factor columns')
  const seen = new Set<string>()
  return parsed.data.map((row, index) => {
    const label_id = row.label_id?.trim()
    const category = row.category?.trim()
    if (!label_id || !category) throw new Error(`Row ${index + 2}: label_id and category are required`)
    if (seen.has(label_id)) throw new Error(`Row ${index + 2}: duplicate label_id ${label_id}`)
    seen.add(label_id)
    const factors: Record<string, number> = {}
    for (const column of factorColumns) {
      const raw = row[column]?.trim()
      const value = Number(raw)
      if (!raw || !Number.isFinite(value) || value < 0 || value > 1) throw new Error(`Row ${index + 2}: ${column} must be between 0 and 1`)
      factors[column.replace(/^factor_/, '')] = value
    }
    return validateItem({ label_id, category, annotator_id: row.annotator_id?.trim() || null, factors,
      text: row.text ?? null, item_text: row.item_text ?? null, item_media_url: row.item_media_url || null }, index, contentType)
  })
}

export async function parseIngestFile(file: File, contentType: ContentType = 'text'): Promise<IngestItem[]> {
  if (!file.name.toLowerCase().endsWith('.json') && file.type !== 'application/json')
    return parseIngestCsv(file, contentType)
  let value: unknown
  try { value = JSON.parse(await file.text()) }
  catch { throw new Error('JSON parse error') }
  const rows = Array.isArray(value) ? value : value && typeof value === 'object' && Array.isArray((value as { items?: unknown }).items)
    ? (value as { items: unknown[] }).items : null
  if (!rows?.length) throw new Error('JSON needs a nonempty items array')
  const seen = new Set<string>()
  return rows.map((raw, index) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`Row ${index + 2}: item must be an object`)
    const row = raw as Record<string, unknown>
    const labelId = typeof row.label_id === 'string' ? row.label_id.trim() : ''
    if (seen.has(labelId)) throw new Error(`Row ${index + 2}: duplicate label_id ${labelId}`)
    seen.add(labelId)
    const factors = row.factors && typeof row.factors === 'object' && !Array.isArray(row.factors)
      ? row.factors as Record<string, number> : {}
    return validateItem({ label_id: labelId, category: typeof row.category === 'string' ? row.category.trim() : '',
      annotator_id: typeof row.annotator_id === 'string' ? row.annotator_id.trim() : null, factors,
      text: typeof row.text === 'string' ? row.text : null,
      item_text: typeof row.item_text === 'string' ? row.item_text : null,
      item_media_url: typeof row.item_media_url === 'string' ? row.item_media_url : null,
      content: row.content && typeof row.content === 'object' ? row.content as IngestItem['content'] : null,
    }, index, contentType)
  })
}
