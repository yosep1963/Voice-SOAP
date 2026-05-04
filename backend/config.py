"""런타임 설정. 환경변수로 override 가능."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOICE_SOAP_", env_file=".env", extra="ignore")

    whisper_model_repo: str = "mlx-community/whisper-large-v3-mlx"
    hints_file: Path = Path("hints/medical_hints.txt")
    postprocess_file: Path = Path("hints/postprocess.yaml")
    formats_dir: Path = Path("hints/formats")
    default_format_id: str = "soap"
    host: str = "127.0.0.1"
    port: int = 8080
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, description="50MB cap on uploaded wav")

    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "gemma-3-12b-it-qat"
    llm_timeout_seconds: float = 120.0
    llm_temperature: float = 0.1

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Phase 2 웹 UI(Vite dev server)만 허용. 외부 origin 추가 금지.",
    )

    feedback_log_path: Path = Field(
        default=Path("logs/edits.jsonl"),
        description="사용자 편집 diff 학습 로그 (마스킹 후 JSONL 추가). plan.md Phase 5.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
