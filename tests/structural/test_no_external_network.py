"""구조 테스트: backend 코드는 외부 네트워크를 절대 호출하지 않는다.

CLAUDE.md §"보안 표면" 의 첫 번째 항목 — *외부 네트워크 호출을 절대 금지*.
의료법/PIPA 제약 때문에 환자 데이터가 어떤 형태로든 외부로 나가서는 안 된다.

이 테스트는 다음을 정적 검사한다:
    1. backend/ 안의 모든 .py 파일에서 http(s):// 리터럴을 추출
    2. localhost / 127.0.0.1 이 아닌 호스트가 등장하면 fail
    3. 호스트 판정이 어려운 경우(예: f-string으로 host 변수 주입) 도 의심으로 fail

문서 한 줄("외부 네트워크 금지")보다 강한 *기계적* 가드.

새 외부 호출이 *정당한* 경우(예: localhost가 아닌 사내 네트워크 LM 서버)
는 ALLOWED_HOSTS 에 명시적으로 추가해야 한다 — 코드 리뷰 단계에서 의도가
드러나는 것이 목적.
"""
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

# 명시적 허용 호스트. 추가 시 *반드시* 사유를 주석으로 남길 것.
ALLOWED_HOSTS = {
    "localhost",       # LM Studio (config.llm_base_url 기본값) + Vite dev server (CORS)
    "127.0.0.1",       # FastAPI 바인딩 + Vite dev server alias
}

# http(s)://host[:port][/path] 에서 host 부분만 캡처
_URL_RE = re.compile(r'https?://([A-Za-z0-9_.\-{}\[\]]+)')


def _scan_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _extract_url_hosts(source: str) -> list[str]:
    """파이썬 소스에서 등장하는 모든 http(s):// 호스트 후보를 추출."""
    return _URL_RE.findall(source)


def test_no_external_network_calls_in_backend() -> None:
    files = _scan_python_files(BACKEND_DIR)
    assert files, f"backend/ 디렉터리에서 .py 파일을 못 찾음: {BACKEND_DIR}"

    violations: list[tuple[Path, str]] = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        for host in _extract_url_hosts(src):
            if host not in ALLOWED_HOSTS:
                violations.append((path.relative_to(REPO_ROOT), host))

    if violations:
        msg = "\n".join(f"  {p}: http(s)://{h}" for p, h in violations)
        pytest.fail(
            "backend/ 코드에서 외부 네트워크 URL이 발견됨 (의료법/PIPA 위반 위험):\n"
            f"{msg}\n\n"
            f"허용된 호스트: {sorted(ALLOWED_HOSTS)}\n"
            "정당한 경우라면 ALLOWED_HOSTS 에 사유와 함께 추가하세요."
        )


def test_no_external_http_libraries_imported_outside_llm_client() -> None:
    """httpx/requests/aiohttp 등 HTTP 클라이언트는 backend/soap/llm_client.py 에서만 사용한다.

    CORS origin 등으로 'http://' 문자열이 등장할 수 있는 config.py 는 *사용*이
    아니라 *설정*이므로 별개. 외부로 실제 데이터를 보내는 호출 지점을 *한 곳*에
    묶어 감사하기 쉽게 만든다.
    """
    forbidden_imports = re.compile(
        r'^\s*(?:from\s+(httpx|requests|urllib|aiohttp|http\.client|urllib3)|'
        r'import\s+(httpx|requests|urllib|aiohttp|http\.client|urllib3))',
        re.MULTILINE,
    )
    allowed_paths = {
        BACKEND_DIR / "soap" / "llm_client.py",  # LM Studio 호출 (localhost only)
    }

    violations: list[tuple[Path, str]] = []
    for path in _scan_python_files(BACKEND_DIR):
        if path in allowed_paths:
            continue
        src = path.read_text(encoding="utf-8")
        for match in forbidden_imports.finditer(src):
            module = match.group(1) or match.group(2)
            violations.append((path.relative_to(REPO_ROOT), module))

    if violations:
        msg = "\n".join(f"  {p}: imports {m}" for p, m in violations)
        pytest.fail(
            "HTTP 클라이언트 라이브러리는 backend/soap/llm_client.py 에서만 사용해야 함.\n"
            "(외부 통신 지점을 한 곳에 모아 감사 용이성 확보):\n"
            f"{msg}"
        )


def test_allowed_hosts_are_loopback_only() -> None:
    """ALLOWED_HOSTS 가 실수로 외부 호스트로 늘어나는 것을 방지하는 메타 가드."""
    loopback_only = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    extra = ALLOWED_HOSTS - loopback_only
    assert not extra, (
        f"ALLOWED_HOSTS에 loopback이 아닌 호스트가 포함됨: {extra}. "
        "외부 호스트 허용 시 의료법/PIPA 영향 평가 후 이 메타 가드를 명시적으로 수정해야 함."
    )
