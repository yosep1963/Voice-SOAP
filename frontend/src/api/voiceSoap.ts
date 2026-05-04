// 백엔드 응답 타입. backend의 pydantic 모델과 동기화 유지.

export interface AppliedReplacement {
  pattern: string
  replace: string
  category: string
  count: number
}

export interface LowConfidenceSegment {
  start: number
  end: number
  text: string
  avg_logprob: number
}

export interface TranscriptionResult {
  text: string
  raw_text: string
  model: string
  elapsed_seconds: number
  audio_duration_seconds: number
  rtf: number
  low_confidence_segments: LowConfidenceSegment[]
  used_hints: boolean
  applied_replacements: AppliedReplacement[]
}

// 포맷 메타데이터 (GET /formats)
export interface Section {
  key: string
  label: string
  short: string
  definition: string
}

export interface FormatSummary {
  id: string
  name: string
  sections: Section[]
}

export interface FormatsResponse {
  formats: FormatSummary[]
  default_id: string
}

// 일반화된 의무기록 (POST /note)
export interface ClinicalNote {
  sections: Record<string, string>
  uncertain_segments: string[]
}

export interface ValidationReport {
  passed: boolean
  warnings: string[]
  extra_numbers: string[]
}

export interface ClinicalNoteResponse {
  note: ClinicalNote
  validation: ValidationReport
  model: string
  elapsed_seconds: number
  source_text: string
  format_id: string
}

export interface SectionDiff {
  section: string
  original: string
  edited: string
  changed: boolean
}

export interface EditFeedback {
  timestamp: string
  audio_duration_seconds: number
  raw_text: string
  corrected_text: string
  format_id: string
  original_note: ClinicalNote
  edited_note: ClinicalNote
  diffs: SectionDiff[]
  applied_replacements: AppliedReplacement[]
  uncertain_segments: string[]
}

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8080'

export async function fetchFormats(): Promise<FormatsResponse> {
  const r = await fetch(`${BACKEND_URL}/formats`)
  if (!r.ok) throw await asError(r)
  return (await r.json()) as FormatsResponse
}

export async function postTranscribe(audioBlob: Blob): Promise<TranscriptionResult> {
  const form = new FormData()
  form.append('audio', audioBlob, `recording.${blobExtension(audioBlob)}`)
  const r = await fetch(`${BACKEND_URL}/transcribe`, { method: 'POST', body: form })
  if (!r.ok) throw await asError(r)
  return (await r.json()) as TranscriptionResult
}

export async function postNote(text: string, formatId: string): Promise<ClinicalNoteResponse> {
  const r = await fetch(`${BACKEND_URL}/note`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text, format_id: formatId }),
  })
  if (!r.ok) throw await asError(r)
  return (await r.json()) as ClinicalNoteResponse
}

export async function postFeedback(payload: EditFeedback): Promise<void> {
  const r = await fetch(`${BACKEND_URL}/feedback`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw await asError(r)
}

async function asError(r: Response): Promise<Error> {
  const detail = await r.text()
  return new Error(`HTTP ${r.status}: ${detail.slice(0, 300)}`)
}

function blobExtension(blob: Blob): string {
  const t = blob.type
  if (t.includes('webm')) return 'webm'
  if (t.includes('ogg')) return 'ogg'
  if (t.includes('mp4') || t.includes('m4a')) return 'm4a'
  if (t.includes('wav')) return 'wav'
  if (t.includes('mpeg')) return 'mp3'
  return 'bin'
}
