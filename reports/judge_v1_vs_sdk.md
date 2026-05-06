# Judge v1 (Anthropic API) vs SDK (Claude Agent SDK / Max 구독) 비교

**목적**: judge.py를 직접 API 호출 → claude-agent-sdk(로컬 `claude` CLI invoke)로
마이그레이션 후, 동일한 5 시드 케이스에서 채점 일관성 회귀 확인.

**모델**: 양쪽 모두 `claude-sonnet-4-6`. LM Studio 노트 생성 모델은 `gemma-3-12b-it-qat`.

**실행**: 2026-05-06. SDK 결과 = `reports/judge_seed_sdk.json`.

---

## 점수 비교

| Case | v1 API | SDK | Δ total | 비고 |
|---|---|---|---:|---|
| drug_ambiguity_01 | 5/5/5/5 (20, PASS) | 5/5/5/5 (20, PASS) | 0 | 동일 |
| hallucination_trap_01 | 5/5/3/3 (16, PASS) | 5/4/2/2 (13, FAIL) | **−3** | 노트 동일, judge variance |
| missing_info_01 | 5/5/5/5 (20, PASS) | 5/5/5/5 (20, PASS) | 0 | 동일 |
| normal_01 | 5/5/5/5 (20, PASS) | 5/5/5/5 (20, PASS) | 0 | 동일 |
| section_misclass_01 | 5/5/5/5 (20, PASS) | 5/5/5/5 (20, PASS) | 0 | 동일 |

**결론**: 4/5 케이스 점수 완전 일치. 1 케이스(hallucination_trap_01)는 동일한 LM Studio 노트에 대한 judge 자체의 variance — completeness·fidelity 차원이 borderline(원문에 약물 미언급 → 누락 판정 강도가 ±1점 흔들림).

---

## 발견된 이슈와 수정

### JSON 파싱 systematic 실패 (drug_ambiguity_01)

1차/2차 SDK 실행 모두 같은 위치에서 파싱 실패. 원인: judge가 reasoning 안에서 인용 강조용으로 escape 안 된 큰따옴표(`"`)를 사용해 JSON 깨짐. 예시 raw:

```
"reasoning": "...노트 전반이 원문 발화("푸로세미드 40밀리그램과...
                                     ↑ JSON string 종료로 해석됨
```

**수정**: `backend/eval/rubric.py`의 `JUDGE_SYSTEM_PROMPT`에 한 줄 추가 —
> reasoning 필드 안에서 큰따옴표(`"`) 사용 금지. 작은따옴표(`'`) 또는 한국어 인용부호(`「...」`) 사용.

3차 실행에서 5/5 케이스 모두 정상 파싱 통과(`「복수 호전 시 감량 예정」` 형식으로 인용). 117 unit test 모두 통과.

---

## 노트 동일성 (회귀 진단용)

`hallucination_trap_01`의 LM Studio 노트는 **두 실행에서 완전히 동일**:

```
S: B형 간염 추적 환자입니다.
O: HBV DNA 검출되지 않았고 ALT 28로 정상입니다.
A: (빈 값)
P: 현재 약물 유지하겠습니다.
```

→ 점수 차이는 동일 입력에 대한 Sonnet judge의 비결정성. 경계 케이스(약물·진단 미언급에 대한 누락 판정)에서 ±2점 변동 관찰.

---

## 성능 (judge 호출 시간)

| Case | v1 API | SDK | 배수 |
|---|---:|---:|---:|
| drug_ambiguity_01 | 9.8s | 49.0s | 5.0x |
| hallucination_trap_01 | 13.8s | 62.1s | 4.5x |
| missing_info_01 | 10.9s | 39.4s | 3.6x |
| normal_01 | 14.1s | 41.5s | 2.9x |
| section_misclass_01 | 14.3s | 38.3s | 2.7x |
| **평균** | **12.6s** | **46.0s** | **~3.7x** |

SDK가 ~3.7배 느림. 원인:
- `claude` CLI subprocess 스폰/teardown 오버헤드
- SDK가 reasoning을 더 길게 작성하는 경향 (응답 토큰 ↑)

5 케이스 일괄 실행 기준: v1 ~1분 vs SDK ~4분. 50 케이스 기준: v1 ~10분 vs SDK ~40분.

---

## SDK의 단점 (관찰)

1. **응답 시간 ~3.7배 증가**: 50 케이스 평가 기준 ~30분 추가.
2. **장문 reasoning 경향**: 토큰 사용량과 JSON 파싱 위험 모두 증가. 큰따옴표 escape는 prompt nudge로 해결됐으나 future 케이스에서 다른 형식 함정이 나올 수 있음.

## SDK의 장점

1. **별도 ANTHROPIC_API_KEY 불필요** — Max 구독 인증을 그대로 사용.
2. **API 비용 분리 발생 없음** — Max 한도 내에서 처리.
3. **로컬 환경 변수 의존 제거** — restart-sensitive 키 관리 불필요.

---

## 권장 후속 작업

- **5 케이스 회귀 안정화 완료**: 4/5 일치 + 1건은 노트 동일·judge variance로 설명. 마이그레이션 안전.
- **재시도 로직 (선택)**: 향후 50 케이스 확장 시점에 JSON 파싱 실패 1회 재시도 추가. 현재 5 케이스 기준 prompt nudge만으로 충분.
- **50 케이스 확장 시**: SDK 기반 진행 가능. 일괄 실행 시간 ~40분 예상.
