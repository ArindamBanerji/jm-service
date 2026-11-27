const BASE = '/v1'

export type Tier = 'red' | 'amber' | 'green' | 'autonomous'
export type ContentType = 'text' | 'image'
export type LabelSchema = 'single' | 'multi' | 'ner'
export type Modality = { content_type: ContentType; label_schema: LabelSchema; modality_enforced: boolean }
export type ProjectMediaSettings = Modality & { modality_locked: boolean; inline_images_enabled: boolean }
export type MediaSummary = { media_kind: 'text' | 'image' }
export interface ProjectCapabilities {
  combinations: { content_type: ContentType; label_schema: LabelSchema }[]
  inline_images_enabled: boolean
}
export interface TierStatus {
  tier: Tier
  category: string
  verified_count: number
  accuracy: number | null
  conservation_gate_pass: boolean
  conservation_reason: string | null
  next_tier: Tier | null
  next_tier_requirements: string | null
  recommended_action_policy: string
}
export interface IngestItem {
  label_id: string
  category: string
  annotator_id?: string | null
  factors: Record<string, number>
  text?: string | null
  notes?: string | null
  item_media_url?: string | null
  item_text?: string | null
  content?: LabelContent | null
}
export interface IngestRequest extends IngestItem { domain_id: string }
export interface IngestResponse {
  label_id: string
  decision_id: string
  recommended_action: string
  confidence: number
  factors_used: Record<string, number>
  category: string
  conservation_status: string
  tier: Tier
  action_policy: string
  tier_status: TierStatus
  auto_accepted: boolean
}
export interface IngestBatchRequest { domain_id: string; items: IngestItem[] }
export interface IngestBatchResponse { results: IngestResponse[]; batch_size: number }
export interface SampleSeedResponse { domain_id: string; created: number; existing: number; pending: number }
export interface VerifyRequest {
  domain_id: string
  label_id: string
  actual_action: string
  verified_outcome: boolean
  notes?: string | null
}
export interface VerifyResponse {
  label_id: string
  action_taken: string
  was_correct: boolean
  engine_updated: boolean
  new_accuracy: number | null
}
export interface PendingLabel extends IngestItem {
  annotator_id: string | null
  recommended_action: string
  confidence: number
  text_preview: string | null
  centroid_distance?: number | null
  priority_rank?: number
  review_notes?: string | null
  media_kind?: MediaSummary['media_kind']
}
export interface NextBatchResponse {
  items: { id: string; text_preview: string; centroid_distance: number | null; category: string
    priority_rank: number; annotator_id: string | null; recommended_action: string; confidence: number
    notes?: string | null; review_notes?: string | null; media_kind?: MediaSummary['media_kind'] }[]
  strategy: 'centroid_distance' | 'random'
  total_pending: number
  note?: string | null
}
export interface SlaResponse {
  floor_pct: number | null
  current_accuracy: number
  margin: number | null
  gate_status: 'safe' | 'warning' | 'critical' | 'paused' | 'inactive'
  auto_approve_active: boolean
  verified_count: number
  min_verified_for_sla: number
}
export interface DistributionResponse {
  categories: { name: string; count: number; pct: number; verified: number; pending: number }[]
  total: number
  imbalance_warning: string | null
}
export interface ThroughputResponse {
  daily: { date: string; labels: number; verified: number; avg_time_sec: number | null }[]
  annotators: { id: string; name: string; labels_total: number; labels_today: number; avg_time_sec: number | null }[]
  summary: { total_labels: number; avg_per_day: number; avg_time_sec: number | null }
}
export type ConfusionSource = 'human' | 'prediction' | 'all'
export interface ConfusionResponse {
  categories: string[]
  matrix: number[][]
  top_confusions: { from: string; to: string; count: number; pct: number }[]
}
export interface AnalyticsAgreementResponse {
  annotators: string[]
  matrix: number[][]
  per_category: Record<string, number[][]>
  lowest_pair: { a: string; b: string; agreement: number; worst_category: string | null } | null
  note?: string | null
}
export interface LabelDetail extends Omit<PendingLabel, 'text_preview' | 'category' | 'confidence' | 'recommended_action'> {
  domain_id: string
  category: string | null
  confidence: number | null
  recommended_action: string | null
  text: string | null
  actual_action: string | null
  notes: string | null
  review_notes: string | null
  verified_outcome: boolean | null
  verified_at: string | null
  revision_id: string
  previous_category: string | null
  status: 'pending_classification' | 'scored'
  content: LabelContent | null
  prediction?: PredictionItem
}
export interface NerSpan { start: number; end: number; label: string; text: string }
export interface LabelContent {
  content_type: 'text_ner' | 'text_multilabel' | 'image_classification'
  spans: NerSpan[]
  tags: string[]
  image_url: string | null
}
export interface TextTaskResponse { label_id: string; status: 'pending_classification' | 'scored'; category: string | null }
export interface RelabelResponse { label_id: string; category: string; revision_id: string; previous_category: string | null }
export type PendingResponse = PendingLabel[]
export interface Inversion { trusted_factor: string; actual_signal_factor: string; interpretation: string }
export interface OverviewResponse {
  domain_id: string
  overall_accuracy: number | null
  total_verified: number
  total_labels: number
  categories: TierStatus[]
  inversion: Inversion | null
  compounding_curve: { verified_count: number; accuracy: number; timestamp: string }[]
  generated_at: string
}
export interface CorrectionPattern {
  category: string
  recommended_action: string
  actual_action: string
  count: number
  percentage_of_category: number
}
export interface CorrectionsResponse {
  domain_id: string
  total_corrections: number
  correction_rate: number | null
  patterns: CorrectionPattern[]
  top_pattern: Omit<CorrectionPattern, 'percentage_of_category'> | null
}
export interface AnnotatorProfile {
  annotator_id: string
  total_labels: number
  verified_count: number
  accuracy: number | null
  strongest_category: string | null
  weakest_category: string | null
  last_active: string
}
export interface AnnotatorsResponse { domain_id: string; annotators: AnnotatorProfile[] }
export interface FactorsResponse {
  domain_id: string
  factor_names: string[]
  inversion: Inversion | null
  factor_stats: { factor: string; mean_correct: number | null; mean_incorrect: number | null; predictive_gap: number | null }[]
}
export interface CompoundingResponse {
  domain_id: string
  category: string | null
  points: { index: number; verified_count: number; running_accuracy: number; timestamp: string }[]
  baseline_accuracy: number | null
  current_accuracy: number | null
  improvement: number | null
}
export interface AutonomyResponse { domain_id: string; categories: TierStatus[]; overall_tier: Tier }
export interface HealthReport {
  report_version: string
  metadata: { row_count: number; category_count: number; factor_count: number; verified_count: number; analysis_time_ms: number }
  overall_accuracy: number | null
  category_risks: { category: string; accuracy: number | null; verified_count: number; risk_level: string; conservation_phase: string }[]
  inversion: Inversion | null
  annotator_profiles: unknown[] | null
  silent_risks: unknown[]
  cost_projection: unknown | null
  factor_names: string[]
  warnings: string[]
  message?: string
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

function explain(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(explain).join('; ')
  if (detail && typeof detail === 'object') {
    const value = detail as Record<string, unknown>
    if ('item_index' in value) return `CSV row ${Number(value.item_index) + 1}: ${explain(value.error)}`
    if ('message' in value) return String(value.message)
    if ('msg' in value) return String(value.msg)
  }
  return 'Request failed'
}

function decode(path: string, value: unknown, method = 'GET'): void {
  const object = (candidate: unknown): candidate is Record<string, unknown> =>
    candidate !== null && typeof candidate === 'object' && !Array.isArray(candidate)
  const requireFields = (candidate: unknown, fields: Record<string, 'string' | 'number' | 'boolean' | 'object' | 'array'>) => {
    if (!object(candidate)) throw new ApiError('The server returned incompatible data. Refresh and retry.', 502)
    for (const [name, kind] of Object.entries(fields)) {
      const field = candidate[name]
      if (kind === 'array' ? !Array.isArray(field) : kind === 'object' ? !object(field) : typeof field !== kind)
        throw new ApiError('The server returned incompatible data. Refresh and retry.', 502)
    }
  }
  if (path === '/projects/capabilities') {
    requireFields(value, { combinations: 'array', inline_images_enabled: 'boolean' })
    ;(value as ProjectCapabilities).combinations.forEach(row =>
      requireFields(row, { content_type: 'string', label_schema: 'string' }))
  } else if (path.startsWith('/projects') && !path.match(/\/projects\/[^/]+/)) {
    if (method === 'GET' && !Array.isArray(value)) throw new ApiError('The server returned incompatible project data. Refresh and retry.', 502)
    if (method === 'GET' && Array.isArray(value)) value.forEach(row => {
      requireFields(row, { id: 'string', name: 'string', status: 'string', settings_version: 'number' })
      if (!object(row) || (row.public_domain_id !== null && typeof row.public_domain_id !== 'string'))
        throw new ApiError('The server returned incompatible project data. Refresh and retry.', 502)
      if (object(row) && ('content_type' in row || 'label_schema' in row || 'modality_enforced' in row))
        requireFields(row, { content_type: 'string', label_schema: 'string', modality_enforced: 'boolean' })
    })
    else requireFields(value, { id: 'string', public_domain_id: 'string', name: 'string' })
  } else if (path.match(/^\/projects\/[^/]+$/)) {
    if (method === 'GET') {
      requireFields(value, { id: 'string', name: 'string', settings_version: 'number', role: 'string' })
      if (!object(value) || (value.public_domain_id !== null && typeof value.public_domain_id !== 'string'))
        throw new ApiError('The server returned incompatible project data. Refresh and retry.', 502)
      if (object(value) && ('content_type' in value || 'label_schema' in value || 'modality_enforced' in value))
        requireFields(value, { content_type: 'string', label_schema: 'string', modality_enforced: 'boolean', modality_locked: 'boolean' })
    }
    else requireFields(value, { id: 'string', settings_version: 'number', status: 'string' })
  }
  else if (/^\/(?:projects\/[^/]+\/labels|labels\/[^/]+)\/pending$/.test(path)) {
    if (!Array.isArray(value)) throw new ApiError('The server returned incompatible queue data. Refresh and retry.', 502)
    value.forEach(row => requireFields(row, { label_id: 'string', recommended_action: 'string', confidence: 'number' }))
  } else if (method === 'GET' && /\/items\/[^/]+$/.test(path)) {
    requireFields(value, { label_id: 'string', factors: 'object', revision_id: 'string', status: 'string' })
    const content = (value as Record<string, unknown>).content
    if (content !== null && content !== undefined) {
      requireFields(content, { content_type: 'string', spans: 'array', tags: 'array' })
      const structured = content as LabelContent
      if (!structured.tags.every(tag => typeof tag === 'string')) throw new ApiError('Invalid label tags', 502)
      structured.spans.forEach(span => requireFields(span, { start: 'number', end: 'number', label: 'string', text: 'string' }))
      if (structured.content_type === 'image_classification' && structured.image_url != null && typeof structured.image_url !== 'string')
        throw new ApiError('Invalid image label content', 502)
    }
  } else if (path.endsWith('/relabel')) requireFields(value, { label_id: 'string', revision_id: 'string' })
  else if (path.endsWith('/content')) requireFields(value, { label_id: 'string', content_type: 'string' })
  else if (path.endsWith('/tasks')) requireFields(value, { label_id: 'string', status: 'string' })
  else if (path.endsWith('/predictions') && method === 'GET') {
    requireFields(value, { items: 'array', total: 'number', limit: 'number', offset: 'number' })
    ;(value as { items: unknown[] }).items.forEach(row => {
      requireFields(row, { origin: 'string', label_id: 'string' })
      if (object(row) && row.origin === 'human') {
        requireFields(row, { recommended_action: 'string', confidence: 'number' })
      } else {
        requireFields(row, { id: 'string', prediction_state: 'string', decision_version: 'number',
          current_label_log_id: 'string', factors: 'object', categories: 'array', actions: 'array',
          model_confidence: 'number', dlj_confidence: 'number', spans: 'array' })
        ;(row as PredictionItem).spans.forEach(span => requireFields(span, { start: 'number', end: 'number', label: 'string', text: 'string' }))
      }
    })
  } else if (path.includes('/predictions/') && (path.endsWith('/review') || path.endsWith('/reopen')))
    requireFields(value, { id: 'string', state: 'string', current_label_log_id: 'string', decision_version: 'number' })
  else if (path.includes('/webhooks') && !path.endsWith('/deliveries') && !path.endsWith('/test') && !path.endsWith('/health')) {
    const fields = { id: 'string', url: 'string', subscribed_events: 'array', active: 'boolean', key_version: 'number', created_at: 'string' } as const
    if (method === 'GET') {
      if (!Array.isArray(value)) throw new ApiError('Invalid webhook list', 502)
      value.forEach(row => requireFields(row, fields))
    } else requireFields(value, fields)
  }
  else if (path.endsWith('/webhooks/health')) requireFields(value, { total: 'number', healthy: 'number', retrying: 'number', failing: 'number', items: 'array' })
  else if (path.endsWith('/deliveries')) requireFields(value, { items: 'array', attempt_history: 'array', total: 'number' })
  else if (path.endsWith('/bulk-verify')) requireFields(value, { processed: 'number', skipped: 'number', errors: 'array' })
  else if (path.endsWith('/sample')) requireFields(value, { domain_id: 'string', created: 'number', existing: 'number', pending: 'number' })
  else if (path === '/labels/verify' || path.endsWith('/labels/verify')) requireFields(value, { label_id: 'string', was_correct: 'boolean' })
  else if (path === '/labels/ingest/batch' || path.endsWith('/labels/batch')) {
    requireFields(value, { results: 'array', batch_size: 'number' })
    ;(value as { results: unknown[] }).results.forEach(row => requireFields(row, { label_id: 'string' }))
  } else if (path === '/labels/ingest') requireFields(value, { label_id: 'string', decision_id: 'string', confidence: 'number' })
  else if (path.endsWith('/autonomy')) {
    requireFields(value, { categories: 'array' })
    ;(value as { categories: unknown[] }).categories.forEach(row => requireFields(row, { category: 'string', tier: 'string' }))
  }
  else if (path.endsWith('/next-batch')) {
    requireFields(value, { items: 'array', strategy: 'string', total_pending: 'number' })
    const batch = value as NextBatchResponse
    if (!['random', 'centroid_distance'].includes(batch.strategy) || batch.items.some(row =>
      !row || (row.centroid_distance !== null && !Number.isFinite(row.centroid_distance)))) throw new ApiError('Invalid smart queue data', 502)
    batch.items.forEach(row => requireFields(row, {
      id: 'string', text_preview: 'string', category: 'string', priority_rank: 'number',
      recommended_action: 'string', confidence: 'number',
    }))
  }
  else if (path.endsWith('/sla')) {
    requireFields(value, {
    current_accuracy: 'number', gate_status: 'string', auto_approve_active: 'boolean',
    verified_count: 'number', min_verified_for_sla: 'number',
    })
    const sla = value as SlaResponse
    if (!['safe', 'warning', 'critical', 'paused', 'inactive'].includes(sla.gate_status) ||
      (sla.gate_status === 'inactive' ? sla.floor_pct !== null || sla.margin !== null :
        !Number.isFinite(sla.floor_pct) || !Number.isFinite(sla.margin))) throw new ApiError('Invalid quality SLA', 502)
  }
  else if (path.endsWith('/analytics/distribution')) {
    requireFields(value, { categories: 'array', total: 'number' })
    ;(value as DistributionResponse).categories.forEach(row => requireFields(row, {
      name: 'string', count: 'number', pct: 'number', verified: 'number', pending: 'number',
    }))
  } else if (path.endsWith('/analytics/throughput')) {
    requireFields(value, { daily: 'array', annotators: 'array', summary: 'object' })
    const result = value as ThroughputResponse
    result.daily.forEach(row => requireFields(row, { date: 'string', labels: 'number', verified: 'number' }))
    result.annotators.forEach(row => requireFields(row, { id: 'string', name: 'string', labels_total: 'number', labels_today: 'number' }))
    requireFields(result.summary, { total_labels: 'number', avg_per_day: 'number' })
  } else if (path.endsWith('/analytics/confusion')) {
    requireFields(value, { categories: 'array', matrix: 'array', top_confusions: 'array' })
    const result = value as ConfusionResponse
    if (!result.categories.every(name => typeof name === 'string') ||
      !result.matrix.every(row => Array.isArray(row) && row.every(cell => typeof cell === 'number')))
      throw new ApiError('Invalid confusion matrix', 502)
    result.top_confusions.forEach(row => requireFields(row, { from: 'string', to: 'string', count: 'number', pct: 'number' }))
  } else if (path.endsWith('/analytics/agreement')) {
    requireFields(value, { annotators: 'array', matrix: 'array', per_category: 'object' })
    const result = value as AnalyticsAgreementResponse
    if (!result.annotators.every(name => typeof name === 'string') ||
      !result.matrix.every(row => Array.isArray(row) && row.every(cell => typeof cell === 'number')))
      throw new ApiError('Invalid agreement matrix', 502)
  }
  else if (path.endsWith('/invites')) requireFields(value, { id: 'string', mail_status: 'string' })
  else if (path === '/account') requireFields(value, { tenant_id: 'string', tier: 'string' })
  else if (path === '/account/domains') {
    if (!Array.isArray(value)) throw new ApiError('The server returned incompatible domain data. Refresh and retry.', 502)
    value.forEach(row => requireFields(row, { id: 'string' }))
  } else if (path === '/account/domains/resolve') requireFields(value, { public_domain_id: 'string' })
  else if (path === '/auth/confirm') requireFields(value, { api_key: 'string', tenant_id: 'string' })
  else if (path === '/auth/register') requireFields(value, { message: 'string' })
  else if (path === '/label-health/analyze') {
    requireFields(value, { metadata: 'object', warnings: 'array' })
    requireFields((value as { metadata: unknown }).metadata, { row_count: 'number', verified_count: 'number', factor_count: 'number' })
  } else if (path === '/billing/checkout-url') requireFields(value, { checkout_url: 'string', tier: 'string' })
  else if (path.startsWith('/dashboard/') || path.includes('/dashboard/')) {
    const route = path.split('/').at(-1)
    const fields = route === 'overview' ? { domain_id: 'string', categories: 'array', total_verified: 'number', total_labels: 'number', compounding_curve: 'array' } :
      route === 'corrections' ? { domain_id: 'string', patterns: 'array' } :
      route === 'annotators' ? { domain_id: 'string', annotators: 'array' } :
      route === 'factors' ? { domain_id: 'string', factor_stats: 'array' } :
      route === 'compounding' ? { domain_id: 'string', points: 'array' } :
      { pairs: 'array' }
    requireFields(value, fields as unknown as Record<string, 'string' | 'number' | 'boolean' | 'object' | 'array'>)
    const data = value as Record<string, unknown[]>
    if (route === 'overview') {
      data.categories.forEach(row => requireFields(row, { category: 'string', tier: 'string', verified_count: 'number' }))
      data.compounding_curve.forEach(row => requireFields(row, { verified_count: 'number', accuracy: 'number' }))
    } else if (route === 'corrections') {
      data.patterns.forEach(row => requireFields(row, { category: 'string', recommended_action: 'string', actual_action: 'string', count: 'number', percentage_of_category: 'number' }))
    } else if (route === 'annotators') {
      data.annotators.forEach(row => requireFields(row, { annotator_id: 'string', total_labels: 'number', verified_count: 'number', last_active: 'string' }))
    } else if (route === 'factors') {
      data.factor_stats.forEach(row => requireFields(row, { factor: 'string' }))
    } else if (route === 'compounding') {
      data.points.forEach(row => requireFields(row, { verified_count: 'number', running_accuracy: 'number' }))
    } else if (route === 'iaa') {
      data.pairs.forEach(row => requireFields(row, { annotator_a: 'string', annotator_b: 'string', overlap_count: 'number' }))
    }
  } else if (path.endsWith('/guidelines')) {
    if (!object(value) || !(typeof value.guidelines === 'string' || value.guidelines === null))
      throw new ApiError('The server returned incompatible guidelines. Refresh and retry.', 502)
  } else if (!object(value) && !Array.isArray(value)) throw new ApiError('The server returned incompatible data. Refresh and retry.', 502)
}

async function request<T>(path: string, init?: RequestInit, onResponse?: (response: Response) => void,
  credential?: string, expectedFormat: 'json' | 'html' | 'pdf' | 'csv' = 'json'): Promise<T> {
  const authenticated = !path.startsWith('/label-health/') && path !== '/auth/register' && path !== '/auth/confirm'
  const apiKey = credential ?? (localStorage.getItem('rgi-api-key') || (import.meta.env.DEV ? import.meta.env.VITE_API_KEY : ''))
  const headers = new Headers(init?.headers)
  if (authenticated && apiKey) headers.set('X-Api-Key', apiKey)
  const response = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail: unknown
    try {
      const body: unknown = await response.clone().json()
      if (body && typeof body === 'object' && !Array.isArray(body)) {
        const fields = body as Record<string, unknown>
        detail = fields.detail ?? fields.error ?? JSON.stringify(body)
      } else detail = body
    } catch { detail = await response.text() }
    throw new ApiError(explain(detail), response.status)
  }
  onResponse?.(response)
  const contentType = response.headers.get('content-type') ?? ''
  if (expectedFormat === 'csv' && contentType.includes('text/csv')) return await response.blob() as T
  if (expectedFormat === 'pdf' && contentType.includes('application/pdf')) return await response.blob() as T
  if (expectedFormat === 'html' && contentType.includes('text/html')) return await response.text() as T
  if (expectedFormat !== 'json' || !contentType.includes('application/json'))
    throw new ApiError('Unexpected response format', 502)
  const value: unknown = await response.json()
  decode(path.split('?')[0], value, init?.method ?? 'GET')
  return value as T
}
function json(body: unknown): RequestInit { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } }
function upload(file: File): RequestInit { const body = new FormData(); body.append('file', file); return { method: 'POST', body } }
function params(values: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') search.set(key, String(value))
  return search.size ? `?${search}` : ''
}
const id = (value: string) => encodeURIComponent(value)
const labelsRoot = (domainId: string, projectId?: string | null) =>
  projectId ? `/projects/${id(projectId)}/labels` : `/labels/${id(domainId)}`
const metaRoot = (domainId: string, projectId?: string | null) =>
  projectId ? `/projects/${id(projectId)}` : `/domains/${id(domainId)}`

export const uploadForAnalysis = (file: File, signal?: AbortSignal) => request<HealthReport>('/label-health/analyze', { ...upload(file), signal })
export const uploadForReport = (file: File, signal?: AbortSignal) => request<string>('/label-health/report', { ...upload(file), signal }, undefined, undefined, 'html')
export const downloadReportPdf = (file: File, signal?: AbortSignal) => request<Blob>('/label-health/report/pdf', { ...upload(file), signal }, undefined, undefined, 'pdf')
export const ingestLabel = (body: IngestRequest) => request<IngestResponse>('/labels/ingest', json(body))
export const ingestBatch = (body: IngestBatchRequest, credential?: string, signal?: AbortSignal,
  projectId?: string | null, requestKey?: string) => projectId ?
    request<IngestBatchResponse>(`${labelsRoot(body.domain_id, projectId)}/batch`,
      { ...json({ request_key: requestKey ?? crypto.randomUUID(), items: body.items }), signal }, undefined, credential) :
    request<IngestBatchResponse>('/labels/ingest/batch', { ...json(body), signal }, undefined, credential)
export const seedSample = (domainId: string, credential?: string, signal?: AbortSignal) => request<SampleSeedResponse>(`/labels/${id(domainId)}/sample`, { method: 'POST', signal }, undefined, credential)
export const hasApiKey = () => Boolean(localStorage.getItem('rgi-api-key') || (import.meta.env.DEV && import.meta.env.VITE_API_KEY))
  export interface RegistrationResponse { api_key: string; tenant_id: string; tier: string; message: string }
export interface RegistrationStart { message: string }
export const registerAccount = (email: string, name?: string) => request<RegistrationStart>('/auth/register', json({ email, name: name || undefined }))
export const confirmAccount = (token: string) => request<RegistrationResponse>('/auth/confirm', json({ token }))
export const verifyLabel = (body: VerifyRequest, credential?: string, signal?: AbortSignal, projectId?: string | null) =>
  request<VerifyResponse>(projectId ? `${labelsRoot(body.domain_id, projectId)}/verify` : '/labels/verify',
    { ...json(projectId ? { label_id: body.label_id, actual_action: body.actual_action,
      verified_outcome: body.verified_outcome, notes: body.notes } : body), signal }, undefined, credential)
export interface BulkVerifyResponse { processed: number; skipped: number; errors: { label_id: string; error: string }[] }
export const bulkVerify = (domainId: string, body: { label_ids: string[]; action: 'approve' | 'reject'; outcome: boolean; reason?: string }, credential?: string, signal?: AbortSignal, projectId?: string | null) => request<BulkVerifyResponse>(`${labelsRoot(domainId, projectId)}/bulk-verify`, { ...json(body), signal }, undefined, credential)
export type PendingSort = 'label_id' | 'category' | 'annotator_id' | 'confidence' | 'recommended_action' | 'scored_at'
export interface PendingOptions extends Record<string, string | number | undefined> { category?: string; limit?: number; offset?: number; sort_by?: PendingSort; sort_order?: 'asc' | 'desc'; search?: string }
export const getPending = (domainId: string, options: PendingOptions = {}, signal?: AbortSignal, projectId?: string | null, credential?: string) => request<PendingResponse>(`${labelsRoot(domainId, projectId)}/pending${params(options)}`, { signal }, undefined, credential)
export const getPendingPage = async (domainId: string, options: PendingOptions, credential?: string, signal?: AbortSignal, projectId?: string | null): Promise<{ rows: PendingLabel[]; total: number }> => {
  let total: number | null = null
  const rows = await request<PendingResponse>(`${labelsRoot(domainId, projectId)}/pending${params(options)}`, { signal }, response => {
    const header = response.headers.get('X-Total-Count')
    if (header !== null && /^\d+$/.test(header)) total = Number(header)
  }, credential)
  if (total === null || !Number.isSafeInteger(total)) throw new Error('Pending total count is unavailable')
  return { rows, total }
}
export const downloadProjectCsv = (projectId: string, credential: string, signal: AbortSignal) =>
  request<Blob>(`/projects/${id(projectId)}/export?format=csv&browser_fallback=true`,
    { signal }, undefined, credential, 'csv')
export const getNextBatch = (projectId: string, n = 50, credential?: string, signal?: AbortSignal,
  filters: Pick<PendingOptions, 'category' | 'search' | 'offset'> = {}) =>
  request<NextBatchResponse>(`/projects/${id(projectId)}/next-batch${params({ strategy: 'centroid_distance', n, ...filters })}`, { signal }, undefined, credential)
export const getProjectSla = (projectId: string, credential?: string, signal?: AbortSignal) =>
  request<SlaResponse>(`/projects/${id(projectId)}/sla`, { signal }, undefined, credential)
export const getDistribution = (projectId: string, credential?: string, signal?: AbortSignal) =>
  request<DistributionResponse>(`/projects/${id(projectId)}/analytics/distribution`, { signal }, undefined, credential)
export const getThroughput = (projectId: string, days = 7, credential?: string, signal?: AbortSignal) =>
  request<ThroughputResponse>(`/projects/${id(projectId)}/analytics/throughput${params({ days })}`, { signal }, undefined, credential)
export const getConfusion = (projectId: string, source: ConfusionSource = 'all', credential?: string, signal?: AbortSignal) =>
  request<ConfusionResponse>(`/projects/${id(projectId)}/analytics/confusion${params({ source })}`, { signal }, undefined, credential)
export const getAnalyticsAgreement = (projectId: string, credential?: string, signal?: AbortSignal) =>
  request<AnalyticsAgreementResponse>(`/projects/${id(projectId)}/analytics/agreement`, { signal }, undefined, credential)
export const getLabelDetail = (domainId: string, labelId: string, signal?: AbortSignal, projectId?: string | null, credential?: string) => request<LabelDetail>(`${labelsRoot(domainId, projectId)}/items/${id(labelId)}`, { signal }, undefined, credential)
export const createLabelContent = (domainId: string, labelId: string, body: LabelContent, projectId?: string | null) => request<{ label_id: string; content_type: string; spans_count?: number; tags_count?: number }>(`${labelsRoot(domainId, projectId)}/items/${id(labelId)}/content`, json(body))
export const createTextTask = (domainId: string, body: { label_id: string; text: string; category?: string }, credential?: string, signal?: AbortSignal, projectId?: string | null) => request<TextTaskResponse>(`${labelsRoot(domainId, projectId)}/tasks`, { ...json(body), signal }, undefined, credential)
export const relabelItem = (domainId: string, labelId: string, body: { category: string; idempotency_token: string; spans?: NerSpan[]; tags?: string[]; notes?: string }, credential?: string, signal?: AbortSignal, projectId?: string | null) => request<RelabelResponse>(`${labelsRoot(domainId, projectId)}/items/${id(labelId)}/relabel`, { ...json(body), signal }, undefined, credential)
const dashboardRoot = (domainId: string, projectId?: string | null) => projectId ? `/projects/${id(projectId)}/dashboard` : `/dashboard/${id(domainId)}`
export const getOverview = (domainId: string, projectId?: string | null, credential?: string, signal?: AbortSignal) => request<OverviewResponse>(`${dashboardRoot(domainId, projectId)}/overview`, { signal }, undefined, credential)
export const getCorrections = (domainId: string, projectId?: string | null, credential?: string, signal?: AbortSignal) => request<CorrectionsResponse>(`${dashboardRoot(domainId, projectId)}/corrections`, { signal }, undefined, credential)
export const getAnnotators = (domainId: string, limit = 50, projectId?: string | null, credential?: string, signal?: AbortSignal) => request<AnnotatorsResponse>(`${dashboardRoot(domainId, projectId)}/annotators${params({ limit })}`, { signal }, undefined, credential)
export const getFactors = (domainId: string, projectId?: string | null) => request<FactorsResponse>(`${dashboardRoot(domainId, projectId)}/factors`)
export const getCompounding = (domainId: string, options: { window?: number; category?: string } = {}, projectId?: string | null, credential?: string, signal?: AbortSignal) => request<CompoundingResponse>(`${dashboardRoot(domainId, projectId)}/compounding${params(options)}`, { signal }, undefined, credential)
export const getAutonomy = (domainId: string, signal?: AbortSignal, projectId?: string | null, credential?: string) => request<AutonomyResponse>(`${metaRoot(domainId, projectId)}/autonomy`, { signal }, undefined, credential)
export interface AgreementResponse {
  pairs: { annotator_a: string; annotator_b: string; kappa: number | null; overlap_count: number }[]
  overall_kappa: number | null
  total_overlapping_labels: number
}
export const getAgreement = (domainId: string, projectId?: string | null, credential?: string, signal?: AbortSignal) => request<AgreementResponse>(`${dashboardRoot(domainId, projectId)}/iaa`, { signal }, undefined, credential)
export interface GuidelinesResponse { guidelines: string | null; guidelines_updated_at: string | null }
export const getGuidelines = (domainId: string, signal?: AbortSignal, projectId?: string | null, credential?: string) => request<GuidelinesResponse>(`${metaRoot(domainId, projectId)}/guidelines`, { signal }, undefined, credential)
export const putGuidelines = (domainId: string, guidelines: string, credential?: string, signal?: AbortSignal) =>
  request<GuidelinesResponse>(`/domains/${id(domainId)}/guidelines`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guidelines }), signal }, undefined, credential)
export interface AccountSummary {
  tenant_id: string; tenant_name: string; tier: string; created_at: string
  is_active: boolean; cancelled_at: string | null; trial_expires_at: string | null; trial_expired: boolean
  usage: { labels_today: number; labels_this_month: number; daily_cap: number | null; monthly_cap: number | null; day_key: string; month_key: string }
}
export interface AccountDomain { id: string; public_domain_id: string | null; needs_name: boolean }
const emptyUsage: AccountSummary['usage'] = {
  labels_today: 0, labels_this_month: 0, daily_cap: null, monthly_cap: null, day_key: '—', month_key: '—',
}
export const getAccount = async (credential?: string, signal?: AbortSignal): Promise<AccountSummary> => {
  const result = await request<Omit<AccountSummary, 'usage'> & { usage?: Partial<AccountSummary['usage']> }>('/account', { signal }, undefined, credential)
  const usage = result.usage && typeof result.usage === 'object' ? result.usage : {}
  return { ...result, cancelled_at: result.cancelled_at ?? null, trial_expires_at: result.trial_expires_at ?? null,
    trial_expired: result.trial_expired ?? false, usage: { ...emptyUsage, ...usage } }
}
export const getAccountDomains = (credential?: string, signal?: AbortSignal) =>
  getAllPages<AccountDomain>('/account/domains', signal, credential)
export const resolveAccountDomain = (domainId: string, credential?: string, signal?: AbortSignal) => request<{ public_domain_id: string }>('/account/domains/resolve', { ...json({ domain_id: domainId }), signal }, undefined, credential)
export const getCheckoutUrl = (tier: string, credential?: string, signal?: AbortSignal) => request<{ checkout_url: string; tier: string }>(`/billing/checkout-url${params({ tier })}`, { signal }, undefined, credential)

export interface ProjectSummary extends Modality {
  id: string; public_domain_id: string | null; name: string; description?: string | null
  status: 'active' | 'archived' | 'completed'; settings_version: number
  automation_enabled?: boolean; confidence_floor?: number; role?: 'owner' | 'admin' | 'reviewer' | 'annotator'
  guidelines?: string | null; guidelines_updated_at?: string | null
  modality_locked?: boolean
}
async function getAllPages<T>(path: string, signal?: AbortSignal, credential?: string): Promise<T[]> {
  const owner = credential ?? (localStorage.getItem('rgi-api-key') || (import.meta.env.DEV ? import.meta.env.VITE_API_KEY : '') || '')
  const items: T[] = []
  let offset = 0
  for (;;) {
    let next: string | null = null
    const rows = await request<T[]>(offset ? `${path}?offset=${offset}` : path, { signal },
      response => { next = response.headers.get('X-Next-Offset') }, owner)
    items.push(...rows)
    if (next === null) return items
    if (!rows.length || Number(next) !== offset + rows.length) throw new ApiError('Invalid page. Refresh and retry.', 502)
    offset += rows.length
  }
}
export const getProjects = (signal?: AbortSignal, credential?: string) =>
  getAllPages<ProjectSummary>('/projects', signal, credential)
export const getProject = (projectId: string, signal?: AbortSignal, credential?: string) =>
  request<ProjectSummary>(`/projects/${id(projectId)}`, { signal }, undefined, credential)
export const fetchCapabilities = (signal?: AbortSignal, credential?: string) =>
  request<ProjectCapabilities>('/projects/capabilities', { signal }, undefined, credential)
export const createProject = (body: { name: string; public_domain_id: string; factors: string[]; categories: string[]; actions?: string[]; content_type?: ContentType; label_schema?: LabelSchema }, credential?: string, signal?: AbortSignal) =>
  request<ProjectSummary>('/projects', { ...json(body), signal }, undefined, credential)
export const updateProject = (projectId: string, settingsVersion: number, body: { description?: string; status?: ProjectSummary['status']; automation_enabled?: boolean; confidence_floor?: number; guidelines?: string | null; content_type?: ContentType; label_schema?: LabelSchema; modality_enforced?: boolean }, credential?: string, signal?: AbortSignal) =>
  request<{ id: string; settings_version: number; status: string; content_type?: ContentType; label_schema?: LabelSchema; modality_enforced?: boolean; modality_locked?: boolean }>(`/projects/${id(projectId)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': String(settingsVersion) }, body: JSON.stringify(body), signal,
  }, undefined, credential)
export const inviteProjectMember = (projectId: string, email: string, role: 'admin' | 'reviewer' | 'annotator', credential?: string, signal?: AbortSignal) =>
  request<{ id: string; mail_status: string }>(`/projects/${id(projectId)}/invites`, { ...json({ email, role }), signal }, undefined, credential)

export type PredictionState = 'pending_review' | 'accepted' | 'corrected' | 'reopened' | 'unknown'
export interface PredictionItem {
  id: string; label_id: string; state: 'pending' | 'auto_approved' | 'human_reviewed'
  spans: NerSpan[]; prediction_state: PredictionState; origin: 'prediction'; current_label_log_id: string
  source: string; model_version: string; model_confidence: number; dlj_confidence: number
  category: string | null; action: string | null; confidence: number | null
  recommendation: string; text: string | null; factors: Record<string, number>
  annotator_id: string | null; scored_at: string | null; decision_version: number
  categories: string[]; actions: string[]; assessment: 'correct' | 'incorrect' | 'unknown' | null
  media_kind?: MediaSummary['media_kind']; content?: LabelContent | null
}
export type PredictionQueueItem = PredictionItem | (Pick<PendingLabel, 'category' | 'recommended_action' | 'confidence' | 'label_id' | 'text_preview' | 'media_kind'> & { origin: 'human'; scored_at: string })
export interface PredictionPage { items: PredictionQueueItem[]; total: number; limit: number; offset: number }
export const getPredictions = (projectId: string, options: {
  origin?: 'human' | 'prediction' | 'all'; prediction_state?: PredictionState; source?: string; sort_by?: 'text' | 'category' | 'action' | 'confidence' | 'prediction_state' | 'scored_at'
  sort_order?: 'asc' | 'desc'; limit?: number; offset?: number
} = {}, credential?: string, signal?: AbortSignal) => request<PredictionPage>(
  `/projects/${id(projectId)}/predictions${params(options)}`, { signal }, undefined, credential)
export const reviewPrediction = (projectId: string, predictionId: string, body: {
  action: 'accept' | 'correct'; category?: string; actual_action?: string
  expected_revision: string; decision_version: number; human_spans_reviewed?: boolean; notes?: string
}, credential?: string, signal?: AbortSignal) => request<PredictionItem>(
  `/projects/${id(projectId)}/predictions/${id(predictionId)}/review`, { ...json(body), signal }, undefined, credential)
export const reopenPrediction = (projectId: string, predictionId: string, body: {
  expected_revision: string; decision_version: number
}, credential?: string, signal?: AbortSignal) => request<PredictionItem>(
  `/projects/${id(projectId)}/predictions/${id(predictionId)}/reopen`, { ...json(body), signal }, undefined, credential)

export const WEBHOOK_EVENTS = ['label.verified', 'prediction.auto_approved', 'webhook.test'] as const
export type WebhookEventType = typeof WEBHOOK_EVENTS[number]
export interface WebhookConfig {
  id: string; project_id: string; url: string; subscribed_events: WebhookEventType[]; active: boolean
  key_version: number; destination_version: number; signing_secret_masked: string
  rotated_at: string | null; created_at: string; updated_at: string; signing_secret?: string
}
export interface WebhookHealthItem {
  webhook_id: string; status: 'healthy' | 'retrying' | 'failing' | 'paused' | 'awaiting'; active: boolean
  last_delivery_state: string | null; last_status: number | null; last_delivered_at: string | null; next_retry_at: string | null
}
export interface WebhookHealth { total: number; healthy: number; retrying: number; failing: number; items: WebhookHealthItem[] }
export interface DeliveryAttempt {
  delivery_id: string; event_id: string; event_type: WebhookEventType; attempt_no: number
  timestamp: string; http_status: number | null; outcome: string | null; response_time_ms: number | null
  next_retry_at: string | null; error_summary: string | null
}
export interface DeliveryPage { items: Record<string, unknown>[]; attempt_history: DeliveryAttempt[]; total: number; limit: number; offset: number }
export const getWebhooks = (projectId: string, credential?: string, signal?: AbortSignal) =>
  request<WebhookConfig[]>(`/projects/${id(projectId)}/webhooks`, { signal }, undefined, credential)
export const createWebhook = (projectId: string, body: { url: string; subscribed_events: WebhookEventType[] }, credential?: string, signal?: AbortSignal) =>
  request<WebhookConfig>(`/projects/${id(projectId)}/webhooks`, { ...json(body), signal }, undefined, credential)
export const updateWebhook = (projectId: string, webhookId: string, body: { url?: string; subscribed_events?: WebhookEventType[]; active?: boolean }, credential?: string, signal?: AbortSignal) =>
  request<WebhookConfig>(`/projects/${id(projectId)}/webhooks/${id(webhookId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal }, undefined, credential)
export const deleteWebhook = (projectId: string, webhookId: string, credential?: string, signal?: AbortSignal) =>
  request<WebhookConfig>(`/projects/${id(projectId)}/webhooks/${id(webhookId)}`, { method: 'DELETE', signal }, undefined, credential)
export const rotateWebhook = (projectId: string, webhookId: string, credential?: string, signal?: AbortSignal) =>
  request<WebhookConfig>(`/projects/${id(projectId)}/webhooks/${id(webhookId)}/rotate`, { method: 'POST', signal }, undefined, credential)
export const testWebhook = (projectId: string, webhookId: string, credential?: string, signal?: AbortSignal) =>
  request<{ event_id: string; delivery_id: string }>(`/projects/${id(projectId)}/webhooks/${id(webhookId)}/test`, { method: 'POST', signal }, undefined, credential)
export const getWebhookHealth = (projectId: string, credential?: string, signal?: AbortSignal) =>
  request<WebhookHealth>(`/projects/${id(projectId)}/webhooks/health`, { signal }, undefined, credential)
export const getWebhookDeliveries = (projectId: string, webhookId: string, credential?: string, signal?: AbortSignal) =>
  request<DeliveryPage>(`/projects/${id(projectId)}/webhooks/${id(webhookId)}/deliveries?limit=20`, { signal }, undefined, credential)
