"""inter_rater 도구 테스트 — 외부 호출 없음, 파일 비교만."""
import json
from pathlib import Path

from tools.eval.inter_rater import (
    _pearson,
    compare,
    load_human_grades,
    load_judge_results,
    render,
)


def test_pearson_perfect_positive() -> None:
    assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == 1.0


def test_pearson_perfect_negative() -> None:
    assert _pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0


def test_pearson_zero_variance_returns_none() -> None:
    assert _pearson([1.0, 1.0, 1.0], [2.0, 3.0, 4.0]) is None


def test_pearson_too_few_points() -> None:
    assert _pearson([1.0], [2.0]) is None


def test_load_judge_results_skips_failed_cases(tmp_path: Path) -> None:
    p = tmp_path / "judge.json"
    p.write_text(json.dumps({
        "results": [
            {
                "case_id": "ok_1",
                "score": {
                    "hallucination_safety": {"score": 5, "reasoning": "x"},
                    "section_accuracy": {"score": 4, "reasoning": "x"},
                    "completeness": {"score": 3, "reasoning": "x"},
                    "drug_value_fidelity": {"score": 5, "reasoning": "x"},
                },
            },
            {"case_id": "failed", "score": None, "error": "judge timeout"},
        ]
    }))
    out = load_judge_results(p)
    assert "ok_1" in out
    assert "failed" not in out
    assert out["ok_1"]["hallucination_safety"] == 5


def test_load_human_grades_partial(tmp_path: Path) -> None:
    """부분 채점(일부 차원 누락)도 허용."""
    p = tmp_path / "human.jsonl"
    p.write_text(
        '{"case_id": "c1", "hallucination_safety": 4, "section_accuracy": 3}\n'
        '{"case_id": "c2", "hallucination_safety": 5, "section_accuracy": 5, '
        '"completeness": 5, "drug_value_fidelity": 5}\n'
    )
    out = load_human_grades(p)
    assert out["c1"] == {"hallucination_safety": 4, "section_accuracy": 3}
    assert len(out["c2"]) == 4


def test_load_human_grades_skips_invalid_lines(tmp_path: Path, capsys) -> None:
    p = tmp_path / "human.jsonl"
    p.write_text("not-json\n\n" + json.dumps({"case_id": "c1", "hallucination_safety": 4}) + "\n")
    out = load_human_grades(p)
    assert "c1" in out
    assert len(out) == 1


def test_compare_high_agreement() -> None:
    judge = {
        "c1": {"hallucination_safety": 5, "section_accuracy": 4, "completeness": 4, "drug_value_fidelity": 5},
        "c2": {"hallucination_safety": 4, "section_accuracy": 3, "completeness": 3, "drug_value_fidelity": 4},
    }
    human = {
        "c1": {"hallucination_safety": 5, "section_accuracy": 4, "completeness": 4, "drug_value_fidelity": 5},
        "c2": {"hallucination_safety": 4, "section_accuracy": 3, "completeness": 3, "drug_value_fidelity": 4},
    }
    rep = compare(judge, human)
    assert rep["common_cases"] == 2
    for dim, s in rep["by_dimension"].items():
        assert s["mean_abs_diff"] == 0.0


def test_compare_disagreement_flags_generated() -> None:
    judge = {f"c{i}": {d: 5 for d in (
        "hallucination_safety", "section_accuracy", "completeness", "drug_value_fidelity"
    )} for i in range(5)}
    human = {f"c{i}": {d: 2 for d in (
        "hallucination_safety", "section_accuracy", "completeness", "drug_value_fidelity"
    )} for i in range(5)}
    rep = compare(judge, human)
    assert rep["common_cases"] == 5
    md = render(rep)
    # mean_abs_diff = 3.0 ≥ 1.5 → 경고 항목 등장
    assert "mean |diff|" in md
    assert "⚠️" in md


def test_compare_handles_disjoint_sets() -> None:
    judge = {"c1": {"hallucination_safety": 5, "section_accuracy": 4,
                    "completeness": 3, "drug_value_fidelity": 5}}
    human = {"c2": {"hallucination_safety": 4, "section_accuracy": 4,
                    "completeness": 4, "drug_value_fidelity": 4}}
    rep = compare(judge, human)
    assert rep["common_cases"] == 0
    assert rep["judge_only"] == ["c1"]
    assert rep["human_only"] == ["c2"]


def test_render_no_common_cases() -> None:
    md = render(compare({}, {}))
    assert "공통 케이스" in md
    assert "공통 케이스 없음" in md or "**0개**" in md
