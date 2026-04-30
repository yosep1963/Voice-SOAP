import { useLayoutEffect, useRef, useState } from 'react'
import type { SoapNote, SoapResponse } from '../api/voiceSoap'

interface Props {
  soap: SoapResponse
  onCopyAll?: (editedNote: SoapNote) => void
}

type SectionKey = 'subjective' | 'objective' | 'assessment' | 'plan'

const SECTIONS: { key: SectionKey; label: string; short: string }[] = [
  { key: 'subjective', label: 'S — Subjective (주관)', short: 'S' },
  { key: 'objective', label: 'O — Objective (객관)', short: 'O' },
  { key: 'assessment', label: 'A — Assessment (평가)', short: 'A' },
  { key: 'plan', label: 'P — Plan (계획)', short: 'P' },
]

export function SoapPanel({ soap: s, onCopyAll }: Props) {
  const [text, setText] = useState({
    subjective: s.note.subjective,
    objective: s.note.objective,
    assessment: s.note.assessment,
    plan: s.note.plan,
  })
  const [copiedKey, setCopiedKey] = useState<SectionKey | 'all' | null>(null)

  async function copy(key: SectionKey | 'all') {
    const payload =
      key === 'all'
        ? SECTIONS.map(({ key: k, short }) => `[${short}] ${text[k] || '(비어있음)'}`).join('\n\n')
        : text[key]
    await navigator.clipboard.writeText(payload)
    setCopiedKey(key)
    window.setTimeout(() => setCopiedKey(null), 1500)

    if (key === 'all' && onCopyAll) {
      // 전체 복사 = 외래 검토 완료 시점 → 학습 로그 (Phase 5)
      onCopyAll({
        ...text,
        uncertain_segments: s.note.uncertain_segments,
      })
    }
  }

  return (
    <div className="w-full max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">
          SOAP 결과 <span className="text-xs font-normal text-gray-400">· LLM {s.elapsed_seconds.toFixed(1)}s · 편집 가능</span>
        </h2>
        <button
          onClick={() => copy('all')}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium shadow"
        >
          {copiedKey === 'all' ? '✓ 복사됨' : '📋 전체 복사'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3">
        {SECTIONS.map(({ key, label }) => (
          <section key={key} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-500">{label}</h3>
              <button
                onClick={() => copy(key)}
                className="text-xs px-2 py-1 rounded text-gray-600 hover:text-blue-700 hover:bg-blue-50"
                title="이 섹션만 복사"
              >
                {copiedKey === key ? '✓' : '📋'}
              </button>
            </div>
            <AutoTextarea
              value={text[key]}
              onChange={(v) => setText((prev) => ({ ...prev, [key]: v }))}
              placeholder={key === 'assessment' ? '진단/평가 — 의사가 명시 안 하면 비어있음 (직접 입력)' : '비어있음'}
            />
          </section>
        ))}
      </div>

      {s.note.uncertain_segments.length > 0 && (
        <section className="bg-amber-50 border border-amber-300 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">
            ⚠️ 검토 필요 (모호 표현 {s.note.uncertain_segments.length}개)
          </h3>
          <ul className="list-disc list-inside text-amber-900 text-sm space-y-1">
            {s.note.uncertain_segments.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </section>
      )}

      {!s.validation.passed && (
        <section className="bg-red-50 border border-red-300 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-red-800 mb-2">⛔ 환각 검증 경고</h3>
          <ul className="list-disc list-inside text-red-900 text-sm space-y-1">
            {s.validation.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
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
