"""LLM-as-judge 평가 runner.

흐름:
  1. tests/fixtures/eval_cases/*.yaml 로드 (review_status=approved 기본)
  2. 각 케이스의 source_text를 로컬 LM Studio로 의무기록 생성
  3. Claude Code SDK(로컬 `claude` CLI)로 judge(Sonnet) 호출 → 4 차원 점수
  4. markdown + json 리포트

인증: 로컬 `claude` CLI의 Max 구독 인증을 사용 — 별도 환경변수 불필요.
PHI guard: 케이스의 is_synthetic=True가 schema에 강제되어 있고, judge.py에서
호출 직전 재확인. logs/edits.jsonl 같은 실데이터는 이 runner를 통과 못 함.

Usage:
    uv run python -m tools.eval.run_judge                              # approved 케이스만
    uv run python -m tools.eval.run_judge --include-pending            # pending 포함
    uv run python -m tools.eval.run_judge --case-glob "drug_*"         # ID 매칭
    uv run python -m tools.eval.run_judge --dry-run                    # judge 호출 없이 노트 생성만
    uv run python -m tools.eval.run_judge --out reports/judge.md       # 파일 저장
"""
import argparse
import asyncio
import fnmatch
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.eval.cases import SyntheticCase, load_cases
from tools.eval.judge import JudgeError, judge_case
from backend.eval.rubric import JudgeScore
from backend.soap.formats import get_cached_format
from backend.soap.llm_client import LLMError, structure_to_note
from backend.soap.models import ClinicalNote

logger = logging.getLogger("run_judge")

DEFAULT_CASES_DIR = Path("tests/fixtures/eval_cases")


@dataclass
class JudgeResult:
    case: SyntheticCase
    note: ClinicalNote | None
    note_elapsed: float | None
    score: JudgeScore | None
    judge_elapsed: float | None
    error: str | None  # generation 또는 judge 단계 에러 메시지

    @property
    def stage(self) -> str:
        if self.note is None:
            return "note_generation_failed"
        if self.score is None:
            return "judge_failed"
        return "ok"


async def _generate_note(case: SyntheticCase, settings: Any) -> tuple[ClinicalNote, float]:
    fmt = get_cached_format(settings.formats_dir, case.format_id)
    return await structure_to_note(
        case.source_text,
        fmt=fmt,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
    )


async def evaluate_one(
    case: SyntheticCase,
    *,
    settings: Any,
    judge_model: str,
    dry_run: bool,
) -> JudgeResult:
    # 1단계: 노트 생성 (LM Studio)
    try:
        note, note_elapsed = await _generate_note(case, settings)
    except (LLMError, FileNotFoundError) as e:
        return JudgeResult(case=case, note=None, note_elapsed=None,
                           score=None, judge_elapsed=None, error=f"note gen: {e}")

    if dry_run:
        return JudgeResult(case=case, note=note, note_elapsed=note_elapsed,
                           score=None, judge_elapsed=None, error="dry-run (judge skipped)")

    # 2단계: judge (클라우드 Sonnet)
    fmt = get_cached_format(settings.formats_dir, case.format_id)
    try:
        score, judge_elapsed = await judge_case(
            case=case, fmt=fmt, note=note, model=judge_model,
        )
    except JudgeError as e:
        return JudgeResult(case=case, note=note, note_elapsed=note_elapsed,
                           score=None, judge_elapsed=None, error=f"judge: {e}")

    return JudgeResult(case=case, note=note, note_elapsed=note_elapsed,
                       score=score, judge_elapsed=judge_elapsed, error=None)


def aggregate(results: list[JudgeResult]) -> dict[str, Any]:
    valid = [r for r in results if r.score is not None]
    by_trap: dict[str, list[JudgeResult]] = {}
    for r in valid:
        by_trap.setdefault(r.case.trap_type, []).append(r)

    def _stats(rs: list[JudgeResult]) -> dict[str, float]:
        if not rs:
            return {"n": 0}
        scores = [r.score for r in rs if r.score]
        return {
            "n": len(rs),
            "pass_rate": sum(1 for s in scores if s.overall_pass) / len(scores),
            "mean_total": sum(s.total for s in scores) / len(scores),
            "mean_hallucination_safety": sum(s.hallucination_safety.score for s in scores) / len(scores),
            "mean_section_accuracy": sum(s.section_accuracy.score for s in scores) / len(scores),
            "mean_completeness": sum(s.completeness.score for s in scores) / len(scores),
            "mean_drug_value_fidelity": sum(s.drug_value_fidelity.score for s in scores) / len(scores),
        }

    return {
        "overall": _stats(valid),
        "by_trap_type": {k: _stats(rs) for k, rs in sorted(by_trap.items())},
        "total": len(results),
        "valid": len(valid),
        "failures": sum(1 for r in results if r.error and r.stage != "ok"),
    }


def render_markdown(results: list[JudgeResult], summary: dict[str, Any]) -> str:
    lines: list[str] = ["# LLM-as-Judge 평가 리포트", ""]
    o = summary["overall"]
    lines.append(
        f"**총 {summary['total']} 케이스** (judge 성공 {summary['valid']}, 실패 {summary['failures']})"
    )
    lines.append("")
    if o.get("n", 0):
        lines.append("## 전체 통계")
        lines.append("")
        lines.append(f"- Pass rate: **{o['pass_rate']*100:.0f}%**")
        lines.append(f"- 평균 총점: **{o['mean_total']:.1f}** / 20")
        lines.append(f"- 환각 안전도 (hallucination_safety): {o['mean_hallucination_safety']:.2f}/5")
        lines.append(f"- 섹션 정확도 (section_accuracy): {o['mean_section_accuracy']:.2f}/5")
        lines.append(f"- 완전성 (completeness): {o['mean_completeness']:.2f}/5")
        lines.append(f"- 약물·수치 보존 (drug_value_fidelity): {o['mean_drug_value_fidelity']:.2f}/5")
        lines.append("")

    if summary["by_trap_type"]:
        lines.append("## Trap Type별")
        lines.append("")
        lines.append("| trap_type | n | pass | total | hallu | section | complete | fidelity |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for t, s in summary["by_trap_type"].items():
            lines.append(
                f"| {t} | {s['n']} | {s['pass_rate']*100:.0f}% | {s['mean_total']:.1f} | "
                f"{s['mean_hallucination_safety']:.1f} | {s['mean_section_accuracy']:.1f} | "
                f"{s['mean_completeness']:.1f} | {s['mean_drug_value_fidelity']:.1f} |"
            )
        lines.append("")

    lines.append("## 케이스별 상세")
    lines.append("")
    for r in results:
        lines.append(f"### {r.case.id} ({r.case.trap_type})")
        lines.append("")
        # 노트 생성 자체가 실패한 경우
        if r.note is None:
            lines.append(f"**에러 (note 생성 실패)**: `{r.error}`")
            lines.append("")
            continue

        # 점수가 있으면 점수 + 근거 표시 (정상 흐름)
        if r.score is not None:
            s = r.score
            flag = "✅ PASS" if s.overall_pass else "❌ FAIL"
            lines.append(f"- {flag} (총점 {s.total}/20, min {s.min_dim}/5)")
            lines.append(
                f"- 환각 {s.hallucination_safety.score} | 섹션 {s.section_accuracy.score} | "
                f"완전 {s.completeness.score} | 보존 {s.drug_value_fidelity.score}"
            )
            lines.append(f"- 종합: {s.summary}")
        elif r.error:
            # 노트는 있지만 judge 단계 실패/스킵 — 원문/노트는 보여줌
            lines.append(f"- **judge 단계**: `{r.error}` (노트는 아래에 표시)")
        lines.append("")
        lines.append("**원문**:")
        lines.append(f"> {r.case.source_text}")
        lines.append("")
        lines.append("**LLM 출력**:")
        for k, v in r.note.sections.items():
            lines.append(f"- `{k}`: {v if v else '(빈 값)'}")
        lines.append("")
        if r.score is not None:
            s = r.score
            lines.append("**judge 근거 (각 차원)**:")
            for label, ds in [
                ("환각", s.hallucination_safety),
                ("섹션", s.section_accuracy),
                ("완전성", s.completeness),
                ("보존", s.drug_value_fidelity),
            ]:
                lines.append(f"- {label} ({ds.score}/5): {ds.reasoning}")
            lines.append("")
    return "\n".join(lines)


def render_json(results: list[JudgeResult], summary: dict[str, Any]) -> str:
    payload = {
        "summary": summary,
        "results": [
            {
                "case_id": r.case.id,
                "trap_type": r.case.trap_type,
                "format_id": r.case.format_id,
                "stage": r.stage,
                "error": r.error,
                "note_elapsed_seconds": r.note_elapsed,
                "judge_elapsed_seconds": r.judge_elapsed,
                "note": r.note.model_dump() if r.note else None,
                "score": r.score.model_dump() if r.score else None,
            }
            for r in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def filter_cases(cases: list[SyntheticCase], glob: str | None) -> list[SyntheticCase]:
    if not glob:
        return cases
    return [c for c in cases if fnmatch.fnmatch(c.id, glob)]


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    cases_dir = Path(args.cases_dir) if args.cases_dir else DEFAULT_CASES_DIR
    cases = load_cases(cases_dir, include_pending=args.include_pending)
    cases = filter_cases(cases, args.case_glob)

    if not cases:
        print(
            f"[run_judge] no cases match (dir={cases_dir}, "
            f"include_pending={args.include_pending}, glob={args.case_glob!r})",
            file=sys.stderr,
        )
        return 1

    # 인증은 로컬 `claude` CLI(Max 구독)에서 처리됨 — 사전 키 검사 불필요.
    # 인증 문제는 첫 judge 호출 시 JudgeError로 노출됨.

    print(
        f"[run_judge] {len(cases)} 케이스 처리 시작 "
        f"(judge={args.judge_model}, dry_run={args.dry_run})",
        file=sys.stderr,
    )

    results: list[JudgeResult] = []
    for i, case in enumerate(cases, start=1):
        print(f"  [{i}/{len(cases)}] {case.id} ({case.trap_type})...", file=sys.stderr, flush=True)
        r = await evaluate_one(
            case, settings=settings, judge_model=args.judge_model, dry_run=args.dry_run,
        )
        results.append(r)
        if r.error and r.stage != "ok":
            print(f"    ! {r.error}", file=sys.stderr)
        elif r.score:
            flag = "PASS" if r.score.overall_pass else "FAIL"
            print(
                f"    {flag} total={r.score.total} hallu={r.score.hallucination_safety.score} "
                f"sec={r.score.section_accuracy.score} comp={r.score.completeness.score} "
                f"fid={r.score.drug_value_fidelity.score} "
                f"({r.note_elapsed:.1f}s + {r.judge_elapsed:.1f}s)",
                file=sys.stderr,
            )

    summary = aggregate(results)
    md = render_markdown(results, summary)
    js = render_json(results, summary)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        out_path.with_suffix(".json").write_text(js, encoding="utf-8")
        print(f"\n[run_judge] wrote {out_path} (+ .json)", file=sys.stderr)
    else:
        print(md)
    return 0 if summary["failures"] == 0 else 1


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--cases-dir", help=f"케이스 yaml 디렉터리 (default: {DEFAULT_CASES_DIR})")
    p.add_argument("--include-pending", action="store_true",
                   help="review_status=pending 케이스 포함 (기본: approved만)")
    p.add_argument("--case-glob", help="케이스 ID glob 필터 (예: 'drug_*')")
    p.add_argument("--judge-model", default="claude-sonnet-4-6")
    p.add_argument("--dry-run", action="store_true",
                   help="LM Studio로 노트 생성만 하고 judge는 호출하지 않음")
    p.add_argument("--out", help="markdown 출력 경로 (생략 시 stdout). .json도 같이 씀.")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
