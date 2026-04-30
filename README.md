# Voice SOAP

한국어 음성 → 간장학 SOAP 노트 자동 구조화 (로컬 전용).

전체 로드맵은 `plan.md` 참고. 현재 상태는 **Phase 1 첫 스프린트** — STT 백엔드만 구현됨.

## 빠른 시작

```bash
# 의존성 설치
uv sync

# 서버 실행 (127.0.0.1:8080 바인딩)
uv run uvicorn backend.main:app --port 8080

# 다른 터미널에서 healthcheck
curl http://localhost:8080/healthz

# wav 전사 (PoC 녹음 파일로 테스트)
curl -X POST http://localhost:8080/transcribe \
  -F "audio=@tests/fixtures/recording.wav;type=audio/wav" \
  | python -m json.tool
```

브라우저로 `http://localhost:8080/docs` 열면 Swagger UI에서 wav 직접 업로드 가능.

## 테스트

```bash
uv run pytest -v
```

## PoC vs 백엔드 회귀 검증

PoC 스크립트(`whisper_test.py`)와 백엔드의 텍스트 출력이 동일한지 확인:

```bash
# 1. PoC 기준선
uv run python whisper_test.py --file tests/fixtures/recording.wav --hints hints/medical_hints.txt

# 2. 백엔드 결과
uv run uvicorn backend.main:app --port 8080 &
sleep 2
curl -s -X POST http://localhost:8080/transcribe \
  -F "audio=@tests/fixtures/recording.wav;type=audio/wav" | python -c "import sys,json; print(json.load(sys.stdin)['text'])"
kill %1
```

두 출력 텍스트가 같아야 한다.

## 설정

환경변수로 override 가능 (`VOICE_SOAP_` 프리픽스):

| 변수 | 기본값 |
|---|---|
| `VOICE_SOAP_WHISPER_MODEL_REPO` | `mlx-community/whisper-large-v3-mlx` |
| `VOICE_SOAP_HINTS_FILE` | `hints/medical_hints.txt` |
| `VOICE_SOAP_HOST` | `127.0.0.1` |
| `VOICE_SOAP_PORT` | `8080` |

## 디렉토리

```
backend/
  main.py              # FastAPI 앱 + /healthz
  config.py            # 환경변수 기반 설정
  api/transcribe.py    # POST /transcribe
  stt/
    hints_loader.py    # 의학 힌트 사전
    whisper_engine.py  # mlx-whisper 래퍼 + TranscriptionResult
hints/medical_hints.txt
tests/
  test_hints_loader.py
  test_health.py
  fixtures/recording.wav
```

## 구현 완료 / 진행 중

- ✅ `POST /soap` — LM Studio LLM 호출로 SOAP JSON 구조화 (현재 LLM: Gemma 3 12B Dense MLX 4bit)
- ✅ `POST /process` — 통합 (wav → SOAP)
- ✅ 후처리 사전 (`hints/postprocess.yaml`) — 약물명 환각 차단 (예: 표로세미드→푸로세미드)
- ⏳ 환자 식별자 마스킹 (다음 스프린트)
- ⏳ Phase 2 웹 UI (다음 스프린트)

## 보안 원칙 (`plan.md` §7)

- `127.0.0.1` 바인딩 (외부 접근 차단)
- 업로드 wav는 처리 직후 즉시 삭제 (디스크 잔존 X)
- 로그에 텍스트 본문 미포함 (메타데이터만)
