"""Inter-rater reliability — judge 점수의 의학적 신뢰성 검증.

워크플로우:
  1. `uv run python -m tools.eval.run_judge --out reports/judge_run.md` 실행
  2. reports/judge_run.json을 사용자(임상의)가 검토하며
     reports/human_grades.jsonl에 자기 점수 기록 (한 줄당 1 케이스):
       {"case_id": "drug_ambiguity_01", "hallucination_safety": 5, ...}
  3. `uv run python -m tools.eval.inter_rater reports/judge_run.json reports/human_grades.jsonl`
  4. judge vs 사용자 점수 비교 → 차원별 평균 차이 + Pearson 상관

  judge가 사용자와 너무 다르면(예: 평균 차이 ≥1.5 또는 상관 ≤0.3) judge 프롬프트를
  재설계해야 한다는 신호. 이 검증을 통과해야 50개로 확장하는 게 안전.

이 도구 자체는 클라우드 호출 없음 — 이미 저장된 점수를 비교만 함.
"""
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

DIMENSIONS = (
    "hallucination_safety",
    "section_accuracy",
    "completeness",
    "drug_value_fidelity",
)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """단순 Pearson 상관. n<2 또는 분산 0이면 None."""
    if len(xs) < 2 or len(ys) != len(xs):
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(dx2 * dy2)
    return num / denom if denom else None


def load_judge_results(path: Path) -> dict[str, dict[str, int]]:
    """judge json → {case_id: {dimension: score}}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, int]] = {}
    for r in data.get("results", []):
        score = r.get("score")
        if not score:
            continue
        out[r["case_id"]] = {d: score[d]["score"] for d in DIMENSIONS}
    return out


def load_human_grades(path: Path) -> dict[str, dict[str, int]]:
    """human jsonl → {case_id: {dimension: score}}.

    각 줄은 단일 케이스 채점. 누락된 차원은 무시 (부분 채점 허용).
    """
    out: dict[str, dict[str, int]] = {}
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[inter_rater] line {i} skipped: {e}", file=sys.stderr)
                continue
            cid = d.get("case_id")
            if not cid:
                print(f"[inter_rater] line {i} missing case_id, skipped", file=sys.stderr)
                continue
            scores = {dim: int(d[dim]) for dim in DIMENSIONS if dim in d}
            if scores:
                out[cid] = scores
    return out


def compare(
    judge: dict[str, dict[str, int]],
    human: dict[str, dict[str, int]],
) -> dict[str, Any]:
    common = sorted(set(judge) & set(human))
    if not common:
        return {
            "common_cases": 0,
            "judge_only": sorted(set(judge) - set(human)),
            "human_only": sorted(set(human) - set(judge)),
            "by_dimension": {},
            "case_diffs": [],
        }

    by_dim: dict[str, dict[str, Any]] = {}
    for dim in DIMENSIONS:
        js: list[float] = []
        hs: list[float] = []
        for cid in common:
            if dim in human[cid] and dim in judge[cid]:
                js.append(float(judge[cid][dim]))
                hs.append(float(human[cid][dim]))
        if not js:
            by_dim[dim] = {"n": 0}
            continue
        diffs = [j - h for j, h in zip(js, hs)]
        by_dim[dim] = {
            "n": len(js),
            "mean_judge": sum(js) / len(js),
            "mean_human": sum(hs) / len(hs),
            "mean_diff": sum(diffs) / len(diffs),
            "mean_abs_diff": sum(abs(d) for d in diffs) / len(diffs),
            "max_abs_diff": max(abs(d) for d in diffs),
            "pearson": _pearson(js, hs),
        }

    case_diffs = []
    for cid in common:
        per_dim = []
        total_abs = 0
        for dim in DIMENSIONS:
            if dim in human[cid] and dim in judge[cid]:
                d = judge[cid][dim] - human[cid][dim]
                per_dim.append({"dim": dim, "judge": judge[cid][dim],
                                "human": human[cid][dim], "diff": d})
                total_abs += abs(d)
        case_diffs.append({"case_id": cid, "total_abs_diff": total_abs, "by_dim": per_dim})
    case_diffs.sort(key=lambda r: r["total_abs_diff"], reverse=True)

    return {
        "common_cases": len(common),
        "judge_only": sorted(set(judge) - set(human)),
        "human_only": sorted(set(human) - set(judge)),
        "by_dimension": by_dim,
        "case_diffs": case_diffs,
    }


def render(report: dict[str, Any]) -> str:
    lines: list[str] = ["# Inter-rater reliability 리포트", ""]
    n = report["common_cases"]
    lines.append(f"공통 케이스: **{n}개**")
    if report.get("judge_only"):
        lines.append(f"- judge만 채점: {', '.join(report['judge_only'])}")
    if report.get("human_only"):
        lines.append(f"- human만 채점: {', '.join(report['human_only'])}")
    lines.append("")

    if not n:
        lines.append("(공통 케이스 없음 — 비교 불가)")
        return "\n".join(lines)

    lines.append("## 차원별 비교")
    lines.append("")
    lines.append("| 차원 | n | judge 평균 | human 평균 | mean diff (j−h) | mean \\|diff\\| | max \\|diff\\| | Pearson |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for dim in DIMENSIONS:
        s = report["by_dimension"].get(dim, {"n": 0})
        if not s.get("n"):
            lines.append(f"| {dim} | 0 | — | — | — | — | — | — |")
            continue
        pearson = s.get("pearson")
        pearson_str = f"{pearson:.2f}" if pearson is not None else "n/a"
        lines.append(
            f"| {dim} | {s['n']} | {s['mean_judge']:.2f} | {s['mean_human']:.2f} | "
            f"{s['mean_diff']:+.2f} | {s['mean_abs_diff']:.2f} | {s['max_abs_diff']:.0f} | {pearson_str} |"
        )
    lines.append("")

    # 신뢰성 판정 게이트
    flags: list[str] = []
    for dim, s in report["by_dimension"].items():
        if not s.get("n"):
            continue
        if s["mean_abs_diff"] >= 1.5:
            flags.append(f"⚠️  {dim}: mean |diff| {s['mean_abs_diff']:.2f} ≥ 1.5 — judge가 일관되게 다르게 채점")
        p = s.get("pearson")
        if p is not None and p < 0.3 and s["n"] >= 5:
            flags.append(f"⚠️  {dim}: Pearson {p:.2f} < 0.3 — 상관 부족, 50개 확장 전 prompt 재설계")
    if flags:
        lines.append("## 경고")
        lines.append("")
        for f in flags:
            lines.append(f"- {f}")
        lines.append("")

    if report["case_diffs"]:
        lines.append("## 케이스별 차이 (총 abs diff 큰 순)")
        lines.append("")
        for c in report["case_diffs"][:10]:
            lines.append(f"### {c['case_id']} (총 |diff| {c['total_abs_diff']})")
            for d in c["by_dim"]:
                lines.append(
                    f"- {d['dim']}: judge {d['judge']} vs human {d['human']} (Δ {d['diff']:+d})"
                )
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("judge_json", help="run_judge가 출력한 .json")
    p.add_argument("human_jsonl", help="사용자 채점 jsonl (case_id + 4 차원 점수)")
    p.add_argument("--out", help="markdown 출력 경로 (생략 시 stdout)")
    args = p.parse_args()

    judge = load_judge_results(Path(args.judge_json))
    human = load_human_grades(Path(args.human_jsonl))
    report = compare(judge, human)
    md = render(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"[inter_rater] wrote {out}", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
