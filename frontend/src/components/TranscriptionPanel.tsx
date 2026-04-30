import type { TranscriptionResult } from '../api/voiceSoap'

interface Props {
  transcription: TranscriptionResult
}

export function TranscriptionPanel({ transcription: t }: Props) {
  return (
    <section className="w-full max-w-3xl bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-500">전사 결과 (STT)</h3>
        <span className="text-xs text-gray-400 tabular-nums">
          {t.elapsed_seconds.toFixed(1)}s · 음성 {t.audio_duration_seconds.toFixed(1)}s · RTF {t.rtf.toFixed(2)}
        </span>
      </div>
      <p className="text-gray-900 whitespace-pre-wrap">{t.text}</p>
      {t.applied_replacements.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-gray-500">
            후처리 사전 보정 {t.applied_replacements.length}개 + STT 원본
          </summary>
          <div className="mt-2 space-y-2 text-xs text-gray-600">
            <ul className="list-disc list-inside">
              {t.applied_replacements.map((r, i) => (
                <li key={i}>
                  [{r.category}] <code>{r.pattern}</code> → <code>{r.replace}</code> (×{r.count})
                </li>
              ))}
            </ul>
            <div>
              <strong>원본:</strong>
              <p className="mt-1 whitespace-pre-wrap">{t.raw_text}</p>
            </div>
          </div>
        </details>
      )}
    </section>
  )
}
