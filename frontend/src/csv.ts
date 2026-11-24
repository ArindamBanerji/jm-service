import Papa from 'papaparse'
import type { IngestItem } from './api'

export async function parseIngestCsv(file: File): Promise<IngestItem[]> {
  const text = await file.text()
  const header = Papa.parse<string[]>(text, { preview: 1 }).data[0] ?? []
  if (header.length !== new Set(header).size || header.some(field => !field.trim())) throw new Error('CSV headers must be unique and nonempty')
  const parsed = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true })
  if (parsed.errors.length) throw new Error(`CSV parse error: ${parsed.errors[0].message}`)
  const fields = parsed.meta.fields ?? []
  if (fields.length !== new Set(fields).size || fields.some(field => !field.trim())) throw new Error('CSV headers must be unique and nonempty')
  if (!['label_id', 'category'].every(field => fields.includes(field))) throw new Error('CSV needs label_id and category columns')
  if (parsed.data.length < 1) throw new Error('CSV has no labels')
  const excluded = new Set(['label_id', 'category', 'annotator_id', 'text', 'proposed_action', 'actual_action', 'verified', 'verified_outcome', 'action', 'timestamp', 'existing_label'])
  const prefixed = fields.filter(field => field.startsWith('factor_'))
  const factorColumns = prefixed.length ? prefixed : fields.filter(field => !excluded.has(field))
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
    const source = row.text || null
    if (source && new TextEncoder().encode(source).length > 32 * 1024) throw new Error(`Row ${index + 2}: text must be at most 32 KiB UTF-8`)
    return { label_id, category, annotator_id: row.annotator_id?.trim() || null, factors, text: source }
  })
}
