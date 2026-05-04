# LLM-as-Judge 평가 리포트

**총 5 케이스** (judge 성공 0, 실패 5)

## 케이스별 상세

### drug_ambiguity_01 (drug_ambiguity)

- **judge 단계**: `dry-run (judge skipped)` (노트는 아래에 표시)

**원문**:
> 복수 조절 위해 푸로세미드 40밀리그램과 스피로노락톤 100밀리그램 처방드립니다. 다음 외래에 체중 변화 확인하겠습니다.

**LLM 출력**:
- `subjective`: (빈 값)
- `objective`: (빈 값)
- `assessment`: (빈 값)
- `plan`: 푸로세미드 40밀리그램과 스피로노락톤 100밀리그램 처방, 다음 외래에 체중 변화 확인

### hallucination_trap_01 (hallucination_trap)

- **judge 단계**: `dry-run (judge skipped)` (노트는 아래에 표시)

**원문**:
> B형 간염 추적 환자입니다. 엔테카비르 0.5밀리그램 매일 복용 중입니다. HBV DNA 검출되지 않았고 ALT 28로 정상입니다. 현재 약물 유지하겠습니다.

**LLM 출력**:
- `subjective`: B형 간염 추적 환자입니다.
- `objective`: HBV DNA 검출되지 않았고 ALT 28로 정상입니다.
- `assessment`: (빈 값)
- `plan`: 현재 약물 유지하겠습니다.

### missing_info_01 (missing_info)

- **judge 단계**: `dry-run (judge skipped)` (노트는 아래에 표시)

**원문**:
> 추적 검사 결과입니다. AST 145, ALT 180, 총 빌리루빈 3.2, INR 1.5입니다. 약물 조정은 다음 외래에서 검토하겠습니다.

**LLM 출력**:
- `subjective`: (빈 값)
- `objective`: AST 145, ALT 180, 총 빌리루빈 3.2, INR 1.5입니다
- `assessment`: (빈 값)
- `plan`: 약물 조정은 다음 외래에서 검토하겠습니다

### normal_01 (normal)

- **judge 단계**: `dry-run (judge skipped)` (노트는 아래에 표시)

**원문**:
> 62세 남자 알코올성 간경변 추적 환자입니다. MELD 14, Child-Pugh B 7점입니다. 황달은 호전되고 있고 복부 팽만감도 줄었습니다. 푸로세미드 40밀리그램에서 20밀리그램으로 감량합니다.

**LLM 출력**:
- `subjective`: 62세 남자 알코올성 간경변 추적 환자입니다. 황달은 호전되고 있고 복부 팽만감도 줄었습니다.
- `objective`: MELD 14, Child-Pugh B 7점입니다.
- `assessment`: (빈 값)
- `plan`: 푸로세미드 40밀리그램에서 20밀리그램으로 감량합니다.

### section_misclass_01 (section_misclass)

- **judge 단계**: `dry-run (judge skipped)` (노트는 아래에 표시)

**원문**:
> 환자가 복부 팽만감을 호소합니다. AST 85, ALT 92 측정되었고 알부민이 3.1로 낮습니다. 복부 진찰에서 shifting dullness 양성입니다. 이뇨제 처방을 시작하겠습니다.

**LLM 출력**:
- `subjective`: 환자가 복부 팽만감을 호소합니다.
- `objective`: AST 85, ALT 92 측정되었고 알부민이 3.1로 낮습니다. 복부 진찰에서 shifting dullness 양성입니다.
- `assessment`: (빈 값)
- `plan`: 이뇨제 처방을 시작하겠습니다.
