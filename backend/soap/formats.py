"""포맷 정의 로더. 외래 dictation 분류 포맷을 yaml에서 읽어 LLM 프롬프트로 빌드.

각 포맷(soap, initial_visit, ...)은 hints/formats/<id>.yaml에 정의됨.
- sections: 섹션 키/라벨/정의 (UI + 시스템 프롬프트 양쪽에서 사용)
- strict_rules: 시스템 프롬프트의 "엄격한 규칙" 항목
- few_shots: LLM 학습용 예시 (입력 dictation + 정답 JSON)
"""
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class Section(BaseModel):
    key: str
    label: str
    short: str = ""
    definition: str


class FewShot(BaseModel):
    label: str
    input: str
    output: dict[str, Any]


class FormatDefinition(BaseModel):
    id: str
    name: str
    intro: str
    sections: list[Section] = Field(min_length=1)
    strict_rules: list[str] = Field(min_length=1)
    few_shots: list[FewShot] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_few_shot_keys(self) -> "FormatDefinition":
        section_keys = {s.key for s in self.sections}
        allowed = section_keys | {"uncertain_segments"}
        for i, shot in enumerate(self.few_shots):
            shot_keys = set(shot.output.keys())
            unknown = shot_keys - allowed
            if unknown:
                raise ValueError(
                    f"Format {self.id!r} few_shot #{i} has unknown keys: {unknown}. "
                    f"Allowed: {allowed}"
                )
            missing = section_keys - shot_keys
            if missing:
                raise ValueError(
                    f"Format {self.id!r} few_shot #{i} missing section keys: {missing}"
                )
        return self


def load_format(formats_dir: Path, format_id: str) -> FormatDefinition:
    """단일 포맷 yaml을 로드. 파일 없으면 FileNotFoundError."""
    path = formats_dir / f"{format_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Format file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Format file must be a YAML mapping, got {type(raw).__name__}")
    if raw.get("id") != format_id:
        raise ValueError(
            f"Format id mismatch: yaml has {raw.get('id')!r}, expected {format_id!r}"
        )
    return FormatDefinition(**raw)


@lru_cache(maxsize=8)
def get_cached_format(formats_dir: Path, format_id: str) -> FormatDefinition:
    """경로+id 키로 lru_cache. 서버 startup 후엔 yaml 변경 반영 안 됨 — 재시작 필요."""
    return load_format(formats_dir, format_id)
