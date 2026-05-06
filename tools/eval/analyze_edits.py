"""편집 로그(`logs/edits.jsonl`) 분석 — STT 오류·LLM 보강 후보 도출.

**왜 backend/가 아니라 tools/에 있나**: backend/는 환자 데이터를 다루는 런타임이라
구조 가드가 외부 네트워크를 차단함. 이 도구는 dev-time 분석 harness이므로 tools/.
외부 네트워크 호출 0 (로컬 파일만 읽음).

**워크플로우 (외래 1주 단위 반복)**:
    1. 외래 종료 후:
         uv run python -m tools.eval.analyze_edits --out reports/edit_analysis_$(date +%F).md
    2. 리포트의 'STT 오류 후보' 섹션 검토 → 반복되는 패턴(2+ 케이스) 우선 식별.
    3. 레이어 선택:
         - 반복 STT 오인식 (예: '엔드카벨'→'엔테카비르'): hints/postprocess.yaml에 정규식 룰.
         - 새 도메인 용어 (Whisper가 모르는 신약/검사명): hints/medical_hints.txt에 추가.
         - 음향 환각 (반복 음절 등): Whisper 옵션 (마지막 수단; 이미 condition_on_previous_text=False).
    4. drug 카테고리 룰 추가 시 기존 약물명과 발음 충돌 검증 (CLAUDE.md 토르세미드 사례).
    5. tests/test_postprocess.py에 새 룰별 단위 테스트 추가.
    6. 백엔드 재시작 — get_cached_rules가 startup에 재로드.
    7. 다음 외래에서 검증 → 재분석 → 반복.

**PHI 보호**: 환자 식별자는 입력 시점에 mask_identifiers() 통과한 상태. 출력에서는
컨텍스트 snippet을 max_context 자(기본 30) 이내로 제한. 외부 호출 0.

Usage:
    uv run python -m tools.eval.analyze_edits                              # 기본 logs/edits.jsonl
    uv run python -m tools.eval.analyze_edits --log /custom/path.jsonl
    uv run python -m tools.eval.analyze_edits --out reports/ea_2026-05-06.md
    uv run python -m tools.eval.analyze_edits --max-context 50 --min-edit-len 3
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.feedback.metrics import note_distance
from backend.feedback.models import EditFeedback
from backend.soap.models import ClinicalNote
from backend.stt.postprocess import get_cached_rules

logger = logging.getLogger("analyze_edits")

# 한글 2-8자 토큰 (의학 용어 후보). 5자 약물명(엔테카비르, 푸로세미드 등)과
# 6-8자 화합물명(스피로노락톤, 우르소데옥시콜산)을 모두 포착.
_HANGUL_TOKEN_RE = re.compile(r"[가-힣]{2,8}")

# 의학적 의미 없는 흔한 한국어 — 용어 후보에서 제외 (휴리스틱).
_STOPWORDS = frozenset({
    "환자", "오늘", "내일", "어제", "지난", "다음", "현재", "이번", "최근",
    "있습니다", "없습니다", "합니다", "됩니다", "드립니다", "하겠습니다",
    "예정", "관찰", "추적", "외래", "입원", "퇴원",
    "정도", "처음", "조금", "많이", "약간", "다소",
    "하지만", "그러나", "그리고", "또한", "그래서", "그러면",
})


@dataclass
class EditPair:
    """raw_text와 edited_note flatten string 사이의 difflib 'replace' opcode."""
    before: str
    after: str
    before_ctx: str
    after_ctx: str


@dataclass
class CaseAnalysis:
    index: int
    timestamp: str
    format_id: str
    raw_len: int
    corrected_len: int
    edited_len: int
    note_dist: int  # original_note → edited_note 편집 거리
    n_sections_changed: int
    edit_pairs: list[EditPair] = field(default_factory=list)
    applied: list[tuple[str, str, str, int]] = field(default_factory=list)  # (pattern, replace, category, count)
    section_changes: dict[str, int] = field(default_factory=dict)  # section → distance


def load_jsonl(path: Path) -> list[EditFeedback]:
    if not path.exists():
        raise FileNotFoundError(f"feedback log not found: {path}")
    out: list[EditFeedback] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(EditFeedback.model_validate_json(line))
            except Exception as e:
                logger.warning("skip line %d (parse failed): %s", i, e)
    return out


def flatten_note(note: ClinicalNote) -> str:
    """ClinicalNote의 모든 섹션 텍스트를 공백 1개로 연결. 빈 섹션은 스킵."""
    parts = [v for v in note.sections.values() if v]
    return " ".join(parts)


def extract_edit_pairs(raw: str, edited: str, *, max_context: int, min_len: int) -> list[EditPair]:
    """raw vs edited 문자열에서 difflib 'replace' opcode를 추출.

    min_len 미만(양쪽 모두)인 변경은 노이즈로 간주해 버림 (조사·구두점·짧은 오탈자).
    insert/delete만 있는 경우는 STT 오류라기보다 LLM 추가/누락이라 별도 layer로 봐야 함.
    """
    if not raw or not edited:
        return []
    sm = SequenceMatcher(None, raw, edited, autojunk=False)
    pairs: list[EditPair] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        before = raw[i1:i2]
        after = edited[j1:j2]
        if len(before) < min_len and len(after) < min_len:
            continue
        before_ctx = raw[max(0, i1 - max_context // 2): min(len(raw), i2 + max_context // 2)]
        after_ctx = edited[max(0, j1 - max_context // 2): min(len(edited), j2 + max_context // 2)]
        pairs.append(EditPair(
            before=before,
            after=after,
            before_ctx=before_ctx,
            after_ctx=after_ctx,
        ))
    return pairs


def extract_term_candidates(text: str, known_terms: set[str]) -> Counter:
    """한글 2-4자 토큰 중 known_terms에 없는 것의 빈도. stopwords 제외."""
    counter: Counter = Counter()
    for m in _HANGUL_TOKEN_RE.finditer(text):
        token = m.group(0)
        if token in known_terms or token in _STOPWORDS:
            continue
        counter[token] += 1
    return counter


def load_known_terms(hints_path: Path) -> set[str]:
    """medical_hints.txt에서 한글 토큰 set 추출 (주석/구두점 제외)."""
    if not hints_path.exists():
        return set()
    src = hints_path.read_text(encoding="utf-8")
    cleaned_lines = [ln for ln in src.splitlines() if not ln.strip().startswith("#")]
    body = " ".join(cleaned_lines)
    return set(_HANGUL_TOKEN_RE.findall(body))


def analyze_one(fb: EditFeedback, *, index: int, max_context: int, min_len: int) -> CaseAnalysis:
    edited_flat = flatten_note(fb.edited_note)
    nd = note_distance(fb.original_note, fb.edited_note)
    section_changes = {s.section: s.distance for s in nd.sections if s.changed}
    pairs = extract_edit_pairs(fb.raw_text, edited_flat, max_context=max_context, min_len=min_len)
    applied = [(a.pattern, a.replace, a.category, a.count) for a in fb.applied_replacements]
    return CaseAnalysis(
        index=index,
        timestamp=fb.timestamp,
        format_id=fb.format_id,
        raw_len=len(fb.raw_text),
        corrected_len=len(fb.corrected_text),
        edited_len=len(edited_flat),
        note_dist=nd.total_distance,
        n_sections_changed=nd.n_sections_changed,
        edit_pairs=pairs,
        applied=applied,
        section_changes=section_changes,
    )


def aggregate(cases: list[CaseAnalysis], existing_rules: tuple) -> dict[str, Any]:
    """전체 통계 + 룰 빈도 + 섹션별 편집 빈도."""
    total_n = len(cases)
    if total_n == 0:
        return {"total": 0}

    # postprocess 룰별 fire count (전체 케이스 합산)
    rule_counts: Counter = Counter()
    rule_meta: dict[str, tuple[str, str]] = {}  # pattern → (replace, category)
    for c in cases:
        for pattern, replace, category, count in c.applied:
            rule_counts[pattern] += count
            rule_meta[pattern] = (replace, category)

    # 기존 룰 중 fire 0 (제거 후보)
    never_fired = [
        (r.pattern, r.replace, r.category)
        for r in existing_rules
        if r.pattern not in rule_counts
    ]

    # 섹션별 편집 빈도
    section_freq: Counter = Counter()
    section_total_dist: Counter = Counter()
    for c in cases:
        for sec, dist in c.section_changes.items():
            section_freq[sec] += 1
            section_total_dist[sec] += dist

    return {
        "total": total_n,
        "mean_raw_len": sum(c.raw_len for c in cases) / total_n,
        "mean_corrected_len": sum(c.corrected_len for c in cases) / total_n,
        "mean_edited_len": sum(c.edited_len for c in cases) / total_n,
        "mean_note_dist": sum(c.note_dist for c in cases) / total_n,
        "rule_counts": rule_counts,
        "rule_meta": rule_meta,
        "never_fired": never_fired,
        "section_freq": section_freq,
        "section_total_dist": section_total_dist,
        "n_total_edit_pairs": sum(len(c.edit_pairs) for c in cases),
    }


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


_DECISION_GUIDE = """## 레이어 매핑 가이드

| 패턴 | 우선 레이어 | 비고 |
|---|---|---|
| 같은 약물명이 2+ 케이스에서 같은 형태로 잘못 인식 | `hints/postprocess.yaml` (drug) | 정규식 alternation. 다른 약물과 발음 충돌 검토 필수. |
| Whisper가 아예 다른 단어로 옮긴 새 도메인 용어 | `hints/medical_hints.txt` | 카테고리(진단/검사/약물)별 줄에 추가. last ~224 token 효과. |
| 같은 dictation에서 반복 음절·환각 패턴 | Whisper 옵션 | 이미 `condition_on_previous_text=False`. 추가 조정은 마지막 수단. |
| LLM 출력에서 섹션 misclass 빈발 | `hints/formats/<id>.yaml` few_shots / `backend/soap/prompts.py` | postprocess가 아닌 LLM layer. |
| 사용자가 textarea에서 정보 보강(약물·진단 추가) | 변경 불필요 | plan.md/Phase 2 UI 설계의 전제 — 사용자 보강이 워크플로우의 일부. |

**drug 룰 추가 절차**:
1. 후보 약물명을 다른 한국 약물명과 발음 비교 (예: 푸로세미드 ↔ 토르세미드).
2. 정규식 alternation에 알려진 변형 패턴 모두 포함 (`A|B|C`).
3. `tests/test_postprocess.py`에 unit test 추가.
4. 1주 후 다시 분석해 회귀 없는지 확인.
"""


def render_markdown(
    cases: list[CaseAnalysis],
    summary: dict[str, Any],
    *,
    term_candidates: Counter,
    max_context: int,
    top_terms: int = 20,
) -> str:
    lines: list[str] = []
    lines.append("# Edit-Log 분석 리포트")
    lines.append("")
    lines.append(f"**총 {summary.get('total', 0)} 케이스** 분석.")
    lines.append("")
    if summary.get("total", 0) == 0:
        lines.append("입력이 비어있음.")
        return "\n".join(lines)

    lines.append("## 1. 전체 통계")
    lines.append("")
    lines.append(f"- 평균 raw_text 길이: **{summary['mean_raw_len']:.0f}** 자")
    lines.append(f"- 평균 corrected_text 길이: **{summary['mean_corrected_len']:.0f}** 자")
    lines.append(f"- 평균 edited_note 길이 (모든 섹션 합): **{summary['mean_edited_len']:.0f}** 자")
    lines.append(f"- 평균 LLM→사용자 편집 거리: **{summary['mean_note_dist']:.0f}** chars")
    lines.append(f"- 총 STT 오류 후보 (replace opcode): **{summary['n_total_edit_pairs']}**")
    lines.append("")

    # postprocess 룰 빈도
    lines.append("## 2. 작동 중인 postprocess 룰 (fire count)")
    lines.append("")
    rc: Counter = summary["rule_counts"]
    rm: dict = summary["rule_meta"]
    if rc:
        lines.append("| pattern | replace | category | count |")
        lines.append("|---|---|---|---:|")
        for pattern, count in rc.most_common():
            replace, category = rm.get(pattern, ("?", "?"))
            lines.append(
                f"| `{_truncate(pattern, 40)}` | {replace} | {category} | {count} |"
            )
    else:
        lines.append("(이번 배치에서 어느 룰도 fire 안 함 — postprocess가 잡을 만한 STT 오류가 없었거나, 룰이 패턴을 못 맞춤)")
    lines.append("")

    # 한 번도 fire 안 한 기존 룰
    nf: list = summary["never_fired"]
    lines.append(f"## 3. 이번 배치에서 fire 안 한 기존 룰 ({len(nf)})")
    lines.append("")
    if nf:
        lines.append("(즉시 제거하지 말 것 — 다음 배치에서 fire 가능. 4-6주 fire 0이면 제거 후보)")
        lines.append("")
        for pattern, replace, category in nf[:30]:
            lines.append(f"- `{_truncate(pattern, 40)}` → {replace} *({category})*")
        if len(nf) > 30:
            lines.append(f"- ... 외 {len(nf) - 30}개")
    else:
        lines.append("(없음 — 모든 룰이 적어도 1회 fire)")
    lines.append("")

    # STT 오류 후보 (postprocess가 못 잡은 부분)
    lines.append("## 4. STT 오류 후보 (postprocess가 못 잡은 raw vs edited diff)")
    lines.append("")
    lines.append(
        "raw_text와 사용자 최종 편집(edited_note flatten)을 difflib로 정렬해 추출한 'replace' 구간."
        " STT 오인식뿐 아니라 LLM 변형·사용자 의역도 섞여있음 — 의학 용어 위주로 검토."
    )
    lines.append("")
    pair_count = sum(len(c.edit_pairs) for c in cases)
    if pair_count:
        lines.append(f"| case | before | after | before context | after context |")
        lines.append(f"|---:|---|---|---|---|")
        for c in cases:
            for p in c.edit_pairs:
                lines.append(
                    f"| #{c.index} | `{_truncate(p.before, max_context)}` | "
                    f"`{_truncate(p.after, max_context)}` | "
                    f"`{_truncate(p.before_ctx, max_context)}` | "
                    f"`{_truncate(p.after_ctx, max_context)}` |"
                )
    else:
        lines.append("(없음 — raw와 edited가 거의 같음)")
    lines.append("")

    # 섹션별 편집
    lines.append("## 5. 섹션별 편집 빈도 (LLM 출력 vs 사용자 편집)")
    lines.append("")
    sf: Counter = summary["section_freq"]
    std: Counter = summary["section_total_dist"]
    if sf:
        lines.append("| section | n_changed | total chars edited | mean per case |")
        lines.append("|---|---:|---:|---:|")
        n = summary["total"]
        for sec, freq in sf.most_common():
            lines.append(
                f"| {sec} | {freq}/{n} | {std[sec]} | {std[sec] / n:.1f} |"
            )
        lines.append("")
        lines.append(
            "*편집 빈도가 한 섹션에 집중되면 → LLM 프롬프트(few_shots, SYSTEM_PROMPT) 보강 후보.*"
            " STT 보강(postprocess/hints)으론 잘 안 풀림."
        )
    else:
        lines.append("(어느 섹션도 변경 안 됨 — 사용자가 LLM 출력을 그대로 사용)")
    lines.append("")

    # medical_hints.txt 후보 용어
    lines.append("## 6. medical_hints.txt 추가 후보 (한글 2-4자, 빈도순)")
    lines.append("")
    lines.append(
        "현재 hints/medical_hints.txt에 *없는* 한글 토큰. 의학 용어 여부는 수동 판단."
        " 흔한 일반어는 stopwords로 일부 제거됨."
    )
    lines.append("")
    if term_candidates:
        lines.append("| term | count |")
        lines.append("|---|---:|")
        for term, count in term_candidates.most_common(top_terms):
            lines.append(f"| {term} | {count} |")
    else:
        lines.append("(후보 없음)")
    lines.append("")

    lines.append(_DECISION_GUIDE)
    return "\n".join(lines)


def render_json(cases: list[CaseAnalysis], summary: dict[str, Any]) -> str:
    payload = {
        "summary": {
            "total": summary.get("total", 0),
            "mean_raw_len": summary.get("mean_raw_len", 0),
            "mean_corrected_len": summary.get("mean_corrected_len", 0),
            "mean_edited_len": summary.get("mean_edited_len", 0),
            "mean_note_dist": summary.get("mean_note_dist", 0),
            "n_total_edit_pairs": summary.get("n_total_edit_pairs", 0),
            "rule_counts": dict(summary.get("rule_counts", Counter())),
            "section_freq": dict(summary.get("section_freq", Counter())),
        },
        "cases": [
            {
                "index": c.index,
                "timestamp": c.timestamp,
                "format_id": c.format_id,
                "raw_len": c.raw_len,
                "corrected_len": c.corrected_len,
                "edited_len": c.edited_len,
                "note_dist": c.note_dist,
                "n_sections_changed": c.n_sections_changed,
                "edit_pairs": [
                    {"before": p.before, "after": p.after}
                    for p in c.edit_pairs
                ],
                "applied": [
                    {"pattern": pat, "replace": rep, "category": cat, "count": cnt}
                    for pat, rep, cat, cnt in c.applied
                ],
                "section_changes": c.section_changes,
            }
            for c in cases
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    p.add_argument("--log", help="feedback jsonl path (default: settings.feedback_log_path)")
    p.add_argument("--out", help="markdown 출력 경로 (생략 시 stdout). .json도 같이 씀.")
    p.add_argument("--max-context", type=int, default=30, help="컨텍스트 snippet 자수 (PHI 보호)")
    p.add_argument("--min-edit-len", type=int, default=4, help="이 미만 길이 변경은 노이즈로 무시")
    p.add_argument("--top-terms", type=int, default=20, help="medical_hints.txt 후보 출력 개수")
    args = p.parse_args()

    settings = get_settings()
    log_path = Path(args.log) if args.log else settings.feedback_log_path
    entries = load_jsonl(log_path)
    if not entries:
        print(f"[analyze] no entries in {log_path}", file=sys.stderr)
        return 1

    rules = get_cached_rules(settings.postprocess_file)
    known_terms = load_known_terms(settings.hints_file)

    cases: list[CaseAnalysis] = []
    term_counter: Counter = Counter()
    for i, fb in enumerate(entries):
        c = analyze_one(fb, index=i, max_context=args.max_context, min_len=args.min_edit_len)
        cases.append(c)
        term_counter.update(extract_term_candidates(fb.corrected_text, known_terms))

    summary = aggregate(cases, rules)
    md = render_markdown(
        cases, summary,
        term_candidates=term_counter,
        max_context=args.max_context,
        top_terms=args.top_terms,
    )
    js = render_json(cases, summary)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        out_path.with_suffix(".json").write_text(js, encoding="utf-8")
        print(f"[analyze] wrote {out_path} (+ .json)", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
