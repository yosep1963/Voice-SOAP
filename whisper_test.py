#!/usr/bin/env python3
"""
Whisper 한국어 의학 STT 테스트 v3
- 외부 힌트 파일(medical_hints.txt) 자동 로딩
- 자동 입력 장치 감지
"""

import argparse
import sys
import time
import wave
from pathlib import Path


# 폴백용 기본 힌트 (medical_hints.txt 없을 때만 사용)
DEFAULT_PROMPT = (
    "간장학 외래 진료 기록입니다. "
    "주요 용어: 간경변, 정맥류, 복수, 황달, 간성혼수, 간세포암, "
    "MELD, Child-Pugh, AST, ALT, 빌리루빈."
)


def load_hints(hints_file="medical_hints.txt"):
    """medical_hints.txt 로딩. 주석/빈 줄 제거."""
    path = Path(hints_file)
    if not path.exists():
        # 스크립트 같은 폴더에서 한 번 더 찾기
        path = Path(__file__).parent / hints_file
        if not path.exists():
            print(f"⚠️  {hints_file} 없음. 기본 힌트 사용.")
            return DEFAULT_PROMPT

    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    prompt = " ".join(lines)
    print(f"📚 힌트 로딩: {path.name} ({len(prompt)}자)")
    return prompt


TEST_PHRASES = [
    "60세 남자 환자, B형 간염으로 인한 간경변 추적 중입니다.",
    "MELD 점수 18점, Child-Pugh B 7점입니다.",
    "복부 초음파에서 5cm 간세포암이 우엽에 발견되었습니다.",
    "아테졸리주맙 베바시주맙 병용요법 시작 예정입니다.",
    "락툴로오스 30cc 하루 세 번, 리팍시민 550mg 하루 두 번 처방드립니다.",
    "AST 85, ALT 92, 총빌리루빈 2.3, 알부민 3.1, INR 1.4입니다.",
    "정맥류 출혈 과거력 있어 프로프라놀롤 복용 중입니다.",
    "간성혼수 grade 2로 입원 치료 후 호전되었습니다.",
    "엔테카비르 0.5mg 매일 복용 중이며 HBV DNA 검출되지 않습니다.",
    "복수 조절 위해 푸로세미드 40mg 스피로노락톤 100mg 증량합니다.",
]


def find_input_device(preferred_index=None):
    import sounddevice as sd
    devices = sd.query_devices()

    if preferred_index is not None:
        d = devices[preferred_index]
        if d["max_input_channels"] == 0:
            print(f"❌ 장치 {preferred_index}는 입력 장치가 아닙니다.")
            sys.exit(1)
        return preferred_index, min(d["max_input_channels"], 2)

    input_devices = [(i, d) for i, d in enumerate(devices)
                     if d["max_input_channels"] > 0]
    if not input_devices:
        print("❌ 입력 장치 없음.")
        sys.exit(1)

    for kw in ["usb", "mic", "head"]:
        for i, d in input_devices:
            if kw in d["name"].lower():
                return i, min(d["max_input_channels"], 2)

    i, d = input_devices[0]
    return i, min(d["max_input_channels"], 2)


def list_devices():
    import sounddevice as sd
    print("\n🎤 오디오 장치:\n")
    for i, d in enumerate(sd.query_devices()):
        marker = "🎙️ " if d["max_input_channels"] > 0 else "🔊 "
        print(f"  {marker}[{i}] {d['name']} "
              f"(in: {d['max_input_channels']}, out: {d['max_output_channels']})")
    print()


def record_audio(duration, output_path="recording.wav", device_index=None):
    try:
        import sounddevice as sd
        import scipy.io.wavfile as wav
        import numpy as np
    except ImportError:
        print("❌ 패키지 누락")
        sys.exit(1)

    dev_idx, channels = find_input_device(device_index)
    dev_info = sd.query_devices(dev_idx)
    print(f"🎤 사용 장치: [{dev_idx}] {dev_info['name']} ({channels}ch)")

    native_sr = int(dev_info["default_samplerate"])
    target_sr = 16000

    print(f"🎙️  {duration}초 녹음 시작... ({native_sr}Hz)")
    print("   (Ctrl+C로 중단)")

    try:
        audio = sd.rec(int(duration * native_sr), samplerate=native_sr,
                       channels=channels, dtype="int16", device=dev_idx)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\n중단됨")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 녹음 실패: {e}")
        sys.exit(1)

    if channels > 1:
        audio = audio.mean(axis=1).astype(np.int16)

    if native_sr != target_sr:
        from scipy.signal import resample_poly
        audio = resample_poly(audio, target_sr, native_sr).astype(np.int16)

    wav.write(output_path, target_sr, audio)
    print(f"✅ 저장됨: {output_path}\n")
    return output_path


def transcribe(audio_path, model_repo, prompt):
    try:
        import mlx_whisper
    except ImportError:
        print("❌ mlx-whisper 필요")
        sys.exit(1)

    start = time.time()
    result = mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=model_repo,
        language="ko",
        initial_prompt=prompt,
        word_timestamps=False,
        verbose=None,
    )
    return result, time.time() - start


def get_audio_duration(audio_path):
    try:
        with wave.open(str(audio_path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def print_result(label, result, elapsed, audio_dur):
    text = result["text"].strip()
    rtf = elapsed / audio_dur if audio_dur > 0 else 0
    print("=" * 70)
    print(f"📋 {label}")
    print("=" * 70)
    print(text)
    print("-" * 70)
    print(f"⏱️  오디오 {audio_dur:.1f}s | 처리 {elapsed:.1f}s | RTF {rtf:.2f}x")
    if "segments" in result:
        low = [s for s in result["segments"] if s.get("avg_logprob", 0) < -0.5]
        if low:
            print(f"⚠️  신뢰도 낮은 구간 {len(low)}개:")
            for s in low[:3]:
                print(f"   [{s['start']:.1f}s] {s['text'].strip()[:60]} "
                      f"(logprob={s['avg_logprob']:.2f})")
    print()


def run_compare(audio_path, model_repo, prompt):
    audio_dur = get_audio_duration(audio_path)
    print("\n🔬 비교 모드: 의학용어 힌트 효과\n")
    print("⏳ [1/2] 힌트 없이...")
    r1, t1 = transcribe(audio_path, model_repo, None)
    print_result("힌트 없음", r1, t1, audio_dur)
    print("⏳ [2/2] 의학용어 힌트...")
    r2, t2 = transcribe(audio_path, model_repo, prompt)
    print_result("의학용어 힌트 적용", r2, t2, audio_dur)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", "-f")
    p.add_argument("--record", "-r", type=int, default=0)
    p.add_argument("--device", "-d", type=int, default=None)
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--model", "-m",
                   default="mlx-community/whisper-large-v3-mlx")
    p.add_argument("--hints", default="medical_hints.txt",
                   help="힌트 파일 경로")
    p.add_argument("--no-prompt", action="store_true")
    p.add_argument("--compare", action="store_true")
    p.add_argument("--show-phrases", action="store_true")
    p.add_argument("--show-hints", action="store_true",
                   help="현재 로딩되는 힌트 출력")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return
    if args.show_phrases:
        print("\n📖 추천 테스트 문장:\n")
        for i, ph in enumerate(TEST_PHRASES, 1):
            print(f"  {i:2d}. {ph}")
        print()
        return
    if args.show_hints:
        prompt = load_hints(args.hints)
        print(f"\n--- 현재 힌트 ({len(prompt)}자) ---\n{prompt}\n")
        return

    prompt = load_hints(args.hints)

    if args.record > 0:
        audio_path = record_audio(args.record, device_index=args.device)
    elif args.file:
        audio_path = args.file
        if not Path(audio_path).exists():
            print(f"❌ 파일 없음: {audio_path}")
            sys.exit(1)
    else:
        p.print_help()
        sys.exit(0)

    if args.compare:
        run_compare(audio_path, args.model, prompt)
    else:
        active_prompt = None if args.no_prompt else prompt
        label = "힌트 없음" if args.no_prompt else "의학용어 힌트"
        print(f"\n⏳ 전사 중... ({args.model})")
        result, elapsed = transcribe(audio_path, args.model, active_prompt)
        audio_dur = get_audio_duration(audio_path)
        print()
        print_result(label, result, elapsed, audio_dur)


if __name__ == "__main__":
    main()
