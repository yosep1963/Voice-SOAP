"""클라우드 judge 클라이언트 (Anthropic Messages API).

**왜 backend/가 아니라 tools/에 있나**: backend/는 환자 데이터를 다루는 런타임이라
구조 가드(tests/structural/test_no_external_network.py)가 외부 네트워크를 차단함.
이 judge는 *합성 dictation* 전용 dev-time harness이므로 tools/ 계층에 위치.
런타임 코드(FastAPI 핸들러 등)에서 이 모듈을 import하면 안 됨.

httpx 직접 호출 — 새 의존성 추가 없음. respx로 단위 테스트 가능.

**PHI guard**: 모든 judge 호출은 SyntheticCase를 받아야 하며, is_synthetic=True 검증을
schema에서 강제. 이 모듈은 그 외에도 두 번째 방어선:
- ANTHROPIC_API_KEY 미설정 시 즉시 실패 (실수로 LM Studio처럼 자동 fallback 금지)
- 호출 직전 case.is_synthetic 재확인 (defense in depth)

**비용**: 50 케이스 × 약 2K input + 500 output ≈ Sonnet 4.6 기준 케이스당 ~$0.01.
"""
import json
import os
import re
import time

import httpx

from backend.eval.cases import SyntheticCase
from backend.eval.rubric import (
    JUDGE_SYSTEM_PROMPT,
    JudgeScore,
    build_judge_user_prompt,
)
from backend.soap.formats import FormatDefinition
from backend.soap.models import ClinicalNote

DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"
DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_API_VERSION = "2023-06-01"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class JudgeError(Exception):
    pass


class PhiGuardError(JudgeError):
    """합성 데이터 외에는 클라우드 judge 호출 차단."""


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise JudgeError(f"judge가 유효한 JSON을 반환하지 않음: {e}; raw={raw[:300]!r}") from e


def _phi_guard(case: SyntheticCase) -> None:
    """schema 통과한 케이스도 호출 직전 재확인 — defense in depth."""
    if not case.is_synthetic:
        raise PhiGuardError(
            f"case {case.id!r} is not flagged synthetic — cloud judge call refused"
        )


async def judge_case(
    *,
    case: SyntheticCase,
    fmt: FormatDefinition,
    note: ClinicalNote,
    api_key: str | None = None,
    model: str = DEFAULT_JUDGE_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = 60.0,
    max_tokens: int = 1500,
) -> tuple[JudgeScore, float]:
    """단일 케이스에 대한 judge 호출. (점수, elapsed_seconds) 반환.

    Raises:
        PhiGuardError: 케이스가 합성 표기 안 됨.
        JudgeError: API 호출 실패 또는 응답 파싱 실패.
    """
    _phi_guard(case)

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise JudgeError(
            "ANTHROPIC_API_KEY 환경변수가 설정되지 않음. "
            "이 키는 합성 dictation 평가용 — 실데이터 호출에 사용 금지."
        )

    user_prompt = build_judge_user_prompt(case, fmt, note)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": JUDGE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": key,
        "anthropic-version": DEFAULT_API_VERSION,
        "content-type": "application/json",
    }

    url = f"{base_url.rstrip('/')}/messages"
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise JudgeError(f"judge API 호출 실패 ({url}): {e}") from e

    elapsed = time.perf_counter() - start
    if r.status_code != 200:
        raise JudgeError(f"judge API HTTP {r.status_code}: {r.text[:300]}")

    body = r.json()
    try:
        # Anthropic Messages API: content는 list of blocks
        blocks = body["content"]
        text_blocks = [b["text"] for b in blocks if b.get("type") == "text"]
        if not text_blocks:
            raise JudgeError(f"judge 응답에 text block 없음: {body}")
        content = "\n".join(text_blocks)
    except (KeyError, IndexError, TypeError) as e:
        raise JudgeError(f"예상치 못한 judge 응답 구조: {body}") from e

    parsed = _extract_json(content)
    # judge가 case_id를 우리가 보낸 값으로 정확히 echo했는지 확인 (혼선 방지)
    if parsed.get("case_id") != case.id:
        # 정정 후 진행 — judge가 잘못 채웠어도 채점 자체는 유효할 수 있음
        parsed["case_id"] = case.id
    try:
        score = JudgeScore.model_validate(parsed)
    except Exception as e:
        raise JudgeError(f"judge 응답이 JudgeScore 스키마와 불일치: {e}; raw={content[:400]!r}") from e

    return score, elapsed
