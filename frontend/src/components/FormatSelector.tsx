import type { FormatSummary } from '../api/voiceSoap'

interface Props {
  formats: FormatSummary[]
  selected: string
  onChange: (id: string) => void
  disabled?: boolean
}

export function FormatSelector({ formats, selected, onChange, disabled }: Props) {
  if (formats.length === 0) return null
  return (
    <fieldset
      className="w-full max-w-3xl bg-white border border-gray-200 rounded-lg p-3 shadow-sm"
      disabled={disabled}
    >
      <legend className="px-2 text-xs font-semibold text-gray-500">진료 포맷</legend>
      <div className="flex flex-wrap gap-3">
        {formats.map((f) => (
          <label
            key={f.id}
            className={`flex items-center gap-2 px-3 py-2 rounded border cursor-pointer text-sm ${
              selected === f.id
                ? 'bg-blue-50 border-blue-400 text-blue-800'
                : 'bg-gray-50 border-gray-200 text-gray-700 hover:bg-gray-100'
            } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
          >
            <input
              type="radio"
              name="format"
              value={f.id}
              checked={selected === f.id}
              onChange={() => onChange(f.id)}
              disabled={disabled}
              className="accent-blue-600"
            />
            <span className="font-medium">{f.name}</span>
            <span className="text-gray-400 text-xs">
              ({f.sections.length}섹션)
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
