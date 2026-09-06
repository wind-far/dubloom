from __future__ import annotations

import logging
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, SecretStr

from . import auth, database, review, runtime_security, worker
from .adapters.local_subtitles import parse_srt, uploaded_subtitle_dir
from .adapters.local_video import remove_upload, uploaded_video_dir
from .adapters.openai_client import validate_openai_base_url
from .adapters.openai_translate import list_models as list_openai_models
from .config import WORKFOLDER, YOUTUBE_COOKIE_PATH, ensure_runtime_dirs
from .pipeline import run_task
from .runtime_checks import validate_runtime_device
from .sanitize import sanitize_text
from .sources import detect_source
from .stage_reset import remove_stage_artifacts
from .stages import STAGE_NAMES
from .youtube import LOCAL_UPLOAD_DIRECTIONS, is_local_upload_url, validate_video_url

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".wmv"}
ALLOWED_SUBTITLE_SUFFIXES = {".srt"}
LOCAL_UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_LOCAL_UPLOAD_BYTES = int(os.getenv("LOCAL_UPLOAD_MAX_BYTES", str(4 * 1024 * 1024 * 1024)))
MAX_LOCAL_SUBTITLE_BYTES = int(os.getenv("LOCAL_SUBTITLE_MAX_BYTES", str(20 * 1024 * 1024)))

logger = logging.getLogger(__name__)

TaskListStatus = Literal[
    "all", "queued", "running", "awaiting_review", "paused", "succeeded", "failed"
]
TaskListExecutionMode = Literal["all", "auto", "manual"]
TaskListSort = Literal[
    "created_desc",
    "created_asc",
    "started_desc",
    "started_asc",
    "completed_desc",
    "completed_asc",
    "status_asc",
    "status_desc",
    "title_asc",
    "title_desc",
]


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "********"


class TaskCreate(BaseModel):
    url: str
    execution_mode: str = "auto"
    output_mode: str = "both"
    review_mode: str = "none"
    translation_profile_id: str | None = None
    tts_profile_id: str | None = None


class SegmentUpdate(BaseModel):
    expected_revision: int
    translated_text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    audio_mode: Literal["tts", "original"] | None = None
    tts_profile_id: str | None = None


class ProviderProfileCreate(BaseModel):
    kind: Literal["translation", "tts"]
    name: str
    provider: str
    model: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)


class ProviderProfileUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None
    clear_secrets: bool = False


class ContinueTaskRequest(BaseModel):
    execution_mode: str | None = None


class YouTubeCookieUpdate(BaseModel):
    content: str


class OpenAISettingsUpdate(BaseModel):
    base_url: str
    api_key: str = ""
    clear_api_key: bool = False
    model: str
    translate_concurrency: str = ""


class OpenAIModelsRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""


class YtdlpSettingsUpdate(BaseModel):
    proxy_port: str = ""


class LoginRequest(BaseModel):
    password: SecretStr


def normalize_proxy_port(value: str) -> str:
    proxy_port = value.strip()
    if not proxy_port:
        return ""
    if not proxy_port.isdigit():
        raise HTTPException(status_code=422, detail="Proxy port must be numeric.")
    port = int(proxy_port)
    if port < 1 or port > 65535:
        raise HTTPException(status_code=422, detail="Proxy port must be between 1 and 65535.")
    return str(port)


def normalize_translate_concurrency(value: str) -> str:
    concurrency = value.strip()
    if not concurrency:
        return ""
    if not all("0" <= char <= "9" for char in concurrency):
        raise HTTPException(status_code=422, detail="Translate concurrency must be numeric.")
    workers = int(concurrency)
    if workers < 1 or workers > 200:
        raise HTTPException(
            status_code=422, detail="Translate concurrency must be between 1 and 200."
        )
    return concurrency


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_dirs()
    auth.validate_auth_configuration()
    database.init_db()
    database.delete_expired_auth_sessions(database.now_iso())
    database.backfill_titles_from_metadata()
    database.fail_stale_active_tasks()
    worker.register_handler("segment_preview", review.run_segment_preview)
    worker.register_handler("dirty_render", review.run_dirty_render)
    worker.start(run_task)
    yield


app = FastAPI(
    title="Dubloom API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def redact_login_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    if request.url.path == "/api/auth/login":
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials."},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, exc)


DEFAULT_CORS_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|"
    r"127\.0\.0\.1|"
    r"\[::1\]"
    r"):3000$"
)


def cors_origins() -> list[str]:
    defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
    configured = os.getenv("CORS_ALLOW_ORIGINS", "")
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if "*" in extra:
        raise RuntimeError("CORS_ALLOW_ORIGINS cannot contain '*' when credentials are enabled.")
    return [*defaults, *extra]


def cors_origin_regex() -> str:
    configured = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip()
    return configured or DEFAULT_CORS_ORIGIN_REGEX


_cors_origins = cors_origins()
_cors_origin_regex = cors_origin_regex()

app.add_middleware(
    auth.AuthMiddleware,
    allowed_origins=_cors_origins,
    allowed_origin_regex=_cors_origin_regex,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _clear_replaced_login_cookie(
    response: Response,
    old_token: str,
    settings: auth.AuthSettings | None = None,
) -> None:
    if not old_token:
        return
    if settings is not None:
        auth.clear_session_cookie(response, settings)
        return
    response.delete_cookie(
        key=auth.SESSION_COOKIE_NAME,
        path=auth.SESSION_COOKIE_PATH,
        httponly=True,
    )


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    old_token = request.cookies.get(auth.SESSION_COOKIE_NAME, "")
    auth.revoke_session_token(old_token)
    client_host = request.client.host if request.client else "unknown"

    try:
        settings = auth.validate_auth_configuration()
    except auth.AuthConfigurationError:
        response = JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured."},
            headers={"Cache-Control": "no-store"},
        )
        _clear_replaced_login_cookie(response, old_token)
        return response

    rate_limit = auth.reserve_login_attempt(client_host)
    if not rate_limit.allowed:
        response = JSONResponse(
            status_code=429,
            content={"detail": "Too many login attempts."},
            headers={
                "Cache-Control": "no-store",
                "Retry-After": str(rate_limit.retry_after_seconds),
            },
        )
        _clear_replaced_login_cookie(response, old_token, settings)
        return response

    try:
        password_matches = auth.verify_password(
            payload.password.get_secret_value(), settings
        )
    except auth.AuthConfigurationError:
        auth.clear_login_attempts(client_host)
        response = JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured."},
            headers={"Cache-Control": "no-store"},
        )
        _clear_replaced_login_cookie(response, old_token, settings)
        return response

    if not password_matches:
        response = JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials."},
            headers={"Cache-Control": "no-store"},
        )
        _clear_replaced_login_cookie(response, old_token, settings)
        return response

    auth.clear_login_attempts(client_host)
    token, session = auth.create_session(settings)
    response = JSONResponse(
        content={
            "authenticated": True,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        },
        headers={"Cache-Control": "no-store"},
    )
    auth.set_session_cookie(response, token, settings, session.expires_at)
    return response


@app.get("/api/auth/session")
def auth_session(request: Request) -> JSONResponse:
    session: auth.AuthenticatedSession = request.state.auth_session
    return JSONResponse(
        content={
            "authenticated": True,
            "csrf_token": session.csrf_token,
            "expires_at": session.expires_at,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    session: auth.AuthenticatedSession = request.state.auth_session
    settings: auth.AuthSettings = request.state.auth_settings
    database.delete_auth_session(session.token_hash)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    auth.clear_session_cookie(response, settings)
    return response


def _ensure_runtime_ready() -> None:
    try:
        validate_runtime_device()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def normalize_execution_mode(value: str) -> str:
    try:
        return database.normalize_execution_mode(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def normalize_output_mode(value: str) -> str:
    try:
        return database.normalize_output_mode(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def normalize_review_mode(value: str) -> str:
    try:
        return database.normalize_review_mode(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _profile(profile_id: str | None, kind: str) -> dict[str, Any] | None:
    if profile_id is None:
        return None
    profile = database.get_provider_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail=f"{kind.title()} profile not found.")
    if profile["kind"] != kind:
        raise HTTPException(status_code=422, detail=f"Profile {profile_id} is not a {kind} profile.")
    return profile


def _task_config_snapshot(
    translation_profile_id: str | None,
    tts_profile_id: str | None,
) -> dict[str, Any]:
    translation = _profile(translation_profile_id, "translation")
    tts = _profile(tts_profile_id, "tts")
    openai = database.get_openai_settings()
    return {
        "translation": (
            {
                "provider": translation["provider"],
                "model": translation["model"],
                "config": translation["config"],
            }
            if translation
            else {
                "provider": "openai-compatible",
                "model": openai["model"],
                "config": {
                    "base_url": openai["base_url"],
                    "translate_concurrency": openai["translate_concurrency"],
                },
            }
        ),
        "tts": (
            {"provider": tts["provider"], "model": tts["model"], "config": tts["config"]}
            if tts
            else {"provider": "voxcpm2", "model": "OpenBMB/VoxCPM2", "config": {}}
        ),
    }


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskCreate) -> dict:
    try:
        validated_url = validate_video_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_execution_mode = normalize_execution_mode(payload.execution_mode)
    normalized_output_mode = normalize_output_mode(payload.output_mode)
    normalized_review_mode = normalize_review_mode(payload.review_mode)
    config_snapshot = _task_config_snapshot(
        payload.translation_profile_id, payload.tts_profile_id
    )

    if (
        normalized_review_mode == database.DEFAULT_REVIEW_MODE
        and payload.translation_profile_id is None
        and payload.tts_profile_id is None
    ):
        # Keep the legacy two-argument call for backwards compatibility with
        # integrations that wrap this helper.
        existing_id = database.find_task_by_video_id(
            validated_url.video_id,
            normalized_output_mode,
        )
    else:
        existing_id = database.find_task_by_video_id(
            validated_url.video_id,
            normalized_output_mode,
            review_mode=normalized_review_mode,
            translation_profile_id=payload.translation_profile_id,
            tts_profile_id=payload.tts_profile_id,
        )
    if existing_id:
        existing_task = database.get_task(existing_id)
        if existing_task is not None:
            return existing_task

    _ensure_runtime_ready()
    task_id, created = database.create_or_get_video_task(
        validated_url.url,
        validated_url.video_id,
        execution_mode=normalized_execution_mode,
        output_mode=normalized_output_mode,
        review_mode=normalized_review_mode,
        translation_profile_id=payload.translation_profile_id,
        tts_profile_id=payload.tts_profile_id,
        config_snapshot=config_snapshot,
    )
    task = database.get_task(task_id)
    if task is None:
        raise RuntimeError(f"Task {task_id} was not persisted.")
    if created:
        worker.enqueue(task_id)
    return task


def _clean_upload_filename(filename: str | None) -> str:
    original = Path(filename or "").name.strip()
    if not original:
        raise HTTPException(status_code=422, detail="Video filename is required.")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(status_code=422, detail="Unsupported video file type.")
    safe_stem = sanitize_text(Path(original).stem) or "video"
    return f"{safe_stem}{suffix}"


def _clean_subtitle_filename(filename: str | None) -> str:
    original = Path(filename or "").name.strip()
    if not original:
        raise HTTPException(status_code=422, detail="Subtitle filename is required.")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUBTITLE_SUFFIXES:
        raise HTTPException(status_code=422, detail="Only .srt subtitle files are supported.")
    safe_stem = sanitize_text(Path(original).stem) or "subtitles"
    return f"{safe_stem}{suffix}"


def _save_uploaded_file(file: UploadFile, destination: Path, *, max_bytes: int, too_large_detail: str) -> int:
    total = 0
    created = False
    try:
        with runtime_security.open_private_binary_exclusive(destination) as handle:
            created = True
            while True:
                chunk = file.file.read(LOCAL_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=too_large_detail)
                handle.write(chunk)
    except Exception:
        if created:
            runtime_security.remove_private_file(destination, missing_ok=True)
        raise
    if total == 0:
        runtime_security.remove_private_file(destination, missing_ok=True)
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    return total


def _validate_uploaded_srt(path: Path) -> None:
    try:
        parse_srt(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid SRT subtitle file encoding.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid SRT subtitle file: {exc}") from exc


def _rollback_local_upload(task_id: str) -> None:
    try:
        remove_upload(WORKFOLDER, task_id)
    except Exception:
        logger.exception("Failed to remove local upload files for task %s", task_id)
    try:
        database.delete_task(task_id)
    except Exception:
        logger.exception("Failed to remove local upload database record for task %s", task_id)


@app.post("/api/tasks/upload", status_code=201)
def upload_local_video(
    direction: str = Form("en-zh"),
    file: UploadFile = File(...),
    subtitle_file: UploadFile | None = File(None),
    execution_mode: str = Form("auto"),
    output_mode: str = Form("both"),
    review_mode: str = Form("none"),
    translation_profile_id: str | None = Form(None),
    tts_profile_id: str | None = Form(None),
) -> dict:
    if direction not in LOCAL_UPLOAD_DIRECTIONS:
        raise HTTPException(status_code=422, detail="Unsupported local video direction.")

    original_name = Path(file.filename or "").name.strip()
    stored_name = _clean_upload_filename(original_name)
    stored_subtitle_name = None
    if subtitle_file is not None:
        stored_subtitle_name = _clean_subtitle_filename(subtitle_file.filename)
    normalized_execution_mode = normalize_execution_mode(execution_mode)
    normalized_output_mode = normalize_output_mode(output_mode)
    normalized_review_mode = normalize_review_mode(review_mode)
    config_snapshot = _task_config_snapshot(translation_profile_id, tts_profile_id)
    _ensure_runtime_ready()

    task_id = str(uuid.uuid4())
    try:
        _save_uploaded_file(
            file,
            uploaded_video_dir(WORKFOLDER, task_id) / stored_name,
            max_bytes=MAX_LOCAL_UPLOAD_BYTES,
            too_large_detail="Uploaded video is too large.",
        )
        if subtitle_file is not None and stored_subtitle_name is not None:
            subtitle_path = uploaded_subtitle_dir(WORKFOLDER, task_id) / stored_subtitle_name
            _save_uploaded_file(
                subtitle_file,
                subtitle_path,
                max_bytes=MAX_LOCAL_SUBTITLE_BYTES,
                too_large_detail="Uploaded subtitle is too large.",
            )
            _validate_uploaded_srt(subtitle_path)

        url = f"local://upload/{task_id}?direction={direction}&filename={quote(original_name)}"
        database.create_task(
            url,
            task_id=task_id,
            execution_mode=normalized_execution_mode,
            output_mode=normalized_output_mode,
            review_mode=normalized_review_mode,
            translation_profile_id=translation_profile_id,
            tts_profile_id=tts_profile_id,
            config_snapshot=config_snapshot,
        )
        database.update_task(task_id, title=Path(original_name).stem)
        task = database.get_task(task_id)
        if task is None:
            raise RuntimeError(f"Local upload task {task_id} was not persisted.")
        worker.enqueue(task_id)
        return task
    except Exception:
        _rollback_local_upload(task_id)
        raise


@app.get("/api/tasks/current")
def current_task() -> dict | None:
    return database.get_current_task()


@app.get("/api/tasks")
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = Query("", max_length=200),
    status: TaskListStatus = "all",
    execution_mode: TaskListExecutionMode = "all",
    sort: TaskListSort = "created_desc",
) -> dict:
    return database.list_tasks_page(
        page=page,
        page_size=page_size,
        query=q,
        status=status,
        execution_mode=execution_mode,
        sort=sort,
    )


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/api/tasks/{task_id}/segments")
def task_segments(task_id: str) -> dict[str, Any]:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        segments = review.segments_with_warnings(task_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "segments": segments,
        "task": {
            "id": task["id"],
            "status": task["status"],
            "review_mode": task.get("review_mode") or database.DEFAULT_REVIEW_MODE,
            "review_approved_at": task.get("review_approved_at"),
            "result_stale": bool(task.get("result_stale")),
        },
    }


@app.patch("/api/tasks/{task_id}/segments/{segment_id}")
def update_task_segment(task_id: str, segment_id: str, payload: SegmentUpdate) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Cannot edit segments while the task is active.")
    fields = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    translated = fields.get("translated_text")
    if translated is not None and not translated.strip():
        raise HTTPException(status_code=422, detail="translated_text must be non-empty.")
    speaker = fields.get("speaker")
    if speaker is not None and not speaker.strip():
        raise HTTPException(status_code=422, detail="speaker must be non-empty.")
    if "tts_profile_id" in fields and fields["tts_profile_id"] is not None:
        _profile(fields["tts_profile_id"], "tts")
    try:
        segment = database.update_task_segment(
            task_id,
            segment_id,
            payload.expected_revision,
            **fields,
        )
    except database.SegmentRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    if not task.get("final_video_path"):
        database.update_task(task_id, result_stale=0)
    return dict(segment, warnings=review.segment_warnings(segment))


@app.post("/api/tasks/{task_id}/segments/{segment_id}/preview", status_code=202)
def create_segment_preview(task_id: str, segment_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    segment = database.get_task_segment(task_id, segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    if task["status"] in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Cannot preview while the task is active.")
    if segment["audio_mode"] == "tts" and not str(segment["translated_text"]).strip():
        raise HTTPException(status_code=422, detail="translated_text must be non-empty for TTS.")
    database.set_segment_preview(task_id, segment_id, "queued")
    job_id = worker.enqueue_job(
        task_id,
        "segment_preview",
        {"segment_id": segment_id},
    )
    job = database.get_job(job_id)
    if job is None:
        raise RuntimeError(f"Job {job_id} was not persisted.")
    return job


@app.get("/api/tasks/{task_id}/segments/{segment_id}/audio")
def segment_audio(
    task_id: str,
    segment_id: str,
    kind: Literal["source", "preview"] = "source",
) -> FileResponse:
    try:
        path = review.safe_segment_audio(task_id, segment_id, kind)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/tasks/{task_id}/review/approve", status_code=202)
def approve_task_review(task_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] != "awaiting_review":
        raise HTTPException(status_code=409, detail="Task is not awaiting review.")
    try:
        review.export_segments(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _ensure_runtime_ready()
    approved_at = database.now_iso()
    database.update_task(
        task_id,
        status="queued",
        current_stage="split_audio",
        review_approved_at=approved_at,
        result_stale=0,
        error_message=None,
        completed_at=None,
    )
    job_id = worker.enqueue_job(task_id, "pipeline")
    result = database.get_task(task_id) or {}
    result["job_id"] = job_id
    return result


@app.post("/api/tasks/{task_id}/render-dirty", status_code=202)
def render_dirty_segments(task_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] in {"queued", "running", "awaiting_review"}:
        raise HTTPException(status_code=409, detail="Task is not ready for a dirty render.")
    if not database.list_task_segments(task_id, dirty_only=True) and not task.get("result_stale"):
        raise HTTPException(status_code=409, detail="No segment changes need rendering.")
    try:
        review.export_segments(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _ensure_runtime_ready()
    database.update_task(
        task_id,
        status="queued",
        current_stage="tts" if task.get("output_mode") != "subtitles" else "merge_video",
        error_message=None,
        completed_at=None,
    )
    job_id = worker.enqueue_job(task_id, "dirty_render")
    job = database.get_job(job_id)
    if job is None:
        raise RuntimeError(f"Job {job_id} was not persisted.")
    return job


@app.get("/api/tasks/{task_id}/artifact/source-video")
def source_video(task_id: str) -> FileResponse:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    session_path = str(task.get("session_path") or "").strip()
    if not session_path:
        raise HTTPException(status_code=404, detail="Source video is not available.")
    session = Path(session_path).resolve()
    path = (session / "media" / "video_source.mp4").resolve()
    if not _is_inside_workfolder(session):
        raise HTTPException(status_code=409, detail="Task session is outside the workfolder.")
    try:
        path.relative_to(session)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Invalid source video path.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Source video is not available.")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _validate_provider_name(kind: str, provider: str) -> None:
    from .providers import get_translation_provider, get_tts_provider

    try:
        (get_translation_provider if kind == "translation" else get_tts_provider)(provider)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/provider-profiles")
def provider_profiles(kind: Literal["translation", "tts"] | None = None) -> list[dict]:
    return database.list_provider_profiles(kind)


@app.post("/api/provider-profiles", status_code=201)
def create_provider_profile(payload: ProviderProfileCreate) -> dict:
    _validate_provider_name(payload.kind, payload.provider)
    try:
        profile_id = database.create_provider_profile(
            payload.kind,
            payload.name,
            payload.provider,
            payload.model,
            payload.config,
            payload.secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = database.get_provider_profile(profile_id)
    assert profile is not None
    return profile


@app.get("/api/provider-profiles/{profile_id}")
def provider_profile_detail(profile_id: str) -> dict:
    profile = database.get_provider_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Provider profile not found.")
    return profile


@app.patch("/api/provider-profiles/{profile_id}")
def update_provider_profile(profile_id: str, payload: ProviderProfileUpdate) -> dict:
    current = database.get_provider_profile(profile_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Provider profile not found.")
    if payload.provider is not None:
        _validate_provider_name(current["kind"], payload.provider)
    try:
        updated = database.update_provider_profile(
            profile_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Provider profile not found.")
    profile = database.get_provider_profile(profile_id)
    assert profile is not None
    return profile


@app.delete("/api/provider-profiles/{profile_id}", status_code=204)
def delete_provider_profile(profile_id: str) -> Response:
    if not database.delete_provider_profile(profile_id):
        raise HTTPException(status_code=404, detail="Provider profile not found.")
    return Response(status_code=204)


def _is_inside_workfolder(path: Path) -> bool:
    workfolder = WORKFOLDER.resolve()
    try:
        path.resolve().relative_to(workfolder)
    except ValueError:
        return False
    return True


def _purge_task(task: dict) -> None:
    session_path = task.get("session_path")
    if session_path:
        session_dir = Path(session_path)
        if session_dir.exists() and _is_inside_workfolder(session_dir):
            shutil.rmtree(session_dir)
    log_file = database.log_path(task["id"])
    if log_file.exists():
        log_file.unlink()
    database.delete_task(task["id"])


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str) -> Response:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] == "running":
        raise HTTPException(status_code=409, detail="Cannot delete a running task.")
    _purge_task(task)
    if is_local_upload_url(task["url"]):
        remove_upload(WORKFOLDER, task["id"])
    return Response(status_code=204)


@app.post("/api/tasks/{task_id}/rerun")
def rerun_task(task_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] == "running":
        raise HTTPException(status_code=409, detail="Cannot rerun a running task.")

    _ensure_runtime_ready()
    url = task["url"]
    execution_mode = task.get("execution_mode") or database.DEFAULT_EXECUTION_MODE
    output_mode = task.get("output_mode") or database.DEFAULT_OUTPUT_MODE
    review_mode = task.get("review_mode") or database.DEFAULT_REVIEW_MODE
    translation_profile_id = task.get("translation_profile_id")
    tts_profile_id = task.get("tts_profile_id")
    try:
        config_snapshot = json.loads(task.get("config_snapshot") or "{}")
    except (json.JSONDecodeError, TypeError):
        config_snapshot = {}
    _purge_task(task)
    new_id = database.create_task(
        url,
        task_id=task_id,
        execution_mode=execution_mode,
        output_mode=output_mode,
        review_mode=review_mode,
        translation_profile_id=translation_profile_id,
        tts_profile_id=tts_profile_id,
        config_snapshot=config_snapshot,
    )
    worker.enqueue(new_id)
    return database.get_task(new_id)


@app.post("/api/tasks/{task_id}/stages/{stage_name}/redo")
def redo_stage(task_id: str, stage_name: str) -> dict:
    if stage_name not in STAGE_NAMES:
        raise HTTPException(status_code=404, detail="Stage not found.")
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if (task.get("execution_mode") or database.DEFAULT_EXECUTION_MODE) != "manual":
        raise HTTPException(status_code=409, detail="Only manual tasks support per-stage redo.")
    if task["status"] in {"running", "queued"}:
        raise HTTPException(status_code=409, detail="Task is already running or queued.")
    stage = next((item for item in task["stages"] if item["name"] == stage_name), None)
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found.")
    if stage["status"] not in {"succeeded", "failed"}:
        raise HTTPException(status_code=409, detail="Only completed or failed stages can be redone.")
    _ensure_runtime_ready()
    session_path = task.get("session_path")
    if session_path:
        remove_stage_artifacts(Path(session_path), stage_name, detect_source(task["url"]))
    database.reset_stages_from(task_id, stage_name)
    worker.enqueue(task_id)
    return database.get_task(task_id)


@app.post("/api/tasks/{task_id}/continue")
def continue_task(task_id: str, payload: ContinueTaskRequest | None = None) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] != "paused":
        raise HTTPException(status_code=409, detail="Only paused tasks can be continued.")
    if (task.get("execution_mode") or database.DEFAULT_EXECUTION_MODE) != "manual":
        raise HTTPException(status_code=409, detail="Only manual tasks can be continued step by step.")
    if payload and payload.execution_mode is not None:
        database.update_task(task_id, execution_mode=normalize_execution_mode(payload.execution_mode))
    _ensure_runtime_ready()
    database.queue_task_for_continue(task_id)
    worker.enqueue(task_id)
    return database.get_task(task_id)


@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str) -> dict:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    if task["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed tasks can be resumed.")
    _ensure_runtime_ready()
    database.reset_failed_for_resume(task_id)
    worker.enqueue(task_id)
    return database.get_task(task_id)


@app.get("/api/tasks/{task_id}/log", response_class=PlainTextResponse)
def task_log(task_id: str) -> str:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    path = database.log_path(task_id)
    return path.read_text(encoding="utf-8") if path.exists() else ""


@app.get("/api/tasks/{task_id}/artifact/final-video")
def final_video(task_id: str, download: bool = False) -> FileResponse:
    task = database.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    final_path = task.get("final_video_path")
    if not final_path or not Path(final_path).exists():
        raise HTTPException(status_code=404, detail="Final video is not available.")
    name = Path(final_path).name
    if download:
        return FileResponse(final_path, media_type="video/mp4", filename=name)
    headers = {"Content-Disposition": f'inline; filename="{name}"'}
    return FileResponse(final_path, media_type="video/mp4", headers=headers)


@app.get("/api/cookies/youtube")
def get_youtube_cookie() -> dict:
    metadata = runtime_security.private_file_stat(YOUTUBE_COOKIE_PATH)
    exists = metadata is not None
    size = metadata.st_size if metadata else 0
    updated_at = metadata.st_mtime if metadata else None
    return {"exists": exists, "size": size, "updated_at": updated_at, "content": ""}


@app.post("/api/cookies/youtube")
def save_youtube_cookie(payload: YouTubeCookieUpdate) -> dict:
    content = payload.content.strip()
    if content:
        runtime_security.atomic_write_private_text(YOUTUBE_COOKIE_PATH, content + "\n")
    else:
        runtime_security.remove_private_file(YOUTUBE_COOKIE_PATH, missing_ok=True)
    return get_youtube_cookie()


@app.get("/api/settings/openai")
def get_openai_settings() -> dict:
    settings = database.get_openai_settings()
    return {
        "base_url": settings["base_url"],
        "api_key": mask_secret(settings["api_key"]),
        "has_api_key": bool(settings["api_key"]),
        "model": settings["model"],
        "translate_concurrency": settings["translate_concurrency"],
    }


@app.post("/api/settings/openai")
def save_openai_settings(payload: OpenAISettingsUpdate) -> dict:
    try:
        database.save_openai_settings(
            payload.base_url,
            payload.api_key,
            payload.model,
            normalize_translate_concurrency(payload.translate_concurrency),
            clear_api_key=payload.clear_api_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_openai_settings()


@app.post("/api/settings/openai/models")
def get_openai_models(payload: OpenAIModelsRequest) -> dict:
    settings = database.get_openai_settings()
    try:
        saved_base_url = validate_openai_base_url(settings["base_url"])
        requested_base_url = payload.base_url.strip()
        base_url = (
            validate_openai_base_url(requested_base_url)
            if requested_base_url
            else saved_base_url
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    requested_api_key = payload.api_key.strip()
    if requested_base_url and base_url != saved_base_url and not requested_api_key:
        raise HTTPException(
            status_code=422,
            detail="An API key is required when testing a different OpenAI base URL.",
        )
    api_key = requested_api_key or settings["api_key"]
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key is not configured.")
    try:
        models = list_openai_models(base_url=base_url, api_key=api_key)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch models from the OpenAI-compatible API.",
        ) from exc
    return {"models": models}


@app.get("/api/settings/ytdlp")
def get_ytdlp_settings() -> dict:
    return database.get_ytdlp_settings()


@app.post("/api/settings/ytdlp")
def save_ytdlp_settings(payload: YtdlpSettingsUpdate) -> dict:
    database.save_ytdlp_settings(normalize_proxy_port(payload.proxy_port))
    return get_ytdlp_settings()
