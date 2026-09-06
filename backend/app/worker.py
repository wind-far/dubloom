"""Single-thread, SQLite-backed FIFO worker.

The in-memory queue is only a wake-up channel. SQLite is the source of truth, so
queued work survives a backend restart. Legacy task-id tokens remain supported
for tests and callers that enqueue a task not present in the current database.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import traceback
from typing import Any, Callable, Mapping

from . import database, runtime_security


_queue: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None
_lock = threading.Lock()
logger = logging.getLogger(__name__)
JobHandler = Callable[[str, dict[str, Any]], None]
_handlers: dict[str, JobHandler] = {}


def enqueue(task_id: str) -> None:
    enqueue_job(task_id, "pipeline")


def register_handler(job_type: str, handler: JobHandler) -> None:
    if job_type not in database.JOB_TYPES:
        raise ValueError(f"job_type must be one of: {', '.join(database.JOB_TYPES)}")
    _handlers[job_type] = handler


def enqueue_job(
    task_id: str,
    job_type: str,
    payload: Mapping[str, Any] | None = None,
) -> str:
    try:
        job_id = database.create_job(task_id, job_type, payload)
    except Exception:
        # Preserve the historical worker contract for isolated runner tests and
        # callers that intentionally use synthetic task ids.
        if database.get_task(task_id) is not None:
            raise
        _queue.put(task_id)
        return task_id
    _queue.put(job_id)
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    return database.get_job(job_id)


def _append_failure_log(task_id: str, traceback_text: str) -> None:
    path = database.log_path(task_id)
    timestamp = database.now_iso()
    with runtime_security.open_private_append_text(path) as handle:
        handle.write(f"[{timestamp}] Worker caught an unhandled runner exception\n")
        for line in traceback_text.rstrip().splitlines():
            handle.write(f"[{timestamp}] {line}\n")


def _record_runner_failure(task_id: str, exc: Exception) -> None:
    error_message = str(exc).strip() or type(exc).__name__
    traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    task = None
    try:
        task = database.get_task(task_id)
    except Exception:
        logger.exception("Failed to load task %s after runner exception", task_id)

    if task is not None:
        completed_at = database.now_iso()
        try:
            database.update_task(
                task_id,
                status="failed",
                error_message=error_message,
                completed_at=completed_at,
            )
        except Exception:
            logger.exception("Failed to mark task %s as failed", task_id)

        failed_stage = task.get("current_stage")
        stage_already_completed = any(
            stage.get("name") == failed_stage
            and stage.get("status") in {"succeeded", "skipped"}
            for stage in task.get("stages", ())
        )
        if failed_stage and failed_stage != "done" and not stage_already_completed:
            try:
                database.update_stage(
                    task_id,
                    failed_stage,
                    status="failed",
                    completed_at=completed_at,
                    error_message=error_message,
                    last_message="Failed",
                )
            except Exception:
                logger.exception("Failed to mark task %s stage %s as failed", task_id, failed_stage)

    try:
        _append_failure_log(task_id, traceback_text)
    except Exception:
        logger.exception("Failed to write runner exception log for task %s", task_id)


def _execute_persistent_job(job: dict[str, Any], fallback_runner: Callable[[str], None]) -> None:
    job_type = str(job["type"])
    handler = _handlers.get(job_type)
    if handler is None and job_type == "pipeline":
        handler = lambda task_id, _payload: fallback_runner(task_id)
    if handler is None:
        raise RuntimeError(f"No worker handler registered for job type: {job_type}")
    handler(str(job["task_id"]), dict(job.get("payload") or {}))


def _loop(runner: Callable[[str], None]) -> None:
    while True:
        token = _queue.get()
        job: dict[str, Any] | None = None
        task_id = token
        try:
            try:
                job = database.claim_next_job()
            except sqlite3.OperationalError as exc:
                # `_loop` is intentionally usable in isolation by the legacy
                # worker tests, where no database schema is initialized.
                if "no such table" not in str(exc).lower():
                    raise
                job = None
            if job is not None:
                task_id = str(job["task_id"])
                _execute_persistent_job(job, runner)
                database.complete_job(str(job["id"]))
            else:
                try:
                    token_job = database.get_job(token)
                except sqlite3.OperationalError as exc:
                    if "no such table" not in str(exc).lower():
                        raise
                    token_job = None
                if token_job is None:
                    # Compatibility path for direct writes to `_queue`.
                    runner(task_id)
                # Otherwise this is a duplicate/stale wake token for a durable
                # job. The database status is authoritative, so no work runs.
        except Exception as exc:
            logger.error(
                "Unhandled worker runner exception for task %s",
                task_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            if job is not None:
                try:
                    database.fail_job(
                        str(job["id"]), str(exc).strip() or type(exc).__name__
                    )
                except Exception:
                    logger.exception("Failed to mark job %s as failed", job["id"])
            try:
                if job is None or job.get("type") == "pipeline":
                    _record_runner_failure(task_id, exc)
            except Exception:
                logger.exception("Failed to record runner exception for task %s", task_id)
        finally:
            _queue.task_done()


def start(runner: Callable[[str], None]) -> None:
    global _thread
    register_handler("pipeline", lambda task_id, _payload: runner(task_id))
    database.recover_interrupted_jobs()

    # Migrate tasks queued by older versions into the durable queue. The
    # partial unique index makes this idempotent.
    pending = [t for t in reversed(database.list_tasks()) if t["status"] == "queued"]
    for task in pending:
        database.create_job(str(task["id"]), "pipeline")

    queued_jobs = database.list_jobs(status="queued", limit=100000)
    for job in queued_jobs:
        task = database.get_task(str(job["task_id"]))
        if task and str(task.get("error_message") or "").startswith(
            "Backend restarted before the task completed."
        ):
            database.update_task(
                str(job["task_id"]),
                status="queued",
                error_message=None,
                completed_at=None,
            )
    with _lock:
        if _thread is not None:
            return
        _thread = threading.Thread(target=_loop, args=(runner,), daemon=True)
        _thread.start()
    for job in queued_jobs:
        _queue.put(str(job["id"]))
