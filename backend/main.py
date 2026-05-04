"""Voice SOAP FastAPI 진입점."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.feedback import router as feedback_router
from backend.api.formats import router as formats_router
from backend.api.note import router as note_router
from backend.api.process import router as process_router
from backend.api.transcribe import router as transcribe_router
from backend.config import get_settings
from backend.soap.formats import get_cached_format
from backend.stt.hints_loader import load_hints
from backend.stt.postprocess import get_cached_rules

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    prompt = load_hints(settings.hints_file)
    logger.info("hints loaded: %d chars from %s", len(prompt), settings.hints_file)
    rules = get_cached_rules(settings.postprocess_file)
    logger.info("postprocess rules loaded: %d from %s", len(rules), settings.postprocess_file)
    fmt = get_cached_format(settings.formats_dir, settings.default_format_id)
    logger.info(
        "default format loaded: %s (sections=%d, few_shots=%d) from %s",
        fmt.id, len(fmt.sections), len(fmt.few_shots), settings.formats_dir,
    )
    logger.info("model: %s", settings.whisper_model_repo)
    yield


app = FastAPI(title="Voice SOAP Backend", version="0.1.0", lifespan=lifespan)

# Phase 2 웹 UI(Vite dev server)에서 호출 허용. 외부 origin 추가 금지 (plan.md §7).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(transcribe_router)
app.include_router(note_router)
app.include_router(process_router)
app.include_router(feedback_router)
app.include_router(formats_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "whisper_model": settings.whisper_model_repo,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
    }
