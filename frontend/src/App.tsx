import { useEffect, useState } from 'react'
import { Recorder } from './components/Recorder'
import { TranscriptionPanel } from './components/TranscriptionPanel'
import { NotePanel } from './components/NotePanel'
import { FormatSelector } from './components/FormatSelector'
import {
  fetchFormats,
  postFeedback,
  postNote,
  postTranscribe,
  type ClinicalNote,
  type ClinicalNoteResponse,
  type FormatSummary,
  type SectionDiff,
  type TranscriptionResult,
} from './api/voiceSoap'

type State =
  | { kind: 'idle' }
  | { kind: 'transcribing' }
  | { kind: 'note_pending'; transcription: TranscriptionResult }
  | { kind: 'done'; transcription: TranscriptionResult; response: ClinicalNoteResponse }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [formats, setFormats] = useState<FormatSummary[]>([])
  const [formatId, setFormatId] = useState<string>('')
  const [formatsError, setFormatsError] = useState<string | null>(null)

  useEffect(() => {
    fetchFormats()
      .then((res) => {
        setFormats(res.formats)
        setFormatId(res.default_id)
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e)
        setFormatsError(`포맷 목록 로드 실패: ${msg}`)
      })
  }, [])

  const selectedFormat = formats.find((f) => f.id === formatId)

  async function handleRecorded(blob: Blob) {
    if (!selectedFormat) {
      setState({ kind: 'error', message: '포맷이 선택되지 않았습니다.' })
      return
    }
    setState({ kind: 'transcribing' })
    try {
      const transcription = await postTranscribe(blob)
      setState({ kind: 'note_pending', transcription })
      const response = await postNote(transcription.text, formatId)
      setState({ kind: 'done', transcription, response })
    } catch (e) {
      setState({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  function reset() {
    setState({ kind: 'idle' })
  }

  async function handleCopyAll(editedNote: ClinicalNote) {
    if (state.kind !== 'done' || !selectedFormat) return
    const t = state.transcription
    const r = state.response
    const diffs: SectionDiff[] = selectedFormat.sections.map((s) => {
      const original = r.note.sections[s.key] ?? ''
      const edited = editedNote.sections[s.key] ?? ''
      return { section: s.key, original, edited, changed: original !== edited }
    })
    try {
      await postFeedback({
        timestamp: new Date().toISOString(),
        audio_duration_seconds: t.audio_duration_seconds,
        raw_text: t.raw_text,
        corrected_text: t.text,
        format_id: r.format_id,
        original_note: r.note,
        edited_note: editedNote,
        diffs,
        applied_replacements: t.applied_replacements,
        uncertain_segments: r.note.uncertain_segments,
      })
    } catch (e) {
      // 학습 로그 실패는 critical 아님 — 외래 워크플로우 방해 X
      console.warn('feedback log failed:', e)
    }
  }

  // transcription이 도착했으면 즉시 표시 (note_pending / done 두 단계 모두)
  const transcription =
    state.kind === 'note_pending' || state.kind === 'done' ? state.transcription : null
  const noteKey = state.kind === 'done' ? state.response.source_text : null

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center px-4 py-8 gap-6">
      <header className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">Voice SOAP</h1>
        <p className="text-gray-500 text-sm mt-1">간장학 외래 음성 → 의무기록 자동 구조화 (로컬 전용)</p>
      </header>

      {formatsError && (
        <div className="max-w-2xl bg-red-50 border border-red-300 rounded-lg p-4 text-red-800">
          {formatsError}
        </div>
      )}

      {formats.length > 0 && (
        <FormatSelector
          formats={formats}
          selected={formatId}
          onChange={setFormatId}
          disabled={state.kind === 'transcribing' || state.kind === 'note_pending'}
        />
      )}

      {(state.kind === 'idle' || state.kind === 'error') && selectedFormat && (
        <Recorder onRecorded={handleRecorded} />
      )}

      {state.kind === 'transcribing' && (
        <div className="flex flex-col items-center gap-3 py-8">
          <div className="w-12 h-12 border-4 border-emerald-200 border-t-emerald-600 rounded-full animate-spin" />
          <div className="text-gray-700 text-sm">전사 중... (Whisper, 보통 10~15초)</div>
        </div>
      )}

      {state.kind === 'error' && (
        <div className="max-w-2xl bg-red-50 border border-red-300 rounded-lg p-4 text-red-800">
          <strong>요청 실패</strong>
          <p className="mt-1 text-sm">{state.message}</p>
          <p className="mt-2 text-xs text-red-600">
            백엔드(127.0.0.1:8080)와 LM Studio(127.0.0.1:1234)가 모두 켜져 있는지 확인하세요.
          </p>
        </div>
      )}

      {transcription && <TranscriptionPanel transcription={transcription} />}

      {state.kind === 'note_pending' && selectedFormat && (
        <div className="flex items-center gap-3 text-gray-600 text-sm py-2">
          <div className="w-5 h-5 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
          {selectedFormat.name} 구조화 중... (Gemma 3 12B, 보통 30~40초) — 위 전사 결과 검토하셔도 됩니다
        </div>
      )}

      {state.kind === 'done' && selectedFormat && (
        <>
          {/* key는 새 결과마다 컴포넌트 재마운트 → 편집 state 초기화 */}
          <NotePanel
            key={noteKey ?? undefined}
            response={state.response}
            format={selectedFormat}
            onCopyAll={handleCopyAll}
          />
          <button
            onClick={reset}
            className="px-5 py-2 rounded bg-gray-700 hover:bg-gray-800 text-white text-sm shadow"
          >
            새 녹음
          </button>
        </>
      )}
    </div>
  )
}
