"""POST /feedback — 사용자 편집 diff 학습 로그.

plan.md §5 Phase 5 §"학습/개선 시스템" 시작점.
사용자가 SOAP를 EMR에 복사하는 시점에 자동 호출되어, 모든 텍스트 필드에
환자 식별자 마스킹 적용 후 JSONL로 추가 기록.
"""
import logging

from fastapi import APIRouter, Depends

from backend.config import Settings, get_settings
from backend.feedback.models import EditFeedback, SectionDiff
from backend.feedback.storage import append_feedback
from backend.privacy.masking import mask_identifiers
from backend.soap.models import SoapNote

logger = logging.getLogger(__name__)
router = APIRouter()


def _mask_note(note: SoapNote) -> SoapNote:
    return SoapNote(
        subjective=mask_identifiers(note.subjective),
        objective=mask_identifiers(note.objective),
        assessment=mask_identifiers(note.assessment),
        plan=mask_identifiers(note.plan),
        uncertain_segments=[mask_identifiers(u) for u in note.uncertain_segments],
    )


def _mask_diffs(diffs: list[SectionDiff]) -> list[SectionDiff]:
    return [
        SectionDiff(
            section=d.section,
            original=mask_identifiers(d.original),
            edited=mask_identifiers(d.edited),
            changed=d.changed,
        )
        for d in diffs
    ]


def _apply_masking(fb: EditFeedback) -> EditFeedback:
    return fb.model_copy(update={
        "raw_text": mask_identifiers(fb.raw_text),
        "corrected_text": mask_identifiers(fb.corrected_text),
        "original_note": _mask_note(fb.original_note),
        "edited_note": _mask_note(fb.edited_note),
        "diffs": _mask_diffs(fb.diffs),
        "uncertain_segments": [mask_identifiers(u) for u in fb.uncertain_segments],
    })


@router.post("/feedback")
async def feedback(
    payload: EditFeedback,
    settings: Settings = Depends(get_settings),
) -> dict:
    masked = _apply_masking(payload)
    append_feedback(settings.feedback_log_path, masked)
    changed_count = sum(1 for d in masked.diffs if d.changed)
    logger.info("feedback logged: %d/%d sections edited", changed_count, len(masked.diffs))
    return {"status": "ok", "edited_sections": changed_count}
