const BASE = '/v1'

export type Tier = 'red' | 'amber' | 'green' | 'autonomous'
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
}
export interface LabelDetail extends Omit<PendingLabel, 'text_preview' | 'category' | 'confidence' | 'recommended_action'> {
  domain_id: string
  category: string | null
  confidence: number | null
  recommended_action: string | null
  text: string | null
  actual_action: string | null
  verified_outcome: boolean | null
  verified_at: string | null
  revision_id: string
  previous_category: string | null
  status: 'pending_classification' | 'scored'
  content: LabelContent | null
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

async function request<T>(path: string, init?: RequestInit, onResponse?: (response: Response) => void): Promise<T> {
  const authenticated = !path.startsWith('/label-health/') && path !== '/auth/register'
  const apiKey = localStorage.getItem('rgi-api-key') || (import.meta.env.DEV ? import.meta.env.VITE_API_KEY : '')
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
  if (response.headers.get('content-type')?.includes('application/pdf')) return await response.blob() as T
  if (response.headers.get('content-type')?.includes('text/html')) return await response.text() as T
  return await response.json() as T
}
function json(body: unknown): RequestInit { return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } }
function upload(file: File): RequestInit { const body = new FormData(); body.append('file', file); return { method: 'POST', body } }
function params(values: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') search.set(key, String(value))
  return search.size ? `?${search}` : ''
}
const id = (value: string) => encodeURIComponent(value)

export const uploadForAnalysis = (file: File) => request<HealthReport>('/label-health/analyze', upload(file))
export const uploadForReport = (file: File) => request<string>('/label-health/report', upload(file))
export const downloadReportPdf = (file: File) => request<Blob>('/label-health/report/pdf', upload(file))
export const ingestLabel = (body: IngestRequest) => request<IngestResponse>('/labels/ingest', json(body))
export const ingestBatch = (body: IngestBatchRequest) => request<IngestBatchResponse>('/labels/ingest/batch', json(body))
export const seedSample = (domainId: string) => request<SampleSeedResponse>(`/labels/${id(domainId)}/sample`, { method: 'POST' })
export const hasApiKey = () => Boolean(localStorage.getItem('rgi-api-key') || (import.meta.env.DEV && import.meta.env.VITE_API_KEY))
export interface RegistrationResponse { api_key: string; tenant_id: string; tier: 'trial'; message: string }
export const registerAccount = (email: string, name?: string) => request<RegistrationResponse>('/auth/register', json({ email, name: name || undefined }))
export const verifyLabel = (body: VerifyRequest) => request<VerifyResponse>('/labels/verify', json(body))
export interface BulkVerifyResponse { processed: number; skipped: number; errors: { label_id: string; error: string }[] }
export const bulkVerify = (domainId: string, body: { label_ids: string[]; action: 'approve' | 'reject'; reason?: string }) => request<BulkVerifyResponse>(`/labels/${id(domainId)}/bulk-verify`, json(body))
export type PendingSort = 'label_id' | 'category' | 'annotator_id' | 'confidence' | 'recommended_action'
export interface PendingOptions extends Record<string, string | number | undefined> { category?: string; limit?: number; offset?: number; sort_by?: PendingSort; sort_order?: 'asc' | 'desc'; search?: string }
export const getPending = (domainId: string, options: PendingOptions = {}, signal?: AbortSignal) => request<PendingResponse>(`/labels/${id(domainId)}/pending${params(options)}`, { signal })
export const getPendingPage = async (domainId: string, options: PendingOptions): Promise<{ rows: PendingLabel[]; total: number }> => {
  let total: number | null = null
  const rows = await request<PendingResponse>(`/labels/${id(domainId)}/pending${params(options)}`, undefined, response => {
    const header = response.headers.get('X-Total-Count')
    if (header !== null && /^\d+$/.test(header)) total = Number(header)
  })
  if (total === null || !Number.isSafeInteger(total)) throw new Error('Pending total count is unavailable')
  return { rows, total }
}
export const getLabelDetail = (domainId: string, labelId: string, signal?: AbortSignal) => request<LabelDetail>(`/labels/${id(domainId)}/items/${id(labelId)}`, { signal })
export const createLabelContent = (domainId: string, labelId: string, body: LabelContent) => request<{ label_id: string; content_type: string; spans_count?: number; tags_count?: number }>(`/labels/${id(domainId)}/items/${id(labelId)}/content`, json(body))
export const createTextTask = (domainId: string, body: { label_id: string; text: string; category?: string }) => request<TextTaskResponse>(`/labels/${id(domainId)}/tasks`, json(body))
export const relabelItem = (domainId: string, labelId: string, body: { category: string; idempotency_token: string; spans?: NerSpan[]; tags?: string[] }) => request<RelabelResponse>(`/labels/${id(domainId)}/items/${id(labelId)}/relabel`, json(body))
export const getOverview = (domainId: string) => request<OverviewResponse>(`/dashboard/${id(domainId)}/overview`)
export const getCorrections = (domainId: string) => request<CorrectionsResponse>(`/dashboard/${id(domainId)}/corrections`)
export const getAnnotators = (domainId: string, limit = 50) => request<AnnotatorsResponse>(`/dashboard/${id(domainId)}/annotators${params({ limit })}`)
export const getFactors = (domainId: string) => request<FactorsResponse>(`/dashboard/${id(domainId)}/factors`)
export const getCompounding = (domainId: string, options: { window?: number; category?: string } = {}) => request<CompoundingResponse>(`/dashboard/${id(domainId)}/compounding${params(options)}`)
export const getAutonomy = (domainId: string, signal?: AbortSignal) => request<AutonomyResponse>(`/domains/${id(domainId)}/autonomy`, { signal })
export interface AgreementResponse {
  pairs: { annotator_a: string; annotator_b: string; kappa: number | null; overlap_count: number }[]
  overall_kappa: number | null
  total_overlapping_labels: number
}
export const getAgreement = (domainId: string) => request<AgreementResponse>(`/dashboard/${id(domainId)}/iaa`)
export const getGuidelines = (domainId: string, signal?: AbortSignal) => request<{ guidelines: string | null }>(`/domains/${id(domainId)}/guidelines`, { signal })
export const putGuidelines = (domainId: string, guidelines: string) =>
  request<{ guidelines: string | null }>(`/domains/${id(domainId)}/guidelines`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ guidelines }) })
export interface AccountSummary {
  tenant_id: string; tenant_name: string; tier: string; created_at: string
  is_active: boolean; cancelled_at: string | null; trial_expires_at: string | null; trial_expired: boolean
  usage: { labels_today: number; labels_this_month: number; daily_cap: number | null; monthly_cap: number | null; day_key: string; month_key: string }
}
export interface AccountDomain { id: string; public_domain_id: string | null; needs_name: boolean }
export const getAccount = () => request<AccountSummary>('/account')
export const getAccountDomains = () => request<AccountDomain[]>('/account/domains')
export const resolveAccountDomain = (domainId: string) => request<{ public_domain_id: string }>('/account/domains/resolve', json({ domain_id: domainId }))
export const getCheckoutUrl = (tier: string) => request<{ checkout_url: string; tier: string }>(`/billing/checkout-url${params({ tier })}`)
