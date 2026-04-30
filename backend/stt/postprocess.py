"""STT 후처리 사전. Whisper 출력의 알려진 오인식을 LLM 호출 전에 보정.

`hints/postprocess.yaml` 형식 (plan.md §6):
    - pattern: "퓨로스마이드"     # 정규식
      replace: "푸로세미드"
      category: drug              # 분류 (logging/감사용)
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


@dataclass(frozen=True)
class PostprocessRule:
    pattern: str
    replace: str
    category: str
    _regex: re.Pattern = None  # type: ignore[assignment]

    @classmethod
    def compile(cls, pattern: str, replace: str, category: str) -> "PostprocessRule":
        compiled = re.compile(pattern)
        return cls(pattern=pattern, replace=replace, category=category, _regex=compiled)


class AppliedReplacement(BaseModel):
    pattern: str
    replace: str
    category: str
    count: int


def load_postprocess_rules(path: Path) -> list[PostprocessRule]:
    if not path.exists():
        raise FileNotFoundError(f"Postprocess file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError(f"Postprocess file must be a YAML list, got {type(raw).__name__}")

    rules: list[PostprocessRule] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Entry #{i} is not a mapping: {entry!r}")
        try:
            rules.append(PostprocessRule.compile(
                pattern=entry["pattern"],
                replace=entry["replace"],
                category=entry.get("category", "uncategorized"),
            ))
        except KeyError as e:
            raise ValueError(f"Entry #{i} missing required field: {e}") from e
        except re.error as e:
            raise ValueError(f"Entry #{i} invalid regex {entry['pattern']!r}: {e}") from e
    return rules


@lru_cache(maxsize=4)
def get_cached_rules(path: Path) -> tuple[PostprocessRule, ...]:
    """경로 기반 캐시. tuple로 반환해 hashable + immutable."""
    return tuple(load_postprocess_rules(path))


def apply_postprocess(
    text: str, rules: list[PostprocessRule] | tuple[PostprocessRule, ...]
) -> tuple[str, list[AppliedReplacement]]:
    out = text
    applied: list[AppliedReplacement] = []
    for rule in rules:
        new_out, n = rule._regex.subn(rule.replace, out)
        if n > 0:
            applied.append(AppliedReplacement(
                pattern=rule.pattern,
                replace=rule.replace,
                category=rule.category,
                count=n,
            ))
            out = new_out
    return out, applied
