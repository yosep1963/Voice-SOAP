# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

한국어 음성 dictation을 간장학 SOAP 의무기록으로 자동 구조화하는 **로컬 전용** 시스템. 외래 진료실 워크플로우(환자당 1분 이하)를 위한 도구로, 의료법/PIPA 제약 때문에 **외부 네트워크 호출을 절대 금지**한다.

`plan.md`가 마스터 플랜(5 Phase)이며 모든 설계 결정의 근거다. 새 결정은 `plan.md`의 §"변경 이력"에 추가하거나 별도 노트로 기록한다.

**현재 상태 (2026-04-29)**: Phase 1 거의 완료 + Phase 2 웹 UI MVP 동작 + Phase 5 학습 시스템 시작. 외래 5명 부하 시뮬레이션 통과(메모리 81~83%, 평균 LLM 7.4s, 환각 0%) — `plan.md §2 외래 부하 시뮬레이션` 참고. **본 개발 GO 단계**, 사용자 외래 실사용 + 편집 diff 누적 단계로 진입.

## 명령어

### 백엔드 (repo 루트)

```bash
uv sync                                                       # 의존성 설치/동기화
uv run uvicorn backend.main:app --port 8080                   # 서버 실행 (127.0.0.1 바인딩 강제)
uv run pytest -v                                              # 전체 테스트 (32개)
uv run pytest -m "not integration" -v                         # Whisper 모델 로드 안 하는 빠른 테스트
uv run pytest tests/test_postprocess.py::test_apply_basic_replacement  # 단일 테스트
uv run python whisper_test.py --file <wav> --hints hints/medical_hints.txt  # PoC 회귀 기준선
```

### 프론트엔드 (`frontend/`)

```bash
cd frontend && pnpm install                                   # 의존성 설치
pnpm dev                                                      # Vite dev server (127.0.0.1:5173)
pnpm exec tsc --noEmit -p tsconfig.app.json                   # 타입 체크 (lint 대용)
```

설정 override는 `VOICE_SOAP_` 프리픽스 환경변수 (`backend/config.py:Settings`와 매핑). 예: `VOICE_SOAP_LLM_MODEL=qwen2.5-14b-instruct`, `VOICE_SOAP_FEEDBACK_LOG_PATH=/tmp/edits.jsonl`.

## 아키텍처 요점

**Whisper 호출 시그니처는 PoC와 의도적으로 다르다.** 초기엔 PoC `whisper_test.py`와 동일했으나, 사용자 녹음에서 *"활활활..."* 무한 반복 환각이 발견되어 `condition_on_previous_text=False`(이전 segment 컨텍스트로 잘못 생성 연쇄 차단)와 `compression_ratio_threshold=2.0`(반복 감지 시 fallback temperature 재시도) 두 옵션이 추가됨. **부작용**: 미세하게 PoC와 텍스트가 달라질 수 있음(예: *"총 빌리루빈"* → *"청비루빈"*). 후처리 사전이 변형을 흡수하는 구조. 회귀 검증은 PoC 글자 단위 일치가 아니라 *의학 용어 정확도 + 환각 부재* 기준.

**힌트 사전과 후처리 사전 모두 startup에 검증된다.** `backend/main.py:lifespan`에서 `load_hints()` + `get_cached_rules()` 호출. 파일 부재 시 서버가 즉시 실패. PoC의 `DEFAULT_PROMPT` 폴백은 의도적으로 제거 — 백엔드는 명시적 설정만 허용.

**후처리 사전은 LLM 호출 전에 적용된다.** `hints/postprocess.yaml`의 정규식 룰이 `apply_postprocess()`로 STT 출력에 적용되어 `text` 필드를 만들고, `raw_text`에 Whisper 원본이 보존된다. 순서가 중요한 이유: LLM이 의학 문맥으로 약물명을 자체 보정하다 다른 약물로 잘못 추측하는 환각(예: 표로세미드→토르세미드)을 사전 차단. **새 룰 추가 시**: `category=drug`가 가장 위험하므로 *"다른 발화에서 의도치 않은 치환 가능성"* 항상 검토. 한자어 "의협"처럼 의사협회 등 다른 의미와 충돌하는 패턴은 사전에 넣지 않고 LLM의 `uncertain_segments`(`[?]`)에 의존.

**SOAP 응답의 Assessment가 빈 값으로 나오는 것은 의도된 보수적 동작이다.** `backend/soap/prompts.py:SYSTEM_PROMPT`의 *"명시되지 않은 섹션은 빈 문자열로 두세요"* 규칙 + few-shot 5개(LC f/u, HCC, HE, 정맥류, 검사결과만)의 결과. 26B는 추측해서 채웠는데 그게 환각 위험 — 12B QAT의 보수적 응답이 더 안전. **사용자가 textarea에서 직접 입력**하는 흐름이 plan.md/Phase 2 UI 설계의 전제. 강제로 채우게 하면 약물 환각(토르세미드 케이스) 위험 ↑.

**보안 표면은 Phase 단계에 따라 점진적으로 도입된다.**
- ✅ `127.0.0.1` 바인딩 (외부 네트워크 차단)
- ✅ CORS — Vite dev server(`localhost:5173`, `127.0.0.1:5173`)만 허용 (`backend/config.py:cors_origins`). 외부 origin 추가 금지.
- ✅ 업로드 오디오 처리 직후 즉시 삭제 (`tempfile.NamedTemporaryFile(delete=False)` + `try/finally`. `delete=True`는 macOS에서 mlx_whisper가 닫힌 핸들 읽기 시도하므로 수동 처리)
- ✅ 마스킹 — `POST /feedback` 저장 시점에 `backend/privacy/masking.py`로 주민번호/등록번호 마스킹 (의학 검사 수치 1-3자리는 영향 X)
- ⏳ 24h 자동 삭제 정책 (DB 도입 시점)
- ⏳ 환자 이름 마스킹 (LLM 후처리 단계)

지금 단계에서 미적용 보안 기능을 미리 추가하지 말 것 — YAGNI + plan.md §7가 도입 시점을 명시.

**업로드 오디오는 wav 외에도 webm/ogg/m4a/mp3을 받는다.** `backend/api/transcribe.py:ALLOWED_CONTENT_TYPES`. 브라우저 MediaRecorder는 webm/opus가 기본이라 Phase 2 웹 UI에서 필수. mlx_whisper는 ffmpeg 통해 모든 포맷 디코딩. **단, `get_audio_duration()`은 wav만 wave 모듈로 처리** — webm 등은 ffprobe fallback 사용 (`backend/stt/whisper_engine.py`). ffprobe는 mlx-whisper의 ffmpeg 의존성으로 시스템에 이미 있음.

**PoC 자산은 의도적으로 루트에 남아있다.** `whisper_test.py`, `medical_hints.txt`, `recording.wav`는 회귀 검증 기준선으로 보존. `medical_hints.txt`는 `hints/`로 복사되었지만 원본도 유지 — PoC 스크립트가 직접 참조.

## 프론트엔드 (Phase 2 MVP)

**2단계 UX**: STT 결과를 먼저 표시(10~15s) → SOAP는 그 위에 30~40s 후 추가. App의 상태 머신이 `idle → transcribing → soap_pending → done` 순서. `/transcribe`와 `/soap`을 별도 호출 (`/process` 통합 엔드포인트는 백엔드 직접 호출용으로 유지). 외래에서 텍스트만이라도 즉시 봐서 검토 시작 가능 — 체감 시간 큰 개선.

**SOAP는 textarea 4개로 편집 가능, 섹션별 + 전체 복사**. `SoapPanel.tsx`의 `AutoTextarea`가 자동 height 조절. 새 결과 들어오면 `key` prop으로 컴포넌트 재마운트 → 편집 state 초기화.

**전체 복사 시점이 학습 로그 트리거다.** `SoapPanel`의 `onCopyAll` 콜백 → `App.handleCopyAll` → `postFeedback()`. 사용자가 SOAP 검토 끝낸 시점(=EMR로 옮기는 시점)에 LLM 출력 vs 사용자 편집본 diff가 마스킹 후 `logs/edits.jsonl`에 한 줄 추가. 실패는 silent (외래 워크플로우 방해 X).

## LLM 통합

LM Studio가 OpenAI 호환 엔드포인트(`http://localhost:1234/v1`)를 제공. 모델 ID `gemma-3-12b-it-qat` (Gemma 3 12B Instruct QAT MLX 4bit, ~7-8GB). **LM Studio 설정** (외래 부하 시뮬레이션에서 검증):
- Context Length: **3072** (KV cache 25% 감소, few-shot 5개 + dictation + 응답 토큰 안전 마진)
- **Auto-Evict ON**, Idle TTL **15분** (외래 끊긴 시간 자동 unload, 새 요청 시 자동 재로드)

**모델 결정 이력 (간략)**: 26B A4B MoE → 88% 메모리 압박 → 12B Dense 시도 → Gemma 4 12B 미배포 → Gemma 3 12B QAT 확정. 폴백 순서: Qwen 2.5 14B → Qwen 3 14B → Gemma 3 27B (`plan.md` §4).

**SOAP 프롬프트의 핵심 제약은 "원문에 없는 정보 추가 금지"** — `prompts.py:SYSTEM_PROMPT`. plan.md §6과 동기화 유지. `payload.max_tokens=500`, `temperature=0.1`. 응답에 ```json``` 펜스가 들어와도 `llm_client.py:_extract_json()`이 자동 strip. 매 응답마다 `validator.py`가 숫자 diff 검증 — 원문에 없는 숫자가 SOAP에 들어오면 환각 의심 경고.

## 학습 시스템 (Phase 5 시작점)

`POST /feedback`이 사용자 편집 diff를 `logs/edits.jsonl`에 누적. 모든 텍스트 필드는 저장 전 `mask_identifiers()` 통과. **분석은 미구현** — 데이터 누적 단계. 일주일~한 달 후 jsonl 파일을 직접 분석해서 자주 수정되는 패턴을 후처리 사전 후보로 도출하는 것이 다음 작업.

`logs/`는 `.gitignore`에 등록되어 절대 커밋되지 않음.

## 코드 스타일

- 파일당 ~150줄 상한 (`plan.md` §6). 도메인 기반 분리 (`backend/{stt,soap,privacy,feedback,api}`).
- 명시적 타입 힌트 (Python 3.11 syntax: `list[str]`, `str | None`).
- 결과 객체는 pydantic `BaseModel` (FastAPI 자동 직렬화 + 검증).
- frontend는 React 19 + TypeScript + Tailwind v4. 컴포넌트는 `frontend/src/components/`, API 호출은 `frontend/src/api/voiceSoap.ts`에 모음.
