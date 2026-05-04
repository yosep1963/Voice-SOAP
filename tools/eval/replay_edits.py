"""Edit-replay harness — `logs/edits.jsonl`에 누적된 사용자 편집 기록을 회귀 게이트로 활용.

목표: 새 프롬프트/모델이 사용자가 직접 고친 결과(=gold)에 더 가까워졌는지 정량 비교.

흐름 (한 엔트리당):
  1. corrected_text (STT 후처리 후) → 현재 LLM/프롬프트로 재생성
  2. 새 출력 vs edited_note (gold) 거리 = `replay_to_gold`
  3. original_note (당시 LLM) vs edited_note 거리 = `baseline_to_gold` (저장된 baseline)
  4. improvement = baseline - replay  (양수면 개선, 음수면 회귀)

LM Studio가 켜져있지 않으면 즉시 실패. 외부 네트워크 호출 없음 (localhost만).

Usage:
    uv run python -m tools.eval.replay_edits                    # 전체 logs/edits.jsonl
    uv run python -m tools.eval.replay_edits --limit 5
    uv run python -m tools.eval.replay_edits --dry-run          # LLM 호출 없이 스키마만 검증
    uv run python -m tools.eval.replay_edits --out reports/replay_$(date +%F).{md,json}
"""
import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.feedback.metrics import NoteDistance, note_distance
from backend.feedback.models import EditFeedback
from backend.soap.formats import get_cached_format
from backend.soap.llm_client import LLMError, structure_to_note
from backend.soap.models import ClinicalNote

logger = logging.getLogger("replay_edits")


@dataclass
class ReplayResult:
    """단일 엔트리에 대한 재생성 결과."""

    index: int
    timestamp: str
    format_id: str
    source_text: str
    edited: ClinicalNote  # 사용자 gold
    baseline: ClinicalNote  # 저장 시점의 LLM 출력
    replay: ClinicalNote | None  # 새 LLM 출력 (None = 호출 실패)
    error: str | None
    elapsed_seconds: float | None
    baseline_to_gold: NoteDistance
    replay_to_gold: NoteDistance | None

    @property
    def improvement(self) -> int | None:
        if self.replay_to_gold is None:
            return None
        return self.baseline_to_gold.total_distance - self.replay_to_gold.total_distance


def load_jsonl(path: Path, limit: int | None = None) -> list[EditFeedback]:
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
            if limit is not None and len(out) >= limit:
                break
    return out


async def replay_one(
    fb: EditFeedback,
    *,
    settings: Any,
    index: int,
) -> ReplayResult:
    baseline_d = note_distance(fb.original_note, fb.edited_note)
    try:
        fmt = get_cached_format(settings.formats_dir, fb.format_id)
    except FileNotFoundError as e:
        return ReplayResult(
            index=index,
            timestamp=fb.timestamp,
            format_id=fb.format_id,
            source_text=fb.corrected_text,
            edited=fb.edited_note,
            baseline=fb.original_note,
            replay=None,
            error=f"unknown format_id: {e}",
            elapsed_seconds=None,
            baseline_to_gold=baseline_d,
            replay_to_gold=None,
        )

    try:
        replay_note, elapsed = await structure_to_note(
            fb.corrected_text,
            fmt=fmt,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )
    except LLMError as e:
        return ReplayResult(
            index=index,
            timestamp=fb.timestamp,
            format_id=fb.format_id,
            source_text=fb.corrected_text,
            edited=fb.edited_note,
            baseline=fb.original_note,
            replay=None,
            error=str(e),
            elapsed_seconds=None,
            baseline_to_gold=baseline_d,
            replay_to_gold=None,
        )

    replay_d = note_distance(replay_note, fb.edited_note)
    return ReplayResult(
        index=index,
        timestamp=fb.timestamp,
        format_id=fb.format_id,
        source_text=fb.corrected_text,
        edited=fb.edited_note,
        baseline=fb.original_note,
        replay=replay_note,
        error=None,
        elapsed_seconds=elapsed,
        baseline_to_gold=baseline_d,
        replay_to_gold=replay_d,
    )


def aggregate(results: list[ReplayResult]) -> dict[str, Any]:
    """전체/포맷별 평균 metric. dry-run(replay=None)인 항목은 baseline 통계만 포함."""
    valid = [r for r in results if r.replay_to_gold is not None]
    failures = [r for r in results if r.replay_to_gold is None]

    by_format: dict[str, list[ReplayResult]] = {}
    for r in valid:
        by_format.setdefault(r.format_id, []).append(r)

    def _stats(rs: list[ReplayResult]) -> dict[str, float]:
        if not rs:
            return {"n": 0}
        impr = [r.improvement for r in rs if r.improvement is not None]
        baseline = [r.baseline_to_gold.total_distance for r in rs]
        replay = [r.replay_to_gold.total_distance for r in rs if r.replay_to_gold]
        elapsed = [r.elapsed_seconds for r in rs if r.elapsed_seconds is not None]
        return {
            "n": len(rs),
            "mean_baseline_distance": sum(baseline) / len(baseline),
            "mean_replay_distance": sum(replay) / len(replay) if replay else 0.0,
            "mean_improvement": sum(impr) / len(impr) if impr else 0.0,
            "n_regressions": sum(1 for x in impr if x < 0),
            "n_improvements": sum(1 for x in impr if x > 0),
            "n_unchanged": sum(1 for x in impr if x == 0),
            "mean_elapsed_seconds": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        }

    return {
        "overall": _stats(valid),
        "by_format": {fid: _stats(rs) for fid, rs in sorted(by_format.items())},
        "failures": len(failures),
        "total": len(results),
    }


def render_markdown(results: list[ReplayResult], summary: dict[str, Any], top_k: int = 5) -> str:
    lines: list[str] = []
    lines.append("# Edit-Replay Harness Report")
    lines.append("")
    o = summary["overall"]
    lines.append(f"**총 엔트리**: {summary['total']}, 성공 {o.get('n', 0)}, 실패 {summary['failures']}")
    lines.append("")
    if o.get("n", 0):
        lines.append("## 전체 통계")
        lines.append("")
        lines.append(f"- 평균 baseline→gold 거리: **{o['mean_baseline_distance']:.1f}** chars")
        lines.append(f"- 평균 replay→gold 거리: **{o['mean_replay_distance']:.1f}** chars")
        lines.append(f"- 평균 개선 (음수=회귀): **{o['mean_improvement']:+.1f}** chars")
        lines.append(
            f"- 개선 {o['n_improvements']} / 회귀 {o['n_regressions']} / 불변 {o['n_unchanged']}"
        )
        lines.append(f"- 평균 LLM 응답: {o['mean_elapsed_seconds']:.2f}s")
        lines.append("")

    if summary["by_format"]:
        lines.append("## 포맷별")
        lines.append("")
        lines.append("| format | n | baseline | replay | improvement | regressions |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for fid, s in summary["by_format"].items():
            lines.append(
                f"| {fid} | {s['n']} | {s['mean_baseline_distance']:.1f} | "
                f"{s['mean_replay_distance']:.1f} | {s['mean_improvement']:+.1f} | "
                f"{s['n_regressions']} |"
            )
        lines.append("")

    valid = [r for r in results if r.replay_to_gold is not None]
    regressions = sorted(
        (r for r in valid if (r.improvement or 0) < 0),
        key=lambda r: r.improvement or 0,
    )[:top_k]
    if regressions:
        lines.append(f"## 회귀 케이스 top {len(regressions)}")
        lines.append("")
        for r in regressions:
            lines.append(
                f"### #{r.index} ({r.format_id}, {r.timestamp}) "
                f"— Δ {r.improvement:+d} chars"
            )
            lines.append("")
            lines.append(f"- baseline→gold: {r.baseline_to_gold.total_distance}")
            lines.append(f"- replay→gold: {r.replay_to_gold.total_distance if r.replay_to_gold else '?'}")
            lines.append("")
            lines.append("**source_text** (앞부분):")
            lines.append("")
            lines.append(f"> {r.source_text[:200]}{'...' if len(r.source_text) > 200 else ''}")
            lines.append("")

    failures = [r for r in results if r.error]
    if failures:
        lines.append(f"## 실패 ({len(failures)})")
        lines.append("")
        for r in failures[:10]:
            lines.append(f"- #{r.index} ({r.format_id}): `{r.error}`")
        lines.append("")
    return "\n".join(lines)


def render_json(results: list[ReplayResult], summary: dict[str, Any]) -> str:
    payload = {
        "summary": summary,
        "results": [
            {
                "index": r.index,
                "timestamp": r.timestamp,
                "format_id": r.format_id,
                "baseline_to_gold": r.baseline_to_gold.total_distance,
                "replay_to_gold": r.replay_to_gold.total_distance if r.replay_to_gold else None,
                "improvement": r.improvement,
                "elapsed_seconds": r.elapsed_seconds,
                "error": r.error,
            }
            for r in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    log_path = Path(args.log) if args.log else settings.feedback_log_path
    entries = load_jsonl(log_path, limit=args.limit)
    if not entries:
        print(f"[replay] no entries in {log_path}", file=sys.stderr)
        return 1

    results: list[ReplayResult] = []
    if args.dry_run:
        for i, fb in enumerate(entries):
            d = note_distance(fb.original_note, fb.edited_note)
            results.append(
                ReplayResult(
                    index=i,
                    timestamp=fb.timestamp,
                    format_id=fb.format_id,
                    source_text=fb.corrected_text,
                    edited=fb.edited_note,
                    baseline=fb.original_note,
                    replay=None,
                    error="dry-run",
                    elapsed_seconds=None,
                    baseline_to_gold=d,
                    replay_to_gold=None,
                )
            )
    else:
        for i, fb in enumerate(entries):
            print(f"[replay] {i + 1}/{len(entries)} ({fb.format_id})...", file=sys.stderr, flush=True)
            r = await replay_one(fb, settings=settings, index=i)
            results.append(r)
            if r.error:
                print(f"  ! {r.error}", file=sys.stderr)
            else:
                print(
                    f"  baseline={r.baseline_to_gold.total_distance} "
                    f"replay={r.replay_to_gold.total_distance if r.replay_to_gold else '?'} "
                    f"Δ={r.improvement:+d} ({r.elapsed_seconds:.2f}s)",
                    file=sys.stderr,
                )

    if args.dry_run:
        # dry-run에서는 baseline 통계만 의미있음 — 별도 요약
        baseline = [r.baseline_to_gold.total_distance for r in results]
        print(f"\n[replay dry-run] entries={len(results)}")
        print(f"  baseline→gold 거리 평균: {sum(baseline)/len(baseline):.1f}")
        print(f"  baseline→gold 거리 중간값: {sorted(baseline)[len(baseline)//2]}")
        print(f"  unchanged-by-user (LLM 출력 그대로 복사): "
              f"{sum(1 for d in baseline if d == 0)}/{len(baseline)}")
        return 0

    summary = aggregate(results)
    md = render_markdown(results, summary)
    js = render_json(results, summary)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        out_path.with_suffix(".json").write_text(js, encoding="utf-8")
        print(f"\n[replay] wrote {out_path} (+ .json)", file=sys.stderr)
    else:
        print(md)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--log", help="feedback jsonl path (default: settings.feedback_log_path)")
    p.add_argument("--limit", type=int, help="첫 N개만 처리 (스모크 테스트용)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="LLM 호출 없이 jsonl 파싱 + baseline 거리만 계산",
    )
    p.add_argument("--out", help="출력 markdown 경로 (생략 시 stdout). .json도 같이 씀.")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
