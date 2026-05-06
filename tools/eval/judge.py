"""클라우드 judge 클라이언트 (Claude Agent SDK 통한 Max 구독 사용).

**왜 backend/가 아니라 tools/에 있나**: backend/는 환자 데이터를 다루는 런타임이라
구조 가드(tests/structural/test_no_external_network.py)가 외부 네트워크를 차단함.
이 judge는 *합성 dictation* 전용 dev-time harness이므로 tools/ 계층에 위치.
런타임 코드(FastAPI 핸들러 등)에서 이 모듈을 import하면 안 됨.

**왜 SDK인가 (직접 API 호출 대신)**: 로컬 `claude` CLI를 invoke하므로 사용자의
Max 구독 인증을 그대로 사용 → 별도 ANTHROPIC_API_KEY 불필요, 비용은 Max 한도 안에서 처리.

**PHI guard**: 모든 judge 호출은 SyntheticCase를 받아야 하며, is_synthetic=True 검증을
schema에서 강제. 이 모듈은 두 번째 방어선으로 호출 직전 case.is_synthetic 재확인.

**테스트**: backend abstraction(`JudgeBackend`)으로 SDK 호출을 격리. 테스트는
`_default_backend`를 monkeypatch하여 SDK 없이도 동작.
"""
import json
import logging
import re
import time
from typing import Awaitable, Callable

from backend.eval.cases import SyntheticCase
from backend.eval.rubric import (
    JUDGE_SYSTEM_PROMPT,
    JudgeScore,
    build_judge_user_prompt,
)
from backend.soap.formats import FormatDefinition
from backend.soap.models import ClinicalNote

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


# (system_prompt, user_prompt, model) → response text
JudgeBackend = Callable[[str, str, str], Awaitable[str]]


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


async def _default_backend(system: str, user: str, model: str) -> str:
    """기본 backend — Claude Agent SDK로 로컬 `claude` CLI invoke (Max 구독 사용).

    SDK는 단일 응답을 위해 max_turns=1로 제한. tool 사용 차단 (judge는 채점만).
    AssistantMessage의 TextBlock만 추출하여 합쳐 반환.
    """
    # local import — 테스트에서 SDK 미설치 환경 대응
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )

    options = ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        max_turns=1,
        # judge는 외부 도구를 쓰면 안 됨 (자기 의학지식 추정 차단)
        allowed_tools=[],
        # 권한 프롬프트 회피 — judge는 도구 호출이 없어야 정상
        permission_mode="bypassPermissions",
    )
    text_parts: list[str] = []
    async for message in query(prompt=user, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
    return "\n".join(text_parts)


async def judge_case(
    *,
    case: SyntheticCase,
    fmt: FormatDefinition,
    note: ClinicalNote,
    model: str = DEFAULT_JUDGE_MODEL,
    backend: JudgeBackend | None = None,
) -> tuple[JudgeScore, float]:
    """단일 케이스에 대한 judge 호출. (점수, elapsed_seconds) 반환.

    backend가 None이면 _default_backend(SDK)를 사용. 테스트에서는 fake backend 주입.

    Raises:
        PhiGuardError: 케이스가 합성 표기 안 됨.
        JudgeError: backend 호출 실패 또는 응답 파싱 실패.
    """
    _phi_guard(case)
    if backend is None:
        backend = _default_backend

    user_prompt = build_judge_user_prompt(case, fmt, note)
    start = time.perf_counter()
    try:
        content = await backend(JUDGE_SYSTEM_PROMPT, user_prompt, model)
    except Exception as e:
        raise JudgeError(f"judge backend 호출 실패: {e}") from e
    elapsed = time.perf_counter() - start

    if not content.strip():
        raise JudgeError("judge 응답이 비어있음 (Claude Code 인증 또는 모델 응답 확인 필요)")

    parsed = _extract_json(content)
    # judge가 case_id를 우리가 보낸 값으로 정확히 echo했는지 확인 (혼선 방지)
    if parsed.get("case_id") != case.id:
        parsed["case_id"] = case.id
    try:
        score = JudgeScore.model_validate(parsed)
    except Exception as e:
        raise JudgeError(f"judge 응답이 JudgeScore 스키마와 불일치: {e}; raw={content[:400]!r}") from e

    logger.info(
        "judged case=%s model=%s elapsed=%.2fs total=%d pass=%s",
        case.id, model, elapsed, score.total, score.overall_pass,
    )
    return score, elapsed
