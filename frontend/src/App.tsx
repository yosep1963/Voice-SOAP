import { useState } from 'react'
import { Recorder } from './components/Recorder'
import { TranscriptionPanel } from './components/TranscriptionPanel'
import { SoapPanel } from './components/SoapPanel'
import {
  postFeedback,
  postSoap,
  postTranscribe,
  type SectionDiff,
  type SoapNote,
  type SoapResponse,
  type TranscriptionResult,
} from './api/voiceSoap'

type State =
  | { kind: 'idle' }
  | { kind: 'transcribing' }
  | { kind: 'soap_pending'; transcription: TranscriptionResult }
  | { kind: 'done'; transcription: TranscriptionResult; soap: SoapResponse }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'idle' })

  async function handleRecorded(blob: Blob) {
    setState({ kind: 'transcribing' })
    try {
      const transcription = await postTranscribe(blob)
      setState({ kind: 'soap_pending', transcription })
      const soap = await postSoap(transcription.text)
      setState({ kind: 'done', transcription, soap })
    } catch (e) {
      setState({ kind: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  function reset() {
    setState({ kind: 'idle' })
  }

  async function handleCopyAll(editedNote: SoapNote) {
    if (state.kind !== 'done') return
    const t = state.transcription
    const s = state.soap
    const sections: SectionDiff['section'][] = ['subjective', 'objective', 'assessment', 'plan']
    const diffs: SectionDiff[] = sections.map((section) => ({
      section,
      original: s.note[section],
      edited: editedNote[section],
      changed: s.note[section] !== editedNote[section],
    }))
    try {
      await postFeedback({
        timestamp: new Date().toISOString(),
        audio_duration_seconds: t.audio_duration_seconds,
        raw_text: t.raw_text,
        corrected_text: t.text,
        original_note: s.note,
        edited_note: editedNote,
        diffs,
        applied_replacements: t.applied_replacements,
        uncertain_segments: s.note.uncertain_segments,
      })
    } catch (e) {
      // 학습 로그 실패는 critical 아님 — 외래 워크플로우 방해 X
      console.warn('feedback log failed:', e)
    }
  }

  // transcription이 도착했으면 즉시 표시 (soap_pending / done 두 단계 모두)
  const transcription =
    state.kind === 'soap_pending' || state.kind === 'done' ? state.transcription : null
  const soapKey = state.kind === 'done' ? state.soap.source_text : null

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col items-center px-4 py-8 gap-6">
      <header className="text-center">
        <h1 className="text-3xl font-bold text-gray-900">Voice SOAP</h1>
        <p className="text-gray-500 text-sm mt-1">간장학 외래 음성 → SOAP 자동 구조화 (로컬 전용)</p>
      </header>

      {(state.kind === 'idle' || state.kind === 'error') && (
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

      {state.kind === 'soap_pending' && (
        <div className="flex items-center gap-3 text-gray-600 text-sm py-2">
          <div className="w-5 h-5 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
          SOAP 구조화 중... (Gemma 3 12B, 보통 30~40초) — 위 전사 결과 검토하셔도 됩니다
        </div>
      )}

      {state.kind === 'done' && (
        <>
          {/* key는 새 결과마다 컴포넌트 재마운트 → 편집 state 초기화 */}
          <SoapPanel key={soapKey ?? undefined} soap={state.soap} onCopyAll={handleCopyAll} />
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
