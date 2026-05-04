"""GET /formats — 사용 가능한 포맷 목록 + 섹션 메타데이터.

프론트엔드가 포맷 선택 UI와 섹션 동적 렌더에 사용.
formats_dir의 *.yaml 파일을 자동 탐색 — 새 포맷은 yaml 추가만으로 노출됨.
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.config import Settings, get_settings
from backend.soap.formats import Section, get_cached_format

logger = logging.getLogger(__name__)
router = APIRouter()


class FormatSummary(BaseModel):
    id: str
    name: str
    sections: list[Section]


class FormatsResponse(BaseModel):
    formats: list[FormatSummary]
    default_id: str = Field(description="settings.default_format_id")


@router.get("/formats", response_model=FormatsResponse)
def list_formats(settings: Settings = Depends(get_settings)) -> FormatsResponse:
    summaries: list[FormatSummary] = []
    if not settings.formats_dir.exists():
        return FormatsResponse(formats=[], default_id=settings.default_format_id)

    for path in sorted(settings.formats_dir.glob("*.yaml")):
        fid = path.stem
        try:
            f = get_cached_format(settings.formats_dir, fid)
        except (FileNotFoundError, ValueError) as e:
            logger.warning("Skipping invalid format %s: %s", fid, e)
            continue
        summaries.append(FormatSummary(id=f.id, name=f.name, sections=f.sections))

    return FormatsResponse(formats=summaries, default_id=settings.default_format_id)
