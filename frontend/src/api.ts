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
}
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
    if ('msg' in value) return String(value.msg)
  }
  return 'Request failed'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authenticated = !path.startsWith('/label-health/')
  const apiKey = localStorage.getItem('rgi-api-key') || (import.meta.env.DEV ? import.meta.env.VITE_API_KEY : '')
  const headers = new Headers(init?.headers)
  if (authenticated && apiKey) headers.set('X-Api-Key', apiKey)
  const response = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    let detail: unknown
    try { detail = (await response.json()).detail } catch { detail = await response.text() }
    throw new ApiError(explain(detail), response.status)
  }
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
export const verifyLabel = (body: VerifyRequest) => request<VerifyResponse>('/labels/verify', json(body))
export const getPending = (domainId: string, options: { category?: string; limit?: number } = {}) => request<PendingResponse>(`/labels/${id(domainId)}/pending${params(options)}`)
export const getOverview = (domainId: string) => request<OverviewResponse>(`/dashboard/${id(domainId)}/overview`)
export const getCorrections = (domainId: string) => request<CorrectionsResponse>(`/dashboard/${id(domainId)}/corrections`)
export const getAnnotators = (domainId: string, limit = 50) => request<AnnotatorsResponse>(`/dashboard/${id(domainId)}/annotators${params({ limit })}`)
export const getFactors = (domainId: string) => request<FactorsResponse>(`/dashboard/${id(domainId)}/factors`)
export const getCompounding = (domainId: string, options: { window?: number; category?: string } = {}) => request<CompoundingResponse>(`/dashboard/${id(domainId)}/compounding${params(options)}`)
export const getAutonomy = (domainId: string) => request<AutonomyResponse>(`/domains/${id(domainId)}/autonomy`)
