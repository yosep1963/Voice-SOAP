import { useEffect, useRef, useState } from 'react'

interface Props {
  onRecorded: (blob: Blob) => void
  disabled?: boolean
}

type Status = 'idle' | 'recording' | 'requesting'

export function Recorder({ onRecorded, disabled = false }: Props) {
  const [status, setStatus] = useState<Status>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const startedAtRef = useRef<number>(0)
  const intervalRef = useRef<number | null>(null)

  // 진행 시간 카운터
  useEffect(() => {
    if (status !== 'recording') return
    intervalRef.current = window.setInterval(() => {
      setElapsed((Date.now() - startedAtRef.current) / 1000)
    }, 200)
    return () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current)
    }
  }, [status])

  async function start() {
    setError(null)
    setElapsed(0)
    setStatus('requesting')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'
      const rec = new MediaRecorder(stream, { mimeType: mime })
      chunksRef.current = []
      rec.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        onRecorded(blob)
      }
      recorderRef.current = rec
      startedAtRef.current = Date.now()
      rec.start()
      setStatus('recording')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('idle')
    }
  }

  function stop() {
    recorderRef.current?.stop()
    recorderRef.current = null
    setStatus('idle')
  }

  const isRec = status === 'recording'
  return (
    <div className="flex flex-col items-center gap-3">
      <button
        type="button"
        onClick={isRec ? stop : start}
        disabled={disabled || status === 'requesting'}
        className={`w-40 h-40 rounded-full text-white font-semibold text-lg shadow-lg transition active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed ${
          isRec ? 'bg-red-600 hover:bg-red-700 animate-pulse' : 'bg-emerald-600 hover:bg-emerald-700'
        }`}
      >
        {isRec ? '⏹ 종료' : '🎙 녹음'}
      </button>
      {isRec && (
        <div className="text-2xl font-mono tabular-nums text-red-700">
          {elapsed.toFixed(1)}초
        </div>
      )}
      {error && <div className="text-red-600 text-sm max-w-md text-center">⚠️ {error}</div>}
    </div>
  )
}
