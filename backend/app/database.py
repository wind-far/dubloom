from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import config, runtime_security
from .config import DB_PATH, ensure_runtime_dirs, openai_defaults, ytdlp_defaults
from .stages import STAGES


ACTIVE_STATUSES = ("queued", "running")
EXECUTION_MODES = ("auto", "manual")
DEFAULT_EXECUTION_MODE = "auto"
OUTPUT_MODES = ("subtitles", "dubbing", "both")
DEFAULT_OUTPUT_MODE = "both"
REVIEW_MODES = ("none", "required")
DEFAULT_REVIEW_MODE = "none"
PROVIDER_KINDS = ("translation", "tts")
JOB_TYPES = ("pipeline", "segment_preview", "dirty_render")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    if Path(DB_PATH).absolute() == Path(config.DB_PATH).absolute():
        ensure_runtime_dirs()
    runtime_security.secure_sqlite_database_file(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    try:
        runtime_security.secure_sqlite_database_file(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn
    except Exception:
        conn.close()
        raise


def init_db() -> None:
    if Path(DB_PATH).absolute() == Path(config.DB_PATH).absolute():
        ensure_runtime_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              url TEXT NOT NULL,
              title TEXT,
              status TEXT NOT NULL,
              current_stage TEXT,
              session_path TEXT,
              final_video_path TEXT,
              error_message TEXT,
              created_at TEXT NOT NULL,
              started_at TEXT,
              completed_at TEXT,
              execution_mode TEXT NOT NULL DEFAULT 'auto',
              output_mode TEXT NOT NULL DEFAULT 'both'
            );

            CREATE TABLE IF NOT EXISTS task_stages (
              task_id TEXT NOT NULL,
              name TEXT NOT NULL,
              label TEXT NOT NULL,
              status TEXT NOT NULL,
              progress INTEGER,
              started_at TEXT,
              completed_at TEXT,
              last_message TEXT,
              error_message TEXT,
              PRIMARY KEY (task_id, name),
              FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
              token_hash TEXT PRIMARY KEY,
              credential_version TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at
            ON auth_sessions(expires_at);

            CREATE TABLE IF NOT EXISTS auth_login_attempts (
              client_hash TEXT PRIMARY KEY,
              window_started_at TEXT NOT NULL,
              attempt_count INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              applied_at TEXT NOT NULL
            );
            """
        )
        defaults = openai_defaults()
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (f"openai.{key}", value, now_iso()),
            )
        for key, value in ytdlp_defaults().items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (f"ytdlp.{key}", value, now_iso()),
            )
        task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "title" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN title TEXT")
        if "execution_mode" not in task_columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'auto'"
            )
        if "output_mode" not in task_columns:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN output_mode TEXT NOT NULL DEFAULT 'both'"
            )
        stage_columns = {row["name"] for row in conn.execute("PRAGMA table_info(task_stages)").fetchall()}
        if "progress" not in stage_columns:
            conn.execute("ALTER TABLE task_stages ADD COLUMN progress INTEGER")
        _run_schema_migrations(conn)


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    if name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _migration_1_review_workspace(conn: sqlite3.Connection) -> None:
    _add_column(conn, "tasks", "review_mode", "TEXT NOT NULL DEFAULT 'none'")
    _add_column(conn, "tasks", "translation_profile_id", "TEXT")
    _add_column(conn, "tasks", "tts_profile_id", "TEXT")
    _add_column(conn, "tasks", "config_snapshot", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(conn, "tasks", "review_approved_at", "TEXT")
    _add_column(conn, "tasks", "result_stale", "INTEGER NOT NULL DEFAULT 0")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS provider_profiles (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL CHECK (kind IN ('translation', 'tts')),
          name TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT NOT NULL DEFAULT '',
          config_json TEXT NOT NULL DEFAULT '{}',
          secret_config_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS task_segments (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          position INTEGER NOT NULL,
          source_text TEXT NOT NULL,
          translated_text TEXT NOT NULL,
          start_ms INTEGER NOT NULL,
          end_ms INTEGER NOT NULL,
          speaker TEXT NOT NULL DEFAULT '1',
          audio_mode TEXT NOT NULL DEFAULT 'tts' CHECK (audio_mode IN ('tts', 'original')),
          tts_profile_id TEXT,
          revision INTEGER NOT NULL DEFAULT 1,
          dirty INTEGER NOT NULL DEFAULT 1,
          preview_status TEXT NOT NULL DEFAULT 'none',
          preview_path TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (task_id, position),
          FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
          FOREIGN KEY (tts_profile_id) REFERENCES provider_profiles(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          type TEXT NOT NULL CHECK (type IN ('pipeline', 'segment_preview', 'dirty_render')),
          payload_json TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
          attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          started_at TEXT,
          completed_at TEXT,
          error_message TEXT,
          FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        """
    )


def _migration_2_review_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_provider_profiles_kind
        ON provider_profiles(kind, created_at);
        CREATE INDEX IF NOT EXISTS idx_task_segments_task_position
        ON task_segments(task_id, position);
        CREATE INDEX IF NOT EXISTS idx_task_segments_dirty
        ON task_segments(task_id, dirty, position);
        CREATE INDEX IF NOT EXISTS idx_jobs_fifo
        ON jobs(status, created_at, id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_queued_pipeline
        ON jobs(task_id, type) WHERE status IN ('queued', 'running') AND type = 'pipeline';
        """
    )


def _migration_3_job_progress(conn: sqlite3.Connection) -> None:
    _add_column(conn, "jobs", "progress", "INTEGER NOT NULL DEFAULT 0")


SCHEMA_MIGRATIONS = (
    (1, _migration_1_review_workspace),
    (2, _migration_2_review_indexes),
    (3, _migration_3_job_progress),
)


def _run_schema_migrations(conn: sqlite3.Connection) -> None:
    applied = {
        int(row["version"])
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, migration in SCHEMA_MIGRATIONS:
        if version in applied:
            continue
        migration(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )


def create_auth_session(
    *,
    token_hash: str,
    credential_version: str,
    created_at: str,
    expires_at: str,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (
              token_hash, credential_version, created_at, expires_at
            ) VALUES (?, ?, ?, ?)
            """,
            (token_hash, credential_version, created_at, expires_at),
        )


def get_auth_session(token_hash: str) -> dict[str, str] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT token_hash, credential_version, created_at, expires_at
            FROM auth_sessions
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    return dict(row) if row else None


def delete_auth_session(token_hash: str) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
        return cursor.rowcount > 0


def delete_expired_auth_sessions(expires_before: str) -> int:
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM auth_sessions WHERE expires_at <= ?",
            (expires_before,),
        )
        return cursor.rowcount


def reserve_auth_login_attempt(
    *,
    client_hash: str,
    now: str,
    stale_before: str,
    max_attempts: int,
) -> tuple[bool, str]:
    """Atomically reserve one login attempt across processes sharing SQLite."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM auth_login_attempts WHERE window_started_at <= ?",
            (stale_before,),
        )
        row = conn.execute(
            """
            SELECT window_started_at, attempt_count
            FROM auth_login_attempts
            WHERE client_hash = ?
            """,
            (client_hash,),
        ).fetchone()
        if row and int(row["attempt_count"]) >= max_attempts:
            return False, str(row["window_started_at"])

        if row:
            conn.execute(
                """
                UPDATE auth_login_attempts
                SET attempt_count = attempt_count + 1
                WHERE client_hash = ?
                """,
                (client_hash,),
            )
            return True, str(row["window_started_at"])

        conn.execute(
            """
            INSERT INTO auth_login_attempts (
              client_hash, window_started_at, attempt_count
            ) VALUES (?, ?, 1)
            """,
            (client_hash, now),
        )
        return True, now


def delete_auth_login_attempt(client_hash: str) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            "DELETE FROM auth_login_attempts WHERE client_hash = ?",
            (client_hash,),
        )
        return cursor.rowcount > 0


def backfill_titles_from_metadata() -> None:
    import json
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, session_path FROM tasks WHERE (title IS NULL OR title = '') AND session_path IS NOT NULL"
        ).fetchall()
    for row in rows:
        info_path = Path(row["session_path"]) / "metadata" / "ytdlp_info.json"
        if not info_path.exists():
            continue
        title = (json.loads(info_path.read_text(encoding="utf-8")).get("title") or "").strip()
        if not title:
            continue
        with connect() as conn:
            conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (title, row["id"]))


def fail_stale_active_tasks() -> None:
    message = "Backend restarted before the task completed."
    completed_at = now_iso()
    with connect() as conn:
        active_tasks = conn.execute(
            f"SELECT id, current_stage FROM tasks WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
            ACTIVE_STATUSES,
        ).fetchall()
        for task in active_tasks:
            conn.execute(
                """
                UPDATE tasks
                SET status = 'failed', error_message = ?, completed_at = ?
                WHERE id = ?
                """,
                (message, completed_at, task["id"]),
            )
            if task["current_stage"]:
                conn.execute(
                    """
                    UPDATE task_stages
                    SET status = 'failed', error_message = ?, completed_at = ?
                    WHERE task_id = ? AND name = ? AND status IN ('pending', 'running')
                    """,
                    (message, completed_at, task["id"], task["current_stage"]),
                )


def normalize_execution_mode(value: str | None) -> str:
    mode = (value or DEFAULT_EXECUTION_MODE).strip().lower()
    if mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}")
    return mode


def normalize_output_mode(value: str | None) -> str:
    mode = (value or DEFAULT_OUTPUT_MODE).strip().lower()
    if mode not in OUTPUT_MODES:
        raise ValueError(f"output_mode must be one of: {', '.join(OUTPUT_MODES)}")
    return mode


def normalize_review_mode(value: str | None) -> str:
    mode = (value or DEFAULT_REVIEW_MODE).strip().lower()
    if mode not in REVIEW_MODES:
        raise ValueError(f"review_mode must be one of: {', '.join(REVIEW_MODES)}")
    return mode


def _json_text(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), ensure_ascii=False, separators=(",", ":"))


def video_task_id(
    video_id: str,
    output_mode: str,
    review_mode: str = DEFAULT_REVIEW_MODE,
    translation_profile_id: str | None = None,
    tts_profile_id: str | None = None,
) -> str:
    mode = normalize_output_mode(output_mode)
    normalized_review = normalize_review_mode(review_mode)
    base = video_id if mode == DEFAULT_OUTPUT_MODE else f"{video_id}-{mode}"
    if (
        normalized_review == DEFAULT_REVIEW_MODE
        and translation_profile_id is None
        and tts_profile_id is None
    ):
        return base
    fingerprint = hashlib.sha256(
        "\0".join(
            (
                normalized_review,
                translation_profile_id or "",
                tts_profile_id or "",
            )
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"{base}-cfg-{fingerprint}"


def create_task(
    url: str,
    task_id: str | None = None,
    *,
    execution_mode: str = DEFAULT_EXECUTION_MODE,
    output_mode: str = DEFAULT_OUTPUT_MODE,
    review_mode: str = DEFAULT_REVIEW_MODE,
    translation_profile_id: str | None = None,
    tts_profile_id: str | None = None,
    config_snapshot: Mapping[str, Any] | None = None,
) -> str:
    new_id = task_id or str(uuid.uuid4())
    created_at = now_iso()
    mode = normalize_execution_mode(execution_mode)
    normalized_output_mode = normalize_output_mode(output_mode)
    normalized_review_mode = normalize_review_mode(review_mode)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
              id, url, status, current_stage, created_at, execution_mode, output_mode,
              review_mode, translation_profile_id, tts_profile_id, config_snapshot
            )
            VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                url,
                STAGES[0].name,
                created_at,
                mode,
                normalized_output_mode,
                normalized_review_mode,
                translation_profile_id,
                tts_profile_id,
                _json_text(config_snapshot),
            ),
        )
        conn.executemany(
            """
            INSERT INTO task_stages (task_id, name, label, status)
            VALUES (?, ?, ?, 'pending')
            """,
            [(new_id, stage.name, stage.label) for stage in STAGES],
        )
    return new_id


def create_or_get_video_task(
    url: str,
    video_id: str,
    *,
    execution_mode: str = DEFAULT_EXECUTION_MODE,
    output_mode: str = DEFAULT_OUTPUT_MODE,
    review_mode: str = DEFAULT_REVIEW_MODE,
    translation_profile_id: str | None = None,
    tts_profile_id: str | None = None,
    config_snapshot: Mapping[str, Any] | None = None,
) -> tuple[str, bool]:
    from .youtube import extract_video_id

    task_id = video_task_id(
        video_id,
        output_mode,
        review_mode,
        translation_profile_id,
        tts_profile_id,
    )
    created_at = now_iso()
    mode = normalize_execution_mode(execution_mode)
    normalized_output_mode = normalize_output_mode(output_mode)
    normalized_review_mode = normalize_review_mode(review_mode)
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tasks (
              id, url, status, current_stage, created_at, execution_mode, output_mode,
              review_mode, translation_profile_id, tts_profile_id, config_snapshot
            )
            VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                task_id,
                url,
                STAGES[0].name,
                created_at,
                mode,
                normalized_output_mode,
                normalized_review_mode,
                translation_profile_id,
                tts_profile_id,
                _json_text(config_snapshot),
            ),
        )
        if cursor.rowcount == 1:
            conn.executemany(
                """
                INSERT INTO task_stages (task_id, name, label, status)
                VALUES (?, ?, ?, 'pending')
                """,
                [(task_id, stage.name, stage.label) for stage in STAGES],
            )
            return task_id, True

        existing = conn.execute(
            "SELECT id, url, output_mode, review_mode, translation_profile_id, tts_profile_id "
            "FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if existing is None:
            raise RuntimeError(f"Task {task_id} disappeared after an id conflict.")
        try:
            existing_video_id = extract_video_id(existing["url"])
        except ValueError as exc:
            raise sqlite3.IntegrityError(
                f"Task id collision for {task_id}: existing URL is not a supported video URL."
            ) from exc
        if (
            existing_video_id != video_id
            or existing["output_mode"] != normalized_output_mode
            or existing["review_mode"] != normalized_review_mode
            or existing["translation_profile_id"] != translation_profile_id
            or existing["tts_profile_id"] != tts_profile_id
        ):
            raise sqlite3.IntegrityError(
                f"Task id collision for {task_id}: existing task has different video or output mode/configuration."
            )
        return task_id, False


def find_task_by_video_id(
    video_id: str,
    output_mode: str = DEFAULT_OUTPUT_MODE,
    *,
    review_mode: str = DEFAULT_REVIEW_MODE,
    translation_profile_id: str | None = None,
    tts_profile_id: str | None = None,
) -> str | None:
    from .youtube import extract_video_id

    mode = normalize_output_mode(output_mode)
    normalized_review = normalize_review_mode(review_mode)
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, url FROM tasks WHERE output_mode = ? AND review_mode = ? "
            "AND translation_profile_id IS ? AND tts_profile_id IS ? "
            "AND url NOT LIKE 'local://%' "
            "ORDER BY created_at DESC, rowid DESC",
            (mode, normalized_review, translation_profile_id, tts_profile_id),
        ).fetchall()
    for row in rows:
        try:
            if extract_video_id(row["url"]) == video_id:
                return row["id"]
        except ValueError:
            continue
    return None


def has_active_task() -> bool:
    with connect() as conn:
        row = conn.execute(
            f"SELECT 1 FROM tasks WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)}) LIMIT 1",
            ACTIVE_STATUSES,
        ).fetchone()
    return row is not None


def latest_task_id() -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM tasks ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
    return row["id"] if row else None


TASK_SUMMARY_COLUMNS = (
    "id, url, title, status, current_stage, final_video_path, error_message, "
    "created_at, started_at, completed_at, execution_mode, output_mode, review_mode, "
    "translation_profile_id, tts_profile_id, review_approved_at, result_stale"
)

TASK_LIST_SORTS = {
    "created_desc": "created_at DESC, rowid DESC",
    "created_asc": "created_at ASC, rowid ASC",
    "started_desc": "started_at IS NULL ASC, started_at DESC, rowid DESC",
    "started_asc": "started_at IS NULL ASC, started_at ASC, rowid ASC",
    "completed_desc": "completed_at IS NULL ASC, completed_at DESC, rowid DESC",
    "completed_asc": "completed_at IS NULL ASC, completed_at ASC, rowid ASC",
    "status_asc": (
        "CASE status "
        "WHEN 'queued' THEN 1 "
        "WHEN 'running' THEN 2 "
        "WHEN 'awaiting_review' THEN 3 "
        "WHEN 'paused' THEN 4 "
        "WHEN 'failed' THEN 5 "
        "WHEN 'succeeded' THEN 6 "
        "ELSE 99 END ASC, created_at DESC, rowid DESC"
    ),
    "status_desc": (
        "CASE status "
        "WHEN 'queued' THEN 1 "
        "WHEN 'running' THEN 2 "
        "WHEN 'awaiting_review' THEN 3 "
        "WHEN 'paused' THEN 4 "
        "WHEN 'failed' THEN 5 "
        "WHEN 'succeeded' THEN 6 "
        "ELSE 99 END DESC, created_at DESC, rowid DESC"
    ),
    "title_asc": "LOWER(COALESCE(NULLIF(TRIM(title), ''), url)) ASC, created_at DESC, rowid DESC",
    "title_desc": "LOWER(COALESCE(NULLIF(TRIM(title), ''), url)) DESC, created_at DESC, rowid DESC",
}


def list_tasks(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {TASK_SUMMARY_COLUMNS} FROM tasks "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_tasks_page(
    *,
    page: int = 1,
    page_size: int = 20,
    query: str = "",
    status: str = "all",
    execution_mode: str = "all",
    sort: str = "created_desc",
) -> dict[str, Any]:
    page = max(page, 1)
    page_size = max(page_size, 1)
    offset = (page - 1) * page_size
    where_parts: list[str] = []
    params: list[Any] = []

    needle = query.strip().lower()
    if needle:
        pattern = f"%{needle}%"
        where_parts.append(
            "(LOWER(COALESCE(title, '')) LIKE ? "
            "OR LOWER(url) LIKE ? "
            "OR LOWER(id) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern])
    if status != "all":
        where_parts.append("status = ?")
        params.append(status)
    if execution_mode != "all":
        where_parts.append("execution_mode = ?")
        params.append(execution_mode)

    where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    order_sql = TASK_LIST_SORTS.get(sort, TASK_LIST_SORTS["created_desc"])
    active_placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)

    with connect() as conn:
        counts = conn.execute(
            "SELECT "
            f"(SELECT COUNT(*) FROM tasks{where_sql}) AS filtered_total, "
            f"(SELECT COUNT(*) FROM tasks WHERE status IN ({active_placeholders})) AS active_count",
            [*params, *ACTIVE_STATUSES],
        ).fetchone()
        rows = conn.execute(
            f"SELECT {TASK_SUMMARY_COLUMNS} FROM tasks{where_sql} "
            f"ORDER BY {order_sql} LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()

    return {
        "tasks": [dict(row) for row in rows],
        "total": counts["filtered_total"],
        "active_count": counts["active_count"],
        "page": page,
        "page_size": page_size,
    }


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return None
        stages = conn.execute(
            """
            SELECT * FROM task_stages
            WHERE task_id = ?
            ORDER BY
              CASE name
                WHEN 'download' THEN 1
                WHEN 'separate' THEN 2
                WHEN 'asr' THEN 3
                WHEN 'asr_fix' THEN 4
                WHEN 'translate' THEN 5
                WHEN 'split_audio' THEN 6
                WHEN 'tts' THEN 7
                WHEN 'merge_audio' THEN 8
                WHEN 'merge_video' THEN 9
                ELSE 99
              END
            """,
            (task_id,),
        ).fetchall()
    result = dict(task)
    result["stages"] = [dict(stage) for stage in stages]
    return result


def get_current_task() -> dict[str, Any] | None:
    task_id = latest_task_id()
    return get_task(task_id) if task_id else None


def delete_task(task_id: str) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.execute("DELETE FROM task_stages WHERE task_id = ?", (task_id,))
        return cursor.rowcount > 0


def queue_task_for_continue(task_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET status = 'queued', error_message = NULL, completed_at = NULL
            WHERE id = ?
            """,
            (task_id,),
        )


def reset_stages_from(task_id: str, from_stage: str) -> None:
    from .stages import STAGE_NAMES

    if from_stage not in STAGE_NAMES:
        raise ValueError(f"Unknown stage: {from_stage}")

    start = STAGE_NAMES.index(from_stage)
    with connect() as conn:
        for stage in STAGE_NAMES[start:]:
            conn.execute(
                """
                UPDATE task_stages
                SET status = 'pending', started_at = NULL, completed_at = NULL,
                    progress = NULL, last_message = NULL, error_message = NULL
                WHERE task_id = ? AND name = ?
                """,
                (task_id, stage),
            )
        conn.execute(
            """
            UPDATE tasks
            SET status = 'queued', current_stage = ?, final_video_path = NULL,
                completed_at = NULL, error_message = NULL
            WHERE id = ?
            """,
            (from_stage, task_id),
        )


def reset_failed_for_resume(task_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE task_stages
            SET status = 'pending', started_at = NULL, completed_at = NULL,
                progress = NULL, last_message = NULL, error_message = NULL
            WHERE task_id = ? AND status IN ('failed', 'running')
            """,
            (task_id,),
        )
        conn.execute(
            """
            UPDATE tasks
            SET status = 'queued', error_message = NULL, completed_at = NULL,
                started_at = NULL
            WHERE id = ?
            """,
            (task_id,),
        )


def update_task(task_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [task_id]
    with connect() as conn:
        conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", values)


def update_stage(task_id: str, name: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [task_id, name]
    with connect() as conn:
        conn.execute(f"UPDATE task_stages SET {assignments} WHERE task_id = ? AND name = ?", values)


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now_iso()),
        )


def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_openai_settings() -> dict[str, str]:
    from .adapters.openai_client import normalize_openai_base_url

    defaults = openai_defaults()
    keys = {
        "base_url": "openai.base_url",
        "api_key": "openai.api_key",
        "model": "openai.model",
        "translate_concurrency": "openai.translate_concurrency",
    }
    placeholders = ", ".join("?" for _ in keys)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
            tuple(keys.values()),
        ).fetchall()
    saved = {row["key"]: row["value"] for row in rows}
    return {
        "base_url": normalize_openai_base_url(
            saved.get(keys["base_url"], defaults["base_url"])
        ),
        "api_key": saved.get(keys["api_key"], defaults["api_key"]),
        "model": saved.get(keys["model"], defaults["model"]),
        "translate_concurrency": saved.get(
            keys["translate_concurrency"], defaults["translate_concurrency"]
        ),
    }


def save_openai_settings(
    base_url: str,
    api_key: str,
    model: str,
    translate_concurrency: str = "",
    *,
    clear_api_key: bool = False,
) -> None:
    from .adapters.openai_client import validate_openai_base_url

    validated_base_url = validate_openai_base_url(base_url)
    defaults = openai_defaults()
    cleaned_api_key = api_key.strip()
    has_explicit_api_key = bool(cleaned_api_key) and set(cleaned_api_key) != {"*"}
    updated_at = now_iso()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        def current_value(key: str, default: str) -> str:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

        current_base_url = validate_openai_base_url(
            current_value("openai.base_url", defaults["base_url"])
        )
        current_api_key = current_value("openai.api_key", defaults["api_key"])
        if (
            validated_base_url != current_base_url
            and current_api_key
            and not has_explicit_api_key
            and not clear_api_key
        ):
            raise ValueError("A new API key is required when changing the OpenAI base URL.")

        updates = {
            "openai.base_url": validated_base_url,
            "openai.model": model.strip(),
        }
        if clear_api_key:
            updates["openai.api_key"] = ""
        elif has_explicit_api_key:
            updates["openai.api_key"] = cleaned_api_key
        if translate_concurrency.strip():
            updates["openai.translate_concurrency"] = translate_concurrency.strip()

        conn.executemany(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE
            SET value = excluded.value, updated_at = excluded.updated_at
            """,
            [(key, value, updated_at) for key, value in updates.items()],
        )


def get_ytdlp_settings() -> dict[str, str]:
    defaults = ytdlp_defaults()
    return {
        "proxy_port": get_setting("ytdlp.proxy_port", defaults["proxy_port"]),
    }


def save_ytdlp_settings(proxy_port: str) -> None:
    set_setting("ytdlp.proxy_port", proxy_port.strip())


class SegmentRevisionConflict(RuntimeError):
    """Raised when a segment was edited after the caller loaded it."""


def _decode_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def _provider_profile_view(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["config"] = _decode_json_object(result.pop("config_json", "{}"))
    secret_values = _decode_json_object(result.pop("secret_config_json", "{}"))
    result["has_secrets"] = bool(secret_values)
    return result


def create_provider_profile(
    kind: str,
    name: str,
    provider: str,
    model: str = "",
    config: Mapping[str, Any] | None = None,
    secrets: Mapping[str, Any] | None = None,
    *,
    profile_id: str | None = None,
) -> str:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in PROVIDER_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(PROVIDER_KINDS)}")
    cleaned_name = name.strip()
    cleaned_provider = provider.strip()
    if not cleaned_name or not cleaned_provider:
        raise ValueError("name and provider are required")
    new_id = profile_id or str(uuid.uuid4())
    timestamp = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO provider_profiles (
              id, kind, name, provider, model, config_json, secret_config_json,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                normalized_kind,
                cleaned_name,
                cleaned_provider,
                model.strip(),
                _json_text(config),
                _json_text(secrets),
                timestamp,
                timestamp,
            ),
        )
    return new_id


def list_provider_profiles(kind: str | None = None) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if kind is not None:
        normalized_kind = kind.strip().lower()
        if normalized_kind not in PROVIDER_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(PROVIDER_KINDS)}")
        where = " WHERE kind = ?"
        params = (normalized_kind,)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM provider_profiles{where} ORDER BY created_at, id",
            params,
        ).fetchall()
    return [_provider_profile_view(row) for row in rows]


def get_provider_profile(profile_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM provider_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    return _provider_profile_view(row) if row else None


def get_provider_profile_credentials(profile_id: str) -> dict[str, Any] | None:
    """Internal profile view including secrets; never return this from an API."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM provider_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    if not row:
        return None
    result = _provider_profile_view(row)
    result["secrets"] = _decode_json_object(row["secret_config_json"])
    return result


def update_provider_profile(
    profile_id: str,
    *,
    name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    config: Mapping[str, Any] | None = None,
    secrets: Mapping[str, Any] | None = None,
    clear_secrets: bool = False,
) -> bool:
    fields: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise ValueError("name must be non-empty")
        fields["name"] = name.strip()
    if provider is not None:
        if not provider.strip():
            raise ValueError("provider must be non-empty")
        fields["provider"] = provider.strip()
    if model is not None:
        fields["model"] = model.strip()
    if config is not None:
        fields["config_json"] = _json_text(config)
    if clear_secrets:
        fields["secret_config_json"] = "{}"
    elif secrets is not None:
        fields["secret_config_json"] = _json_text(secrets)
    if not fields:
        return get_provider_profile(profile_id) is not None
    fields["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with connect() as conn:
        cursor = conn.execute(
            f"UPDATE provider_profiles SET {assignments} WHERE id = ?",
            [*fields.values(), profile_id],
        )
        return cursor.rowcount > 0


def delete_provider_profile(profile_id: str) -> bool:
    with connect() as conn:
        cursor = conn.execute("DELETE FROM provider_profiles WHERE id = ?", (profile_id,))
        return cursor.rowcount > 0


def _segment_view(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["dirty"] = bool(result["dirty"])
    return result


def replace_task_segments(
    task_id: str,
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    timestamp = now_iso()
    rows: list[tuple[Any, ...]] = []
    for position, item in enumerate(items):
        source_text = str(item.get("source_text", item.get("src", "")))
        translated_text = str(item.get("translated_text", item.get("dst", "")))
        start_ms = int(item.get("start_ms", item.get("start_time", 0)))
        end_ms = int(item.get("end_ms", item.get("end_time", 0)))
        # Legacy/custom translation artifacts may omit timing. Persist them so
        # the review UI can repair the row; approval remains the hard gate.
        if start_ms < 0 or end_ms < 0:
            raise ValueError(f"segment {position} timing cannot be negative")
        audio_mode = str(item.get("audio_mode") or "tts").strip().lower()
        if audio_mode not in {"tts", "original"}:
            raise ValueError("audio_mode must be one of: tts, original")
        rows.append(
            (
                str(item.get("id") or uuid.uuid4()),
                task_id,
                int(item.get("position", position)),
                source_text,
                translated_text,
                start_ms,
                end_ms,
                str(item.get("speaker") or "1"),
                audio_mode,
                item.get("tts_profile_id"),
                max(1, int(item.get("revision", 1))),
                1 if item.get("dirty", True) else 0,
                str(item.get("preview_status") or "none"),
                item.get("preview_path"),
                timestamp,
                timestamp,
            )
        )
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            raise KeyError(task_id)
        conn.execute("DELETE FROM task_segments WHERE task_id = ?", (task_id,))
        conn.executemany(
            """
            INSERT INTO task_segments (
              id, task_id, position, source_text, translated_text, start_ms, end_ms,
              speaker, audio_mode, tts_profile_id, revision, dirty, preview_status,
              preview_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return list_task_segments(task_id)


def list_task_segments(task_id: str, *, dirty_only: bool = False) -> list[dict[str, Any]]:
    where = "task_id = ?"
    if dirty_only:
        where += " AND dirty = 1"
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM task_segments WHERE {where} ORDER BY position, id",
            (task_id,),
        ).fetchall()
    return [_segment_view(row) for row in rows]


def get_task_segment(task_id: str, segment_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM task_segments WHERE task_id = ? AND id = ?",
            (task_id, segment_id),
        ).fetchone()
    return _segment_view(row) if row else None


SEGMENT_UPDATE_FIELDS = {
    "source_text",
    "translated_text",
    "start_ms",
    "end_ms",
    "speaker",
    "audio_mode",
    "tts_profile_id",
    "preview_status",
    "preview_path",
    "position",
}
SEGMENT_RENDER_FIELDS = {
    "translated_text",
    "start_ms",
    "end_ms",
    "speaker",
    "audio_mode",
    "tts_profile_id",
}


def update_task_segment(
    task_id: str,
    segment_id: str,
    expected_revision: int,
    **fields: Any,
) -> dict[str, Any] | None:
    unknown = set(fields) - SEGMENT_UPDATE_FIELDS
    if unknown:
        raise ValueError(f"unsupported segment fields: {', '.join(sorted(unknown))}")
    if not fields:
        return get_task_segment(task_id, segment_id)
    if "audio_mode" in fields and fields["audio_mode"] not in {"tts", "original"}:
        raise ValueError("audio_mode must be one of: tts, original")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT * FROM task_segments WHERE task_id = ? AND id = ?",
            (task_id, segment_id),
        ).fetchone()
        if current is None:
            return None
        if int(current["revision"]) != int(expected_revision):
            raise SegmentRevisionConflict(
                f"segment revision changed from {expected_revision} to {current['revision']}"
            )
        candidate_start = int(fields.get("start_ms", current["start_ms"]))
        candidate_end = int(fields.get("end_ms", current["end_ms"]))
        if candidate_start < 0 or candidate_end <= candidate_start:
            raise ValueError("segment must have 0 <= start_ms < end_ms")
        changed = {key for key, value in fields.items() if current[key] != value}
        updates = dict(fields)
        updates["revision"] = int(current["revision"]) + 1
        updates["updated_at"] = now_iso()
        if changed & SEGMENT_RENDER_FIELDS:
            updates.update(dirty=1, preview_status="none", preview_path=None)
            conn.execute("UPDATE tasks SET result_stale = 1 WHERE id = ?", (task_id,))
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE task_segments SET {assignments} WHERE task_id = ? AND id = ?",
            [*updates.values(), task_id, segment_id],
        )
        row = conn.execute(
            "SELECT * FROM task_segments WHERE task_id = ? AND id = ?",
            (task_id, segment_id),
        ).fetchone()
    return _segment_view(row)


def mark_segments_clean(task_id: str, ids: Iterable[str] | None = None) -> int:
    segment_ids = list(ids) if ids is not None else None
    with connect() as conn:
        if segment_ids is None:
            cursor = conn.execute(
                "UPDATE task_segments SET dirty = 0, updated_at = ? WHERE task_id = ?",
                (now_iso(), task_id),
            )
        elif not segment_ids:
            return 0
        else:
            placeholders = ",".join("?" for _ in segment_ids)
            cursor = conn.execute(
                f"UPDATE task_segments SET dirty = 0, updated_at = ? "
                f"WHERE task_id = ? AND id IN ({placeholders})",
                [now_iso(), task_id, *segment_ids],
            )
        return cursor.rowcount


def set_segment_preview(
    task_id: str,
    segment_id: str,
    status: str,
    path: str | None = None,
) -> bool:
    if status not in {"none", "queued", "running", "generating", "ready", "failed"}:
        raise ValueError("invalid preview status")
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE task_segments
            SET preview_status = ?, preview_path = ?, updated_at = ?
            WHERE task_id = ? AND id = ?
            """,
            (status, path, now_iso(), task_id, segment_id),
        )
        return cursor.rowcount > 0


def _job_view(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["job_type"] = result["type"]
    result["payload"] = _decode_json_object(result.pop("payload_json", "{}"))
    result["progress"] = int(result.get("progress") or 0)
    return result


def create_job(
    task_id: str,
    job_type: str = "pipeline",
    payload: Mapping[str, Any] | None = None,
    *,
    job_id: str | None = None,
) -> str:
    normalized_type = job_type.strip().lower()
    if normalized_type not in JOB_TYPES:
        raise ValueError(f"job_type must be one of: {', '.join(JOB_TYPES)}")
    new_id = job_id or str(uuid.uuid4())
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if normalized_type == "pipeline":
            existing = conn.execute(
                """
                SELECT id FROM jobs
                WHERE task_id = ? AND type = 'pipeline' AND status IN ('queued', 'running')
                ORDER BY created_at, id LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if existing:
                return str(existing["id"])
        conn.execute(
            """
            INSERT INTO jobs (id, task_id, type, payload_json, status, created_at)
            VALUES (?, ?, ?, ?, 'queued', ?)
            """,
            (new_id, task_id, normalized_type, _json_text(payload), now_iso()),
        )
    return new_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_view(row) if row else None


def list_jobs(
    *,
    task_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if task_id is not None:
        where.append("task_id = ?")
        params.append(task_id)
    if status is not None:
        if status not in JOB_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(JOB_STATUSES)}")
        where.append("status = ?")
        params.append(status)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs{where_sql} ORDER BY created_at, rowid LIMIT ?",
            [*params, max(1, limit)],
        ).fetchall()
    return [_job_view(row) for row in rows]


def claim_next_job() -> dict[str, Any] | None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at, rowid LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        started_at = now_iso()
        conn.execute(
            """
            UPDATE jobs SET status = 'running', started_at = ?, completed_at = NULL,
              error_message = NULL, attempts = attempts + 1
            WHERE id = ? AND status = 'queued'
            """,
            (started_at, row["id"]),
        )
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
    return _job_view(claimed)


def complete_job(job_id: str) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs SET status = 'succeeded', progress = 100,
              completed_at = ?, error_message = NULL
            WHERE id = ? AND status = 'running'
            """,
            (now_iso(), job_id),
        )
        return cursor.rowcount > 0


def fail_job(job_id: str, error_message: str) -> bool:
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs SET status = 'failed', completed_at = ?, error_message = ?
            WHERE id = ? AND status = 'running'
            """,
            (now_iso(), error_message, job_id),
        )
        return cursor.rowcount > 0


def update_job_progress(job_id: str, progress: int) -> bool:
    bounded = max(0, min(100, int(progress)))
    with connect() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET progress = ? WHERE id = ? AND status = 'running'",
            (bounded, job_id),
        )
        return cursor.rowcount > 0


def recover_interrupted_jobs() -> int:
    """Put jobs interrupted by process shutdown back at the head of the FIFO queue."""
    with connect() as conn:
        cursor = conn.execute(
            """
            UPDATE jobs SET status = 'queued', started_at = NULL, completed_at = NULL,
              error_message = NULL
            WHERE status = 'running'
            """
        )
        return cursor.rowcount


def log_path(task_id: str) -> Path:
    from .config import LOG_DIR

    if Path(DB_PATH).absolute() != Path(config.DB_PATH).absolute():
        return Path(DB_PATH).absolute().parent / "logs" / f"{task_id}.log"
    return LOG_DIR / f"{task_id}.log"
