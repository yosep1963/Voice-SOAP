# Voice → SOAP 노트 시스템 개발 계획 (최종)

> **프로젝트**: 한국어 음성 → 간장학 의무기록 자동 구조화 (재진 SOAP / 초진 CC-PI-PHx-FHx-PE-Imp-Plan 다중 포맷)
> **개발자**: 이창형 (대구가톨릭대 소화기내과)
> **작성일**: 2026-04-28 / 최종 수정: 2026-04-30
> **상태**: Phase 1·2 완료, Phase 3 포맷 시스템 인프라 완료 → 외래 실사용 + 임상 케이스별 템플릿 추가 단계

---

## 1. 프로젝트 목표

외래 진료 시 음성 dictation을 **로컬에서** SOAP 형식으로 자동 구조화. EMR에 붙여넣기 가능한 형태로 출력. 환자당 처리 시간 1분 이하 목표.

**비목표**: EMR 직접 연동(법적 이슈), 클라우드 전송, 환자 식별 정보 처리.

---

## 2. PoC 검증 완료 (2026-04-28 ~ 04-29)

### STT 검증 (Whisper)

| 항목 | 결과 |
|---|---|
| Whisper large-v3 + 의학 힌트 정확도 | ~85% (간장학 용어) |
| RTF (캐시 후) | 0.10~0.17x (60s 오디오 → 6~10초) |
| 힌트 효과 | 의학용어 ~50% → ~85% (큰 개선) |
| 마이크 워크플로우 | USB 헤드셋 정상 |

**힌트가 못 잡는 패턴**: 외래어 변형(푸로세미드↔퓨로스마이드), 발음 모호(증량↔정량), 일반 용어(간염, 과거력). → 후처리 사전(`hints/postprocess.yaml`)으로 보완 완료.

### LLM 검증 (Gemma 3 12B QAT MLX)

| 항목 | 결과 |
|---|---|
| 메모리 사용 (모델 로드 시) | 77.7% / 24GB ✅ |
| 압축 메모리 | 8.4 GB (안전) |
| API 응답 시간 (32 tokens) | 6초 |
| API 응답 시간 (94 tokens) | 8초 |
| /process end-to-end (60s wav) | ~42초 (STT 14s + LLM 26s) |
| SOAP 분류 정확도 (단일 케이스) | S/O/P 정확, A는 명시 없으면 비움 (안전) |
| 환각 발생 | 없음 (보수적 응답) |

**결론**: Whisper large-v3 + Gemma 3 12B QAT MLX 조합으로 본 개발 진행 가능.

### 외래 부하 시뮬레이션 (2026-04-29)

연속 5명 환자 dictation을 모사한 부하 테스트. 초기 단일 호출 시 메모리 90%+로 치솟던 문제를 **LM Studio 설정 변경**으로 해결.

**적용 설정**:
- Context Length: 4096 → **3072** (KV cache 25% 감소)
- **Auto-Evict ON** (idle 시 자동 unload, 새 요청 시 재로드)
- Idle TTL: **15분** (외래 정상 운영 중엔 유지, 끊긴 시간엔 unload)

**메모리 추이**:

| 시점 | 메모리 점유 | 평가 |
|---|---|---|
| 시작 전 (모델 로드 후) | 80% | 약간 높음 |
| 5명 처리 중 | 81% | ✅ +1%만 증가 (KV cache stateless 확인) |
| 종료 직후 | 81% | ✅ 안정적 |
| 5분 후 | 83.4% | 캐시 누적 — Auto-Evict 동작 영역 |

**응답 시간**:

| 환자 | LLM 응답 시간 |
|---|---|
| 1번 (콜드 시작) | 9초 |
| 2번 | 8초 |
| 3번 | 7초 |
| 4번 | 6초 |
| 5번 | 7초 |
| **평균 (warm)** | **7.4초** |

→ 환자당 60초 dictation + STT 14초 + LLM 7~8초 = **약 80초 안에 SOAP 완성** (목표 1분에 근접).

**SOAP 품질**:
- ✅ S/O/P 분류 정확
- ✅ 환각 0% (원문에 없는 검사결과/약물 추가 없음)
- ✅ 약물 용량/점수/수치 정확 보존
- ⚠️ A(Assessment)는 입력에 명시적 진단이 없으면 빈 값 — **의도된 보수적 동작** (사용자가 textarea에서 직접 입력)

**판정**: 본 개발 KPI 모두 충족. 외래 워크플로우 자신있게 시작 가능.

| KPI | 목표 | 시뮬레이션 결과 |
|---|---|---|
| 메모리 안정성 | 85% 이하 | ✅ 81~83% |
| 5명 연속 처리 | OOM 없음 | ✅ 통과 |
| LLM 응답 시간 | 15초 이내 | ✅ 평균 7.4초 |
| SOAP 정확도 | 80%+ | ✅ S/O/P 정확 |
| 환각률 | 5% 미만 | ✅ 0% |

---

## 3. 시스템 아키텍처

```
┌─────────────────────────────────────────────────┐
│  사용자 (외래 진료실)                              │
│  └─ 단축키 / 메뉴바 클릭으로 녹음 시작/종료        │
└─────────────────┬───────────────────────────────┘
                  │
         ┌────────▼─────────┐
         │  메뉴바 클라이언트  │  (Phase 4)
         │  - 녹음 컨트롤      │
         │  - 결과 뷰어/편집   │
         │  - 클립보드 복사    │
         └────────┬─────────┘
                  │ HTTP (localhost only)
         ┌────────▼─────────┐
         │  FastAPI 백엔드    │  (Mac Mini M4, LaunchAgent)
         ├──────────────────┤
         │ 1. STT 파이프라인   │
         │    Whisper-large-v3 │
         │    + 의학 힌트       │
         │    + 후처리 사전     │
         ├──────────────────┤
         │ 2. SOAP 구조화      │
         │    Gemma 3 12B      │
         │    QAT MLX 4bit     │
         ├──────────────────┤
         │ 3. 템플릿 분기       │
         │    HCC f/u, LC f/u, │
         │    HE 평가 등        │
         ├──────────────────┤
         │ 4. 점수 자동 추출    │
         │    MELD, Child-Pugh │
         │    ALBI, FIB-4       │
         └────────┬─────────┘
                  │
         ┌────────▼─────────┐
         │  SQLite (로컬)     │
         │  - 세션 메타데이터  │
         │  - 사전 엔트리      │
         │  - 24h 자동 삭제    │
         └──────────────────┘
```

**핵심 원칙: 100% 로컬, 외부 네트워크 차단.**

---

## 4. 기술 스택 (검증 완료)

### 백엔드 (Mac Mini M4, 24GB)

| 컴포넌트 | 결정 |
|---|---|
| 언어 | Python 3.11 (pyenv) |
| 프레임워크 | FastAPI + Uvicorn |
| STT | mlx-whisper (`mlx-community/whisper-large-v3-mlx`) |
| **LLM** | **Gemma 3 12B Instruct QAT (MLX 4bit)** |
| LLM 식별자 | `gemma-3-12b-it-qat` |
| LLM 엔드포인트 | `http://127.0.0.1:1234/v1` (LM Studio) |
| 임베딩 | `text-embedding-nomic-embed-text-v1.5` (Phase 5용) |
| DB | SQLite (sqlmodel) |
| 프로세스 | LaunchAgent |

**LLM 결정 근거**:
- mlx-community/gemma-3-12b-it-qat-4bit (다운로드 검증 완료)
- QAT 양자화: 4bit인데 bf16 수준 품질 유지
- MLX 네이티브: Apple Silicon 최적화 (GGUF 대비 2-3배 빠름)
- 메모리 7-8GB: 24GB 안에서 안전 (실측 77.7%)
- SOAP 분류 작업에 충분한 능력 검증됨

**폴백 전략 (Phase 1 벤치마크 결과에 따라)**:
- 1차: Qwen 2.5 14B (~8GB, 한국어 우수)
- 2차: Qwen 3 14B (~8GB, 최신 추론)
- 3차: Gemma 3 27B (~16GB, 메모리 빡빡)

### 메모리 예산 (실측 기반)

```
24GB 통합 메모리
├─ macOS + 시스템: 4-5GB
├─ 개발 도구 + 브라우저: 2-3GB
├─ Whisper large-v3: ~3GB (활성 시)
├─ Gemma 3 12B QAT: 7-8GB ✅
├─ FastAPI + 기타: ~1.5GB
└─ 가용 여유분: 4-5GB

현재 측정: 77.7% (안전 영역)
```

**중장기 메모리 원칙**:
- 한 번에 한 LLM만 (Voice SOAP 또는 Hermes 등)
- 4bit QAT 양자화 기본
- Context 2K-4K 유지
- 외장 NVMe SSD는 모델 저장용 (실행은 내장)

### 프론트엔드 진화 경로
- **Phase 2**: 웹 UI (React + Vite + Tailwind, localhost:8080)
- **Phase 4**: SwiftUI 메뉴바 앱 또는 Tauri (네이티브 통합)

### 시스템
- 단축키: Hammerspoon (macOS 글로벌 단축키)
- 장기 보관 저장소: 없음 (의도적 — 의료법/PIPA 위험 회피)

---

## 5. Phase별 개발 계획

### Phase 1: 백엔드 코어 (1-2주) — ✅ 완료 (2026-04-30 시점)
**목표**: HTTP API로 음성 → 의무기록 변환 가능

- [x] FastAPI 프로젝트 구조 셋업 (pyproject.toml, uv)
- [x] `POST /transcribe` — 음성 파일 → 텍스트 (의학 힌트 적용)
- [x] `POST /note` — 텍스트 → 임의 포맷 의무기록 (Gemma 3 12B 호출). *기존 `/soap`은 Day 3에 삭제, `/note?format_id=soap`로 동일 동작.*
- [x] `POST /process` — 통합 엔드포인트 (SOAP 4섹션 응답, 백엔드 디버그용)
- [x] `GET /formats` — 사용 가능 포맷 목록 + 섹션 메타데이터
- [x] 후처리 사전 시스템 (`hints/postprocess.yaml`) — 28개 룰 누적
- [x] **프롬프트 엔지니어링** — SOAP·initial_visit 모두 5개 few-shot
- [ ] **LLM 벤치마크**: 30개 케이스로 환각률 / 정확도 / 속도 측정 (외래 실사용 데이터로 대체 진행 중)
- [ ] LaunchAgent 등록 스크립트
- [x] OpenAPI docs (Swagger UI, FastAPI 자동 생성)

**산출물**: `curl`로 wav → 의무기록 JSON 변환 가능한 백엔드 + LLM 적합성 보고서

### Phase 2: 웹 UI (1주) — ✅ 완료
**목표**: 브라우저에서 실제 외래 워크플로우 검증

- [x] React 19 + Vite + Tailwind v4
- [x] 녹음 컴포넌트 (MediaRecorder API)
- [x] **포맷 라디오** (재진 SOAP / 초진) — Day 3에 추가
- [x] 동적 섹션 편집기 (`NotePanel.tsx`, sections dict 기반) — 4섹션·7섹션 모두 같은 UI
- [x] 클립보드 복사 (각 섹션 / 전체) + Safari fallback (`execCommand('copy')`)
- [x] 처리 시간 / 신뢰도 표시
- [x] 2단계 UX (STT 결과 먼저 → SOAP 추가)

**산출물**: `localhost:5173`에서 사용 가능한 외래 보조 도구

### Phase 3: 포맷 시스템 (1-2주) — ⏳ 인프라 완료, 케이스별 템플릿 추가 단계
**목표**: 진료 유형별 의무기록 자동 분기 (포맷 선택 + few-shot 기반 LLM 가이드)

**완료 (Day 1~3, 2026-04-30):**
- [x] 포맷 정의 yaml 외부화 (`hints/formats/*.yaml`) — sections·strict_rules·few_shots 구조
- [x] LLM 프롬프트 동적 생성 (`build_system_prompt(fmt)`)
- [x] **포맷 1**: `soap.yaml` — 재진 외래 (S/O/A/P, 4섹션, 5 few-shot)
- [x] **포맷 2**: `initial_visit.yaml` — 초진 외래 (CC/PI/Past Hx/Family Hx/PE/Imp/Plan, 7섹션, 5 few-shot. 음주력 PI+Past Hx 양쪽 기재 원칙)
- [x] 프론트엔드 라디오 선택 + 동적 섹션 렌더
- [x] feedback 로그에 `format_id` 필드 추가 (포맷별 분석 가능)

**남은 작업:**
- [ ] 케이스별 sub-template 추가 (필요 시 yaml 추가만으로 노출):
  - HCC f/u (BCLC, AFP, CT 변화)
  - LC f/u (MELD, Child-Pugh, 정맥류, 복수)
  - HE 평가 (West Haven grade, 유발 인자)
  - 알코올성 간염 (Maddrey, Lille)
- [ ] 자동 점수 추출 (정규식 + LLM 검증)
- [ ] 템플릿 자동 추천 (음성 키워드 기반)

**산출물**: 진료 유형 선택 → 적절한 의무기록 골격 자동 생성

### Phase 4: 네이티브 클라이언트 (2-3주)
**목표**: 메뉴바 앱화로 외래 통합

- [ ] SwiftUI 메뉴바 앱 OR Tauri 앱 선택
- [ ] 시스템 단축키 (예: ⌥⌘R 녹음 시작/종료)
- [ ] 진행 중 비주얼 인디케이터
- [ ] 결과 popover 창
- [ ] 클립보드 자동 복사 옵션

**산출물**: 진료 흐름을 깨지 않는 백그라운드 도구

### Phase 5: 학습/개선 시스템 (지속)
**목표**: 사용할수록 정확도 향상

- [ ] 사용자 편집 diff 로깅 (이름/식별자 자동 마스킹 후)
- [ ] 빈번한 오인식 자동 발견 → 후처리 사전 후보 제안
- [ ] 힌트 사전 버저닝 (Git 관리)
- [ ] **임베딩 기반 RAG** (nomic-embed 활용) — 비슷한 과거 케이스 참조
- [ ] 월간 리포트: 가장 많이 수정된 용어 Top 10

**산출물**: 자가 개선되는 시스템

---

## 6. 핵심 디자인 결정

### 코드 규칙 (TodoList 프로젝트와 동일)
- 파일당 최대 150줄
- 도메인 기반 분리 (`stt/`, `soap/`, `templates/`, `dict/`)
- 명시적 타입 힌트 (Python: typing, mypy strict)

### 검증된 SOAP 프롬프트 (PoC 결과 기반)

```python
SYSTEM_PROMPT = """당신은 간장학 외래 진료 dictation을 SOAP 형식으로 분류하는 도구입니다.

각 섹션 정의:
- subjective: 환자의 호소, 증상, 병력 (주관적 정보)
- objective: 신체검진, 검사 결과, 영상 소견, 점수 (객관적 측정값)
- assessment: 진단명, 평가 (의사가 명시한 판단만)
- plan: 치료 계획, 처방, 추적 관찰
- uncertain_segments: 원문 중 모호한 표현 ([?] 표시 대상)

규칙:
1. 원문에 없는 정보는 절대 추가하지 마세요
2. 각 문장을 적절한 섹션에 분류하세요
3. JSON만 출력 (마크다운 코드블록 없이)
4. **명시되지 않은 섹션은 빈 문자열로 두세요** (추측 금지)

출력 형식:
{"subjective":"","objective":"","assessment":"","plan":"","uncertain_segments":[]}
"""
```

**파라미터**: `temperature=0.1`, `max_tokens=500`

**검증 결과 예시** (recording.wav, 12B QAT):
```
입력: "60세 남자 환자 B형 간염으로 인한 간경변 추적 중입니다. MELD 18점,
       Child-Pugh B 7점입니다. 복부 초음파에서 5cm 간세포암이 우엽에 발견되었습니다.
       아테졸리주맙 베바시주맙 병용요법 시작 예정입니다."

출력: {
  "subjective": "60세 남자 환자 B형 간염으로 인한 간경변 추적 중",
  "objective": "MELD 18점, Child-Pugh B 7점. 복부 초음파에서 5cm 간세포암이 우엽에 발견",
  "assessment": "",  ← 명시적 진단 없으면 비움 (보수적, 안전)
  "plan": "아테졸리주맙 베바시주맙 병용요법 시작 예정",
  "uncertain_segments": []
}
```

⚠️ **마크다운 코드블록 처리**: Gemma는 종종 ` ```json ... ``` ` 으로 감쌉니다. 백엔드에서 strip 처리 필요 — 현재 `backend/soap/llm_client.py:_extract_json()`에 구현됨.

### LLM-Agnostic 인터페이스

폴백 전략(Qwen 2.5/3 등)을 위해 LLM 클라이언트 추상화 (현재 `structure_to_soap()` 함수 시그니처가 이미 모델 인자를 받음):

```python
# backend/soap/llm_client.py
async def structure_to_soap(
    transcript: str,
    *,
    base_url: str,
    model: str,             # gemma-3-12b-it-qat 또는 qwen2.5-14b 등
    timeout_seconds: float,
    temperature: float,
) -> tuple[SoapNote, float]:
    # OpenAI 호환 API 호출
    ...
```

→ 모델 변경 시 환경변수 `VOICE_SOAP_LLM_MODEL`만 수정.

### 후처리 사전 형식
```yaml
# hints/postprocess.yaml
- pattern: "퓨로스마이드"
  replace: "푸로세미드"
  category: drug

- pattern: "스페르농턴|스피르농턴"
  replace: "스피로노락톤"
  category: drug

- pattern: "복부\\s?천파"
  replace: "복부 초음파"
  category: imaging
```

### 점수 자동 계산
음성에서 검사 수치가 나오면 자동으로 MELD/Child-Pugh/ALBI 계산. **PoC 단계에서 만든 기존 계산기 재사용**:
- FIB-4/APRI calculator
- CLIF-C OF/ACLF/MELD calculator
- BCLC calculator

→ Phase 3에서 라이브러리화해서 import.

---

## 7. 보안 / 규제 요구사항 (의료법 / PIPA)

### 절대 원칙
1. **외부 네트워크 호출 금지** (방화벽 / Little Snitch 권장)
2. **환자 식별자 자동 마스킹** (이름, 등록번호, 주민번호 자리)
3. **자동 삭제 정책**: 모든 음성/텍스트 24시간 후 삭제
4. **로그에 환자 데이터 미포함** (오류 로그도 체크)
5. **백업 비활성화**: Time Machine 제외 폴더로 설정

### 식별자 마스킹 규칙
```python
PATTERNS = [
    (r'\b\d{6}-\d{7}\b', '[주민번호]'),
    (r'\b\d{8,10}\b', '[등록번호]'),
    # 환자 이름은 LLM 후처리에서 [환자]로 치환
]
```

### 사용자 동의
환자에게 사용 사실 고지 + 의무기록 작성 보조 도구임을 설명. 데이터 미저장 명시.

---

## 8. 디렉토리 구조

```
voice_soap/
├── plan.md                    # 이 문서
├── README.md
├── pyproject.toml             # uv 사용
├── .env.example
│
├── backend/
│   ├── main.py                # FastAPI 진입점
│   ├── api/
│   │   ├── transcribe.py
│   │   ├── soap.py
│   │   └── process.py
│   ├── stt/
│   │   ├── whisper_engine.py
│   │   ├── postprocess.py
│   │   └── hints_loader.py
│   ├── soap/
│   │   ├── llm_client.py      # OpenAI 호환 추상화
│   │   ├── prompts.py         # 검증된 프롬프트 + few-shot
│   │   └── validator.py       # 환각 검증 (diff)
│   ├── templates/
│   │   ├── base.py
│   │   ├── hcc_followup.yaml
│   │   ├── lc_followup.yaml
│   │   └── he_assessment.yaml
│   ├── scores/
│   │   ├── meld.py
│   │   ├── child_pugh.py
│   │   └── albi.py
│   ├── privacy/
│   │   ├── masking.py
│   │   └── auto_cleanup.py
│   └── db/
│       └── models.py          # SQLModel
│
├── frontend/                   # Phase 2 이후
│   ├── package.json
│   └── src/
│
├── hints/
│   ├── medical_hints.txt      # PoC에서 작성한 것 마이그레이션
│   └── postprocess.yaml
│
├── scripts/
│   ├── install.sh
│   ├── launchagent_install.sh
│   └── cleanup_cron.sh
│
└── tests/
    ├── test_stt.py
    ├── test_soap.py
    └── fixtures/              # 합성 음성 (실제 환자 데이터 X)
```

---

## 9. 위험 요소 및 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| LLM 환각 (없는 검사결과 추가) | 의료적 위해 | 원문 diff 검증, 의심 부분 [?] 표시, **사용자 확인 강제** |
| 프라이버시 유출 | 법적 책임 | 외부 통신 차단, 자동 삭제, 코드 감사 |
| Whisper 의학용어 오인식 | 정확도 저하 | 힌트 + 후처리 사전 + 사용자 편집 학습 |
| Gemma 3 12B 의학 도메인 한계 | SOAP 품질 저하 | Phase 1 벤치마크 후 Qwen 2.5 14B로 폴백 |
| 메모리 부족 | 시스템 불안정 | 12B로 다운그레이드 완료 / 한 번에 한 LLM만 |
| 마크다운 코드블록 출력 | JSON 파싱 실패 | `_extract_json()`로 자동 strip |
| LLM 응답 지연 (8~30초) | 워크플로우 마찰 | 스트리밍 응답 + 백그라운드 처리 |
| 외래 시간 압박 | 도구 사용 포기 | 단축키 워크플로우 최적화, 1-클릭 복사 |
| 시스템 크래시 | 데이터 유실 | 로컬 임시 저장 + 복구, 자동 재시작 |
| 의료법 위반 가능성 | 규제 리스크 | "보조 도구" 명시, 의무기록은 사용자 책임 강조 |

---

## 10. 성공 기준 (KPI)

### Phase 1-2 (PoC → MVP)
- [ ] 의학용어 인식 정확도 90%+ (간장학 용어 50개 표준 셋)
- [ ] 60초 음성 처리 시간 30초 이내 (Whisper 6초 + LLM 10-15초 + 기타) — 현재 ~42초, 개선 여지
- [ ] LLM 환각률 5% 미만 (수기 검증 30건)
- [ ] SOAP 분류 정확도 80%+ (각 섹션 적절히 배치)
- [ ] 메모리 사용 80% 이하 유지 — 현재 77.7% ✅

### Phase 3-4 (실용화)
- [ ] 외래 1세션(60초) 전체 처리 1분 이내
- [ ] 사용자 편집률 20% 이하 (자동 결과 80% 채택)
- [ ] 한 달 연속 사용 가능한 안정성

### Phase 5 (장기)
- [ ] 학회 발표 / 논문화 (KoSAIM 또는 임상 정보학 저널)
- [ ] 후속 프로젝트로 확장 (다른 진료과 / 다국어)

---

## 11. 변경 이력

### 2026-04-30 — 다중 포맷 시스템 도입 (Day 1~3)
**배경**: 재진 외래 SOAP 외에 초진 외래는 CC/PI/Past Hx/Family Hx/PE/Imp/Plan 7섹션으로 dictation 구조가 다르다. 기존 4섹션 고정 구조로는 초진을 표현 불가 → 포맷을 데이터(yaml)로 외부화.

**Day 1 (백엔드 인프라, byte-equivalent SOAP)**
- `hints/formats/*.yaml`로 포맷 정의 외부화 (sections + strict_rules + few_shots)
- `backend/soap/formats.py` — `FormatDefinition` pydantic + lru_cache 로더
- `backend/soap/prompts.py` — 정적 SYSTEM_PROMPT 삭제, `build_system_prompt(fmt)` 동적 빌드
- 골든 회귀: `tests/fixtures/soap_system_prompt_golden.txt`와 byte-for-byte 일치 검증

**Day 2 (포맷 일반화 + 초진 yaml)**
- `ClinicalNote` (sections dict) 모델 도입 — 임의 섹션 수 지원
- `POST /note` 신규 — `format_id` 인자 받아 포맷별 LLM 호출 + 응답
- `hints/formats/initial_visit.yaml` — 7섹션 + 5 few-shot
- 임상 원칙 합의: 음주력은 PI·Past Hx 양쪽 기재 / Imp·Family Hx는 Q&A 없으면 default 빈칸

**Day 3 (프론트엔드 통합 + /soap 정리)**
- `FormatSelector.tsx` 라디오 + `NotePanel.tsx` 동적 섹션 렌더 (구 `SoapPanel` 대체)
- `GET /formats` 엔드포인트 — 자동 yaml 디스커버리, 프론트가 라디오 옵션 채움
- `EditFeedback`에 `format_id` 필드 추가 — `logs/edits.jsonl` 분석 시 포맷별 그루핑 가능
- `POST /soap` 엔드포인트 + 관련 테스트 삭제 (`/note?format_id=soap`로 동일)
- 테스트: 백엔드 54개 통과, 프론트 typecheck 통과

**관련 결정**
- 포맷 추가 = yaml 1개 추가 (코드 수정 없음). 향후 Phase 3 sub-template은 모두 이 경로.
- `SoapNote` 4섹션 모델은 `/process` 엔드포인트(백엔드 디버그용) 후방호환 위해 유지.
- few-shot 5개는 hepatology 일반 지식 기반 초안 — 외래 실사용 후 임상 검증·교체 예정.

### 2026-04-30 — STT 후처리 사전 누적 (외래 dictation 회귀)
- 알코올성 간경변 / Child-Pugh / TACE / 간초음파 / Liver dynamic CT 등 흔한 오인식 8+6=14개 변형을 `hints/postprocess.yaml`에 추가 (28 룰).
- `hints/medical_hints.txt` 끝에 "자주 헷갈리는 표현" 섹션 추가 — Whisper의 last 224 tokens 효과 영역에 phrase 단위로 정확 표기 주입. 이후 dictation에서 오인식 발생률 급감 (사용자 확인).

### 2026-04-30 — 프론트엔드 클립보드 silent failure 수정
- `navigator.clipboard.writeText` 실패 시 silent → `execCommand('copy')` fallback + 사용자 에러 표시.

---

## 12. Claude Code에게 시작 명령

```
이 plan.md를 읽고 Phase 1 마무리 + Phase 2 진입을 진행해주세요.

검증 완료된 환경:
- Mac Mini M4, 24GB
- LM Studio 실행 중 (http://127.0.0.1:1234)
- 모델: gemma-3-12b-it-qat (MLX 4bit, 7GB)
- Whisper large-v3 캐시 완료
- 메모리 사용 77.7% (안전 영역)

Phase 1 잔여 작업:
- 프롬프트 few-shot 예시 5-10개 추가 (recording.wav 결과 기반)
- 30개 케이스 벤치마크 자동화
- LaunchAgent 등록 스크립트

Phase 2 (웹 UI):
- React + Vite + Tailwind (TodoList 프로젝트와 동일 스택)
- 녹음 컴포넌트 + S/O/A/P 편집기 + 클립보드 복사

이미 결정된 사항:
- LLM은 Gemma 3 12B QAT MLX로 확정 (변경 없음)
- Whisper는 large-v3 유지 (회귀 검증 완료)
- SOAP 응답 키는 전체 단어 + uncertain_segments 유지
- LaunchAgent는 Phase 1+2 모두 완료 후 등록
- 프론트엔드는 Phase 2에서 React+Vite로 (TodoList와 통일)

진행 중 막히는 부분이나 결정 필요한 게 있으면 질문해주세요.
```

---

## 부록 A: PoC에서 가져올 자산 (이미 마이그레이션됨)

1. **`hints/medical_hints.txt`** — 카테고리별로 정리된 의학 힌트 사전 (계속 확장)
2. **`hints/postprocess.yaml`** — 후처리 사전 (15개 룰, recording.wav 분석 기반)
3. **`whisper_test.py`** (루트 보존) — PoC 회귀 검증 기준선
4. **`tests/fixtures/recording.wav`** — 첫 통합 테스트 fixture

---

## 부록 B: 인프라 환경 (검증 완료)

- **HW**: Mac Mini M4, 24GB 통합 메모리, 256GB 내장 SSD
- **계획**: 외장 2TB Thunderbolt 4 NVMe SSD (모델 저장용)
- **OS**: macOS Tahoe 26
- **Python**: 3.11 (pyenv 관리)
- **LM Studio**: 설치 완료, http://127.0.0.1:1234 실행 중
- **로드된 모델**:
  - `gemma-3-12b-it-qat` (MLX 4bit, ~8GB)
  - `text-embedding-nomic-embed-text-v1.5` (Phase 5 RAG용)
- **Whisper**: mlx-whisper 0.4.3 (`mlx-community/whisper-large-v3-mlx` 캐시 완료)
- **삭제됨**: OpenClaw (메모리 확보 위해)
- **추후 검토**: Hermes (Voice SOAP과 동시 미운영, 시간대 분리)

---

## 변경 이력

- 2026-04-28: 초안 작성 (PoC 완료 후)
- 2026-04-29: 메모리 88% 점유로 Gemma 4 26B → 12B 변경 시도
- 2026-04-29: Gemma 4에 12B 없음 확인 → **Gemma 3 12B QAT MLX로 최종 확정**
- 2026-04-29: SOAP 프롬프트 검증 완료, 본 개발 GO
- 2026-04-29: Whisper는 large-v3 유지(회귀 검증 완료), SOAP 키는 전체 단어 + uncertain_segments 유지로 본 개발 적용
- 2026-04-29: Phase 2 웹 UI MVP 완료 (Vite + React + Tailwind), 2단계 UX(STT 즉시 → SOAP 추가), 편집 가능 textarea + 섹션별 복사
- 2026-04-29: Whisper 반복 환각 방지 옵션 추가 (`condition_on_previous_text=False`, `compression_ratio_threshold=2.0`)
- 2026-04-29: 후처리 사전 16룰로 확장 (우엽/좌엽 변형, 빌리루빈 변형 추가)
- 2026-04-29: Phase 5 학습 시스템 시작 — `POST /feedback` + 마스킹(주민/등록번호) + JSONL 저장(`logs/edits.jsonl`). 사용자가 "전체 복사" 누르는 시점에 자동 로깅
- 2026-04-29: **외래 5명 연속 부하 시뮬레이션 통과** — Context 3072 + Auto-Evict ON + Idle TTL 15분 적용 후 메모리 81~83% 안정, OOM 없음, 응답 평균 7.4s (워밍 후), 환각 0%, S/O/P 분류 정확. 본 개발 자신감 확보.
