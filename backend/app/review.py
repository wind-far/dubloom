from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from . import database, runtime_security
from .audio_mode import audio_mode
from .sources import detect_source


def _task_or_raise(task_id: str) -> dict[str, Any]:
    task = database.get_task(task_id)
    if task is None:
        raise LookupError("Task not found.")
    return task


def _session(task: dict[str, Any]) -> Path:
    raw = str(task.get("session_path") or "").strip()
    if not raw:
        raise RuntimeError("Task session is not available yet.")
    path = Path(raw).resolve()
    if not path.is_dir():
        raise RuntimeError("Task session is not available.")
    return path


def translation_path(task: dict[str, Any]) -> Path:
    source = detect_source(task["url"])
    return _session(task) / "metadata" / f"translation.{source.target_language}.json"


def provider_runtime(
    task: dict[str, Any],
    kind: str,
    *,
    profile_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if kind not in {"translation", "tts"}:
        raise ValueError("kind must be one of: translation, tts")
    raw_snapshot = task.get("config_snapshot") or "{}"
    if isinstance(raw_snapshot, str):
        try:
            snapshot = json.loads(raw_snapshot)
        except json.JSONDecodeError:
            snapshot = {}
    elif isinstance(raw_snapshot, dict):
        snapshot = raw_snapshot
    else:
        snapshot = {}
    explicit_profile = profile_id is not None
    selected = (
        {}
        if explicit_profile
        else snapshot.get(kind) if isinstance(snapshot.get(kind), dict) else {}
    )
    resolved_profile_id = profile_id or task.get(f"{kind}_profile_id")
    credentials = (
        database.get_provider_profile_credentials(str(resolved_profile_id))
        if resolved_profile_id
        else None
    )
    provider_value = (
        (credentials or {}).get("provider")
        if explicit_profile
        else selected.get("provider") or (credentials or {}).get("provider")
    )
    provider = str(
        provider_value or ("openai-compatible" if kind == "translation" else "voxcpm2")
    )
    settings: dict[str, Any] = {}
    if kind == "translation" and not credentials:
        current = database.get_openai_settings()
        settings["api_key"] = current["api_key"]
    if credentials:
        settings.update(credentials.get("config") or {})
        settings.update(credentials.get("secrets") or {})
    if not explicit_profile:
        settings.update(selected.get("config") or {})
    model = (
        (credentials or {}).get("model")
        if explicit_profile
        else selected.get("model") or (credentials or {}).get("model")
    )
    if model:
        settings["model"] = model
    return provider, settings


def _segment_item(segment: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    source = detect_source(task["url"])
    return {
        "src": segment["source_text"],
        "dst": segment["translated_text"],
        "audio_mode": segment["audio_mode"],
        "src_lang": source.asr_language,
        "dst_lang": source.target_language,
        "start_time": int(segment["start_ms"]),
        "end_time": int(segment["end_ms"]),
        "speaker": str(segment.get("speaker") or "1"),
    }


def import_translation_artifact(task_id: str, artifact: Path) -> list[dict[str, Any]]:
    task = _task_or_raise(task_id)
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        items = payload["translation"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Translation artifact is invalid.") from exc
    if not isinstance(items, list):
        raise ValueError("Translation artifact must contain a translation list.")
    segments = database.replace_task_segments(
        task_id,
        [
            {
                "source_text": str(item.get("src") or item.get("source_text") or ""),
                "translated_text": str(
                    item.get("dst") or item.get("zh") or item.get("translated_text") or ""
                ),
                "start_ms": int(item.get("start_time", item.get("start_ms", 0))),
                "end_ms": int(item.get("end_time", item.get("end_ms", 0))),
                "speaker": str(item.get("speaker") or "1"),
                "audio_mode": audio_mode(item),
                "tts_profile_id": task.get("tts_profile_id"),
            }
            for item in items
        ],
    )
    return segments


def ensure_segments(task_id: str) -> list[dict[str, Any]]:
    segments = database.list_task_segments(task_id)
    if segments:
        return segments
    task = _task_or_raise(task_id)
    artifact = translation_path(task)
    if not artifact.exists():
        return []
    return import_translation_artifact(task_id, artifact)


def segment_warnings(segment: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    duration_ms = int(segment["end_ms"]) - int(segment["start_ms"])
    text = str(segment.get("translated_text") or "").strip()
    if duration_ms > 0 and text:
        cps = len(text.replace(" ", "")) / (duration_ms / 1000)
        if cps > 12:
            warnings.append(
                {
                    "code": "high_character_rate",
                    "message": f"译文语速偏快（{cps:.1f} 字符/秒）",
                }
            )
    if segment.get("audio_mode") == "tts" and duration_ms < int(
        os.getenv("VOXCPM_MIN_REFERENCE_MS", "1200")
    ):
        warnings.append(
            {
                "code": "short_reference",
                "message": "原声片段较短，TTS 可能改用同说话人的备用参考音频",
            }
        )
    return warnings


def segments_with_warnings(task_id: str) -> list[dict[str, Any]]:
    return [dict(segment, warnings=segment_warnings(segment)) for segment in ensure_segments(task_id)]


def validate_segments(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = list(segments)
    if not normalized:
        raise ValueError("No review segments are available.")
    for segment in normalized:
        translated = str(segment.get("translated_text") or "").strip()
        if not translated:
            raise ValueError(f"Segment {segment['id']} has an empty translation.")
        start = int(segment["start_ms"])
        end = int(segment["end_ms"])
        if start < 0 or end <= start:
            raise ValueError(f"Segment {segment['id']} has an invalid time range.")
        if segment.get("audio_mode") not in {"tts", "original"}:
            raise ValueError(f"Segment {segment['id']} has an invalid audio mode.")
    return normalized


def export_segments(task_id: str, *, validate: bool = True) -> Path:
    task = _task_or_raise(task_id)
    segments = database.list_task_segments(task_id)
    if validate:
        segments = validate_segments(segments)
    artifact = translation_path(task)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    runtime_security.atomic_write_private_text(
        artifact,
        json.dumps(
            {"translation": [_segment_item(segment, task) for segment in segments]},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return artifact


def _set_preview(task_id: str, segment_id: str, status: str, path: Path | None = None) -> None:
    setter = getattr(database, "set_segment_preview", None)
    if setter is not None:
        setter(task_id, segment_id, status=status, path=str(path) if path else None)
        return
    with database.connect() as conn:
        conn.execute(
            "UPDATE task_segments SET preview_status = ?, preview_path = ?, updated_at = ? "
            "WHERE task_id = ? AND id = ?",
            (status, str(path) if path else None, database.now_iso(), task_id, segment_id),
        )


def _source_clip(task_id: str, segment: dict[str, Any]) -> Path:
    task = _task_or_raise(task_id)
    session = _session(task)
    path = session / "segments" / "vocals" / f"{int(segment['position']) + 1:04d}.wav"
    if path.exists():
        return path
    artifact = export_segments(task_id, validate=False)
    vocals = session / "media" / "audio_vocals.wav"
    if not vocals.exists():
        raise RuntimeError("Source vocals are not available for preview.")
    from .adapters.audio import split_audio_by_translation

    split_audio_by_translation(vocals, artifact, session)
    if not path.exists():
        raise RuntimeError("Source audio clip was not generated.")
    return path


def run_segment_preview(task_id: str | dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    if isinstance(task_id, dict):
        job = task_id
        task_id = str(job["task_id"])
        payload = job.get("payload") or {}
    else:
        task_id = str(task_id)
        payload = payload or {}
    segment_id = str(payload.get("segment_id") or "")
    segment = database.get_task_segment(task_id, segment_id)
    if segment is None:
        raise LookupError("Segment not found.")
    task = _task_or_raise(task_id)
    session = _session(task)
    source_clip = _source_clip(task_id, segment)
    _set_preview(task_id, segment_id, "running")
    try:
        preview_root = session / "segments" / "previews" / segment_id
        refs = preview_root / "segments" / "vocals"
        metadata = preview_root / "metadata"
        refs.mkdir(parents=True, exist_ok=True)
        metadata.mkdir(parents=True, exist_ok=True)
        preview_translation = metadata / "translation.json"
        runtime_security.atomic_write_private_text(
            preview_translation,
            json.dumps(
                {"translation": [_segment_item(segment, task)]},
                ensure_ascii=False,
                indent=2,
            ),
        )
        preview_ref = refs / "0001.wav"
        if preview_ref.exists():
            runtime_security.remove_private_file(preview_ref, missing_ok=True)
        shutil.copyfile(source_clip, preview_ref)
        # Provider adapters reuse existing outputs. Remove the prior preview so
        # an edited segment cannot accidentally replay stale audio.
        runtime_security.remove_private_file(
            preview_root / "segments" / "tts" / "0001.wav",
            missing_ok=True,
        )
        from .providers import get_tts_provider

        provider_name, settings = provider_runtime(
            task,
            "tts",
            profile_id=segment.get("tts_profile_id"),
        )
        output_dir = get_tts_provider(provider_name).synthesize(
            preview_translation,
            refs,
            preview_root,
            original_vocals_file=session / "media" / "audio_vocals.wav",
            settings=settings,
        )
        output = output_dir / "0001.wav"
        if not output.exists():
            raise RuntimeError("TTS preview was not generated.")
        _set_preview(task_id, segment_id, "ready", output)
    except Exception:
        _set_preview(task_id, segment_id, "failed")
        raise


def _remove_if_exists(path: Path) -> None:
    runtime_security.remove_private_file(path, missing_ok=True)


def run_dirty_render(task_id: str | dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    if isinstance(task_id, dict):
        task_id = str(task_id["task_id"])
    else:
        task_id = str(task_id)
    database.update_task(task_id, status="running", error_message=None)
    try:
        _render_dirty(task_id)
    except Exception as exc:
        database.update_task(
            task_id,
            status="failed",
            error_message=str(exc).strip() or type(exc).__name__,
            completed_at=database.now_iso(),
        )
        raise


def _render_dirty(task_id: str) -> None:
    task = _task_or_raise(task_id)
    segments = validate_segments(database.list_task_segments(task_id))
    dirty = [segment for segment in segments if bool(segment.get("dirty"))]
    if not dirty and not bool(task.get("result_stale")):
        return

    session = _session(task)
    translation = export_segments(task_id)
    tts_dir = session / "segments" / "tts"
    for segment in dirty:
        _remove_if_exists(tts_dir / f"{int(segment['position']) + 1:04d}.wav")
        _remove_if_exists(session / "segments" / "stretched" / f"{int(segment['position']) + 1:04d}.wav")
    for path in (
        session / "tmp" / "audio_dubbing.wav",
        session / "metadata" / "timings.json",
        session / "media" / "video_final.mp4",
    ):
        _remove_if_exists(path)

    output_mode = task.get("output_mode") or database.DEFAULT_OUTPUT_MODE
    if output_mode == "subtitles":
        dubbing = None
        bgm = None
        timings = translation
    else:
        from .adapters.audio import merge_tts_audio, split_audio_by_translation
        from .providers import get_tts_provider

        vocals = session / "media" / "audio_vocals.wav"
        refs = split_audio_by_translation(vocals, translation, session)
        provider_name, settings = provider_runtime(task, "tts")
        tts_dir = get_tts_provider(provider_name).synthesize(
            translation,
            refs,
            session,
            original_vocals_file=vocals,
            settings=settings,
        )
        for segment in dirty:
            profile_id = segment.get("tts_profile_id")
            if not profile_id or segment.get("audio_mode") != "tts":
                continue
            override_root = session / "segments" / "provider-overrides" / str(segment["id"])
            override_refs = override_root / "segments" / "vocals"
            override_metadata = override_root / "metadata"
            override_refs.mkdir(parents=True, exist_ok=True)
            override_metadata.mkdir(parents=True, exist_ok=True)
            source_ref = refs / f"{int(segment['position']) + 1:04d}.wav"
            if not source_ref.exists():
                raise RuntimeError(f"Missing source audio for segment {segment['id']}.")
            override_ref = override_refs / "0001.wav"
            runtime_security.remove_private_file(override_ref, missing_ok=True)
            shutil.copyfile(source_ref, override_ref)
            override_translation = override_metadata / "translation.json"
            runtime_security.atomic_write_private_text(
                override_translation,
                json.dumps(
                    {"translation": [_segment_item(segment, task)]},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            override_output = override_root / "segments" / "tts" / "0001.wav"
            runtime_security.remove_private_file(override_output, missing_ok=True)
            override_provider, override_settings = provider_runtime(
                task,
                "tts",
                profile_id=str(profile_id),
            )
            generated_dir = get_tts_provider(override_provider).synthesize(
                override_translation,
                override_refs,
                override_root,
                original_vocals_file=vocals,
                settings=override_settings,
            )
            generated = generated_dir / "0001.wav"
            if not generated.exists():
                raise RuntimeError(f"TTS provider did not render segment {segment['id']}.")
            target = tts_dir / f"{int(segment['position']) + 1:04d}.wav"
            runtime_security.remove_private_file(target, missing_ok=True)
            shutil.copyfile(generated, target)
        dubbing, timings = merge_tts_audio(translation, tts_dir, session)
        bgm = session / "media" / "audio_bgm.wav"

    from .adapters.ffmpeg import merge_video

    final_video = merge_video(
        session / "media" / "video_source.mp4",
        dubbing,
        bgm,
        timings,
        session,
        output_mode=output_mode,
    )
    database.mark_segments_clean(task_id)
    database.update_task(
        task_id,
        status="succeeded",
        current_stage="done",
        final_video_path=str(final_video),
        result_stale=0,
        completed_at=database.now_iso(),
        error_message=None,
    )


def safe_segment_audio(task_id: str, segment_id: str, kind: str) -> Path:
    task = _task_or_raise(task_id)
    segment = database.get_task_segment(task_id, segment_id)
    if segment is None:
        raise LookupError("Segment not found.")
    session = _session(task).resolve()
    if kind == "source":
        path = _source_clip(task_id, segment)
    elif kind == "preview":
        raw = str(segment.get("preview_path") or "").strip()
        if not raw:
            raise FileNotFoundError("Preview audio is not available.")
        path = Path(raw)
    else:
        raise ValueError("kind must be one of: source, preview")
    resolved = path.resolve()
    try:
        resolved.relative_to(session)
    except ValueError as exc:
        raise PermissionError("Media path is outside the task session.") from exc
    if not resolved.is_file():
        raise FileNotFoundError("Audio is not available.")
    return resolved
