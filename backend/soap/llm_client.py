"""LM Studio (OpenAI 호환) 호출 클라이언트."""
import json
import logging
import re
import time

import httpx

from backend.soap.models import SoapNote
from backend.soap.prompts import SYSTEM_PROMPT, build_user_prompt

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


async def structure_to_soap(
    transcript: str,
    *,
    base_url: str,
    model: str,
    timeout_seconds: float,
    temperature: float,
) -> tuple[SoapNote, float]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
    note = SoapNote(**parsed)
    logger.info(
        "soap structured: model=%s elapsed=%.2fs len_in=%d len_out=%d",
        model,
        elapsed,
        len(transcript),
        len(content),
    )
    return note, elapsed
