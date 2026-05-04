import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import type {
  ClinicalNote,
  ClinicalNoteResponse,
  FormatSummary,
} from '../api/voiceSoap'

interface Props {
  response: ClinicalNoteResponse
  format: FormatSummary
  onCopyAll?: (editedNote: ClinicalNote) => void
}

export function NotePanel({ response: r, format, onCopyAll }: Props) {
  const initialText = useMemo(() => {
    const t: Record<string, string> = {}
    for (const s of format.sections) {
      t[s.key] = r.note.sections[s.key] ?? ''
    }
    return t
  }, [format, r.note.sections])

  const [text, setText] = useState<Record<string, string>>(initialText)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)

  async function copy(key: string | 'all') {
    const payload =
      key === 'all'
        ? format.sections
            .map((s) => `[${s.short || s.key.toUpperCase()}] ${text[s.key] || '(비어있음)'}`)
            .join('\n\n')
        : text[key] ?? ''
    const ok = await writeClipboard(payload)
    if (!ok) {
      setCopyError('클립보드 쓰기 실패. 섹션 텍스트를 직접 선택해 복사하세요.')
      return
    }
    setCopiedKey(key)
    setCopyError(null)
    window.setTimeout(() => setCopiedKey(null), 1500)

    if (key === 'all' && onCopyAll) {
      onCopyAll({
        sections: { ...text },
        uncertain_segments: r.note.uncertain_segments,
      })
    }
  }

  return (
    <div className="w-full max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">
          {format.name} 결과{' '}
          <span className="text-xs font-normal text-gray-400">
            · LLM {r.elapsed_seconds.toFixed(1)}s · 편집 가능
          </span>
        </h2>
        <button
          onClick={() => copy('all')}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium shadow"
        >
          {copiedKey === 'all' ? '✓ 복사됨' : '📋 전체 복사'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {format.sections.map((s) => (
          <section
            key={s.key}
            className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm"
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-500">{s.label}</h3>
              <button
                onClick={() => copy(s.key)}
                className="text-xs px-2 py-1 rounded text-gray-600 hover:text-blue-700 hover:bg-blue-50"
                title="이 섹션만 복사"
              >
                {copiedKey === s.key ? '✓' : '📋'}
              </button>
            </div>
            <AutoTextarea
              value={text[s.key] ?? ''}
              onChange={(v) => setText((prev) => ({ ...prev, [s.key]: v }))}
              placeholder={s.definition}
            />
          </section>
        ))}
      </div>

      {r.note.uncertain_segments.length > 0 && (
        <section className="bg-amber-50 border border-amber-300 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">
            ⚠️ 검토 필요 (모호 표현 {r.note.uncertain_segments.length}개)
          </h3>
          <ul className="list-disc list-inside text-amber-900 text-sm space-y-1">
            {r.note.uncertain_segments.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </section>
      )}

      {copyError && (
        <div className="bg-red-50 border border-red-300 rounded-lg p-3 text-sm text-red-800">
          {copyError}
        </div>
      )}

      {!r.validation.passed && (
        <section className="bg-red-50 border border-red-300 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-red-800 mb-2">⛔ 환각 검증 경고</h3>
          <ul className="list-disc list-inside text-red-900 text-sm space-y-1">
            {r.validation.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

async function writeClipboard(text: string): Promise<boolean> {
  // Safari/document-blur 등으로 navigator.clipboard.writeText가 실패하는 경우의
  // 안전망. textarea+execCommand fallback (legacy 브라우저).
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return legacyCopy(text)
  }
}

function legacyCopy(text: string): boolean {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '0'
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  } finally {
    document.body.removeChild(ta)
  }
  return ok
}

interface AutoTextareaProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

function AutoTextarea({ value, onChange, placeholder }: AutoTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight, 40)}px`
  }, [value])
  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full text-gray-900 bg-gray-50 border border-gray-200 rounded p-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-300 focus:bg-white whitespace-pre-wrap"
    />
  )
}
