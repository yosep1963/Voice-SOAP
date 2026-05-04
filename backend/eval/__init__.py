"""LLM-as-judge 평가 인프라 (도메인 모델만).

이 패키지에는 *외부 네트워크를 호출하지 않는* 순수 로직만 둠:
- cases.py: 합성 케이스 스키마/로더
- rubric.py: 4 차원 rubric + judge 프롬프트 빌더

실제 클라우드 judge 호출은 tools/eval/judge.py에 위치 — 구조 가드가
backend/ 안에서 외부 네트워크 호출을 막기 때문. 자세한 건 그 모듈 참조.

**보안 경계**:
- 케이스는 반드시 `is_synthetic=True`로 표기되어야 (cases.py에서 schema-level 강제)
  tools/eval/judge.py의 PHI guard를 통과 가능.
- CLAUDE.md "외부 네트워크 절대 금지" 정책은 환자 데이터에 대한 것 — 합성 dictation은 PHI 아님.
- 실데이터(logs/edits.jsonl 등)는 judge로 보낼 수 없음 (defense in depth).
"""
