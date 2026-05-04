"""LM Studio (OpenAI 호환) 호출 클라이언트.

`structure_to_note`가 정식 진입점 — 어떤 포맷이든 ClinicalNote(sections dict)를 반환.
`structure_to_soap`는 SoapNote 4섹션 후방호환 wrapper (기존 /soap 엔드포인트가 사용).
"""
import json
import logging
import re
import time

import httpx

from backend.soap.formats import FormatDefinition
from backend.soap.models import ClinicalNote, SoapNote
from backend.soap.prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)

# LLM이 가끔 ```json ... ``` 으로 감싸는 경우를 위한 패턴
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(Exception):
    pass


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM이 유효한 JSON을 반환하지 않음: {e}; raw={raw[:200]!r}") from e


async def structure_to_note(
    transcript: str,
    *,
    fmt: FormatDefinition,
    base_url: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
) -> tuple[ClinicalNote, float]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": build_system_prompt(fmt)},
            {"role": "user", "content": build_user_prompt(transcript)},
        ],
        "temperature": temperature,
        "max_tokens": 500,
        "stream": False,
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            r = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise LLMError(f"LM Studio 호출 실패 ({url}): {e}") from e

    elapsed = time.perf_counter() - start
    if r.status_code != 200:
        raise LLMError(f"LM Studio HTTP {r.status_code}: {r.text[:300]}")

    body = r.json()
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"예상치 못한 LLM 응답 구조: {body}") from e

    parsed = _extract_json(content)
    sections = {s.key: str(parsed.get(s.key, "")) for s in fmt.sections}
    uncertain_raw = parsed.get("uncertain_segments", []) or []
    uncertain = [str(x) for x in uncertain_raw if isinstance(x, str)]

    logger.info(
        "note structured: format=%s model=%s elapsed=%.2fs len_in=%d len_out=%d",
        fmt.id,
        model,
        elapsed,
        len(transcript),
        len(content),
    )
    return ClinicalNote(sections=sections, uncertain_segments=uncertain), elapsed


async def structure_to_soap(
    transcript: str,
    *,
    fmt: FormatDefinition,
    base_url: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
) -> tuple[SoapNote, float]:
    """후방호환 wrapper. 4섹션(SOAP) 형태로 변환해 반환."""
    note, elapsed = await structure_to_note(
        transcript,
        fmt=fmt,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        temperature=temperature,
    )
    return _to_soap_note(note), elapsed


def _to_soap_note(note: ClinicalNote) -> SoapNote:
    return SoapNote(
        subjective=note.sections.get("subjective", ""),
        objective=note.sections.get("objective", ""),
        assessment=note.sections.get("assessment", ""),
        plan=note.sections.get("plan", ""),
        uncertain_segments=note.uncertain_segments,
    )
