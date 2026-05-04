# 합성 평가 케이스 작성 가이드

LLM-as-judge 평가용 합성 dictation 케이스 디렉터리. 각 yaml 파일이 1 케이스.

---

## 1. 왜 합성 케이스인가

실데이터(`logs/edits.jsonl`)는 **PHI**라 클라우드 judge로 보낼 수 없다 (`backend/eval/cases.py`의 `is_synthetic` schema-level guard). 합성 케이스는 임상 패턴을 모사하면서도 환자 식별 정보가 없어 dev-time 평가에만 사용 가능.

**복수 보호 장치**:
1. yaml schema에서 `is_synthetic: true` 강제 (false면 거부)
2. `tools/eval/judge.py`에서 호출 직전 재확인 (defense in depth)
3. `tests/structural/test_no_external_network.py`가 `backend/`에서 외부 호출 차단

---

## 2. 50개 분포 권장

5개 시드 + 45개 추가. **trap type별 다양성**이 단일 type 다수보다 중요.

| trap_type | 권장 수 | 목적 |
|---|---:|---|
| `drug_ambiguity` | 10 | 약물명 변환 환각 (loop diuretic, NA 계열 등) |
| `section_misclass` | 10 | S/O/A/P 섹션 분류 정확도 |
| `missing_info` | 10 | 진단·계획 미명시 시 추측 환각 (가장 위험) |
| `hallucination_trap` | 10 | 약물·수치·검사 결과의 미묘한 변형 유도 |
| `score_extraction` | 5 | MELD/Child-Pugh/ALBI/FIB-4 점수 정확 추출 |
| `normal` | 5 | calibration baseline. judge가 너무 엄격하지 않은지 확인용 |

새 trap_type 추가 시 `backend/eval/cases.py`의 `TrapType` Literal에 등록.

---

## 3. yaml 필드별 작성 가이드

### `id`

`<trap_type>_<2자리 번호>` 형식. 예: `drug_ambiguity_03`, `score_extraction_01`. 같은 type 내에서는 발견된 패턴 다양성을 우선.

### `format_id`

`soap`(재진) 또는 `initial_visit`(초진). 50개 중 ~80%는 `soap`(재진이 외래 dictation의 다수), ~20%는 `initial_visit`로 시작 권장.

### `source_text`

**한국어 외래 dictation, STT 후처리(`hints/postprocess.yaml`) 완료 후 텍스트라 가정.**

좋은 source의 특징:
- 50~150자 정도 (너무 짧으면 trap 약하고, 너무 길면 채점 모호)
- 실제 dictation 어순 ("환자 ~합니다", "처방드립니다" 등)
- 한 케이스에 trap 1~2개 집중 (여러 trap 혼합하면 채점 분리 어려움)
- 약물·수치·진단명을 의도적으로 명시하거나 의도적으로 생략

**피할 것**:
- 임상적으로 모호한 표현 ("X 의심" 같이 S/O/A 어디든 들어갈 수 있는 표현 — `section_misclass_01` 작성 중 발견된 함정. soap.yaml few-shot의 "간성뇌증 의심→A" 패턴과 충돌하면 trap이 ambiguity로 변질)
- 너무 critical한 수치 (예: AST 1500, INR 5.0) — LLM이 emergency 진단을 추측해 trap이 인위적이 됨
- 환자 이름·주민번호 등 PHI 모방 (마스킹 안 했어도 schema가 PHI guard로 차단하지만 애초에 작성 금지)

### `expected_behavior`

**judge가 채점 기준으로 직접 사용하는 텍스트**. 자연어로 적되 actionable해야 함.

체크리스트:
- [ ] **모든 섹션**(S/O/A/P 또는 7섹션)에 대해 어떻게 처리해야 하는지 명시
- [ ] "빈 값이 정답"인 섹션은 *왜* 빈 값인지 이유 (`missing_info_01` 참조)
- [ ] 양자택일 허용 시 명시 (예: *"빈 값 또는 'B형 간염' 둘 다 허용"*)
- [ ] 보존해야 할 약물명·용량·수치를 구체적으로

피할 것:
- "잘 분류해야 함" 같은 모호한 표현
- expected에 본인이 원문에 없는 의학 정보를 추가 (judge가 자기 의학지식으로 추론하면 안 되는 것과 같은 원칙)

### `known_pitfalls`

**이 케이스에서 LLM이 빠질 수 있는 구체적 실패 모드**. 3~5개 권장.

좋은 pitfall:
- *"엔테카비르 → 테노포비르 / 비리어드로 변환"* (구체적 약물명 + 변환 방향)
- *"Assessment에 '급성 간염' 등 추측 진단 추가"* (구체적 환각 예시)
- *"감량 흐름(40 → 20)을 단순히 '20mg 처방'으로 단축"* (구체적 정보 손실)

피할 것:
- *"환각 가능"* 같은 추상적 진술
- pitfall끼리 중복

### `is_synthetic`

**반드시 `true`**. 값이 누락되거나 false면 schema에서 거부.

### `review_status`

- `pending` (작성 직후 기본) — `--include-pending` 플래그 없으면 평가 제외
- `approved` (의학 검수 완료) — 기본 평가에 포함
- `rejected` (불량 케이스로 판정, 보존만) — 항상 제외

### `notes`

작성/검토 메모. 의학적 검수 시 확인할 점을 적어두면 미래 본인이 다시 봤을 때 유용.

---

## 4. yaml 작성 시 주의 (실수 패턴)

5개 시드 작성하며 부딪힌 함정:

### 4.1 리스트 아이템에 콜론 포함 시
```yaml
known_pitfalls:
  - 약물 추측 환각 (예: 우르소데옥시콜산 추가)   # ❌ "예:"가 mapping으로 파싱됨
```
→ 단일 따옴표로 감싸거나 콜론을 다른 기호로:
```yaml
  - '약물 추측 환각 (예: 우르소데옥시콜산 추가)'    # ✓
  - 약물 추측 환각 (예 — 우르소데옥시콜산 추가)     # ✓
```

### 4.2 리스트 아이템이 `"`로 시작 시
```yaml
known_pitfalls:
  - "복수 의심"을 Assessment에 옮김             # ❌ 닫는 따옴표 뒤 글자가 unexpected
```
→ 전체를 단일 따옴표로:
```yaml
  - '"복수 의심"을 Assessment에 옮김'           # ✓
```

### 4.3 한 번에 검증
```bash
uv run python -c "from pathlib import Path; from backend.eval.cases import load_cases; \
  print(load_cases(Path('tests/fixtures/eval_cases'), include_pending=True))"
```
또는:
```bash
uv run pytest tests/test_eval_cases.py tests/test_eval_runner.py
```

---

## 5. 작성 워크플로우 (50개 확장 시)

50개로 늘릴 때 **blind grading**을 지키면 inter-rater 신뢰도가 의미 있어집니다.

```
1. 새 케이스 yaml 작성 (review_status: pending)
2. 의학적 자기 검수 → approved로 변경
3. dry-run으로 LM Studio 노트 생성 미리 확인:
     uv run python -m tools.eval.run_judge --dry-run --out reports/dryrun.md
4. 본인이 노트만 보고 4 차원 점수 매김 (judge 점수 모르는 상태):
     reports/human_grades_blind.jsonl 작성
5. judge 호출:
     uv run python -m tools.eval.run_judge --out reports/judge_run.md
6. inter-rater:
     uv run python -m tools.eval.inter_rater \
       reports/judge_run.json reports/human_grades_blind.jsonl --out reports/ir.md
```

`reports/ir.md`의 경고 게이트:
- 차원별 mean |diff| ≥ 1.5 → judge가 일관되게 다르게 채점
- Pearson r < 0.3 (n≥5) → 상관 부족

게이트 통과해야 50개 평가 결과를 신뢰할 수 있음. 통과 못하면 `backend/eval/rubric.py`의 judge 프롬프트 재설계.

---

## 6. 체크리스트 (새 케이스 작성 시)

- [ ] `id`가 `<trap_type>_<번호>` 형식인가
- [ ] `source_text`가 50~150자, STT 후처리 완료된 한국어 dictation 형태인가
- [ ] `expected_behavior`가 모든 섹션에 대한 처리를 명시하는가
- [ ] `expected_behavior`가 `hints/formats/<format_id>.yaml`의 섹션 정의 + few_shots와 일관되는가 (모순되면 ambiguity → trap 약화)
- [ ] `known_pitfalls`가 구체적 실패 모드 3~5개인가
- [ ] `is_synthetic: true` 명시
- [ ] yaml 콜론·따옴표 함정 회피 (4번 항목)
- [ ] `uv run pytest tests/test_eval_cases.py` 통과
- [ ] 의학적 검수 완료 후 `review_status: approved`

---

## 7. 정책 결정 이력 (참고)

### `hallucination_trap_01`의 누락 동작 (2026-05-04)

LLM이 환각 회피를 위해 약물 정보 자체를 누락하는 패턴 발견 (`reports/judge_seed.json`).

**(B) 정책 시도 결과** (`reports/judge_seed_v2.json`): strict_rules에 *"약물·수치는 어느 섹션이든 반드시 포함"* 룰 추가 → `drug_ambiguity_01`의 추적 정보 누락(comp 5→4) + `hallucination_trap_01`의 섹션 분류 무너짐(sec 5→3, HBV DNA 누락) **부작용 발생**.

**(A) 정책 유지로 롤백**: 환각 < 누락이라는 판단. 외래에서 약물 누락 케이스는 사용자가 textarea로 보강한다는 워크플로우 가정.

같은 패턴을 새 케이스에서 다시 만나면 이 결정을 참고하거나 재검토 trigger로 활용.
