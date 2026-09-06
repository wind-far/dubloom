from __future__ import annotations

import sqlite3

import pytest

from backend.app import database


@pytest.fixture
def review_db(monkeypatch, tmp_path):
    path = tmp_path.resolve() / "review.sqlite"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    return path


def test_versioned_migration_preserves_legacy_tasks(monkeypatch, tmp_path):
    path = tmp_path.resolve() / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE tasks (
              id TEXT PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL,
              current_stage TEXT, session_path TEXT, final_video_path TEXT,
              error_message TEXT, created_at TEXT NOT NULL, started_at TEXT,
              completed_at TEXT
            );
            INSERT INTO tasks (id, url, status, created_at)
            VALUES ('legacy', 'local://legacy', 'succeeded', '2025-01-01T00:00:00+00:00');
            """
        )
    monkeypatch.setattr(database, "DB_PATH", path)

    database.init_db()

    task = database.get_task("legacy")
    assert task is not None
    assert task["review_mode"] == "none"
    assert task["result_stale"] == 0
    with database.connect() as conn:
        assert [row["version"] for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2, 3]


def test_profiles_hide_secrets_and_segments_use_optimistic_revision(review_db):
    task_id = database.create_task(
        "local://test",
        review_mode="required",
        config_snapshot={"translation_provider": "openai-compatible"},
    )
    profile_id = database.create_provider_profile(
        "translation",
        "Local gateway",
        "openai-compatible",
        model="test-model",
        config={"base_url": "http://localhost:8000/v1"},
        secrets={"api_key": "never-return-this"},
    )
    public = database.get_provider_profile(profile_id)
    internal = database.get_provider_profile_credentials(profile_id)

    assert public is not None and "secrets" not in public
    assert "secret_config_json" not in public
    assert public["has_secrets"] is True
    assert internal is not None and internal["secrets"]["api_key"] == "never-return-this"

    segments = database.replace_task_segments(
        task_id,
        [
            {
                "src": "hello",
                "dst": "你好",
                "start_time": 0,
                "end_time": 1000,
                "speaker": "1",
                "audio_mode": "tts",
            }
        ],
    )
    segment = segments[0]
    changed = database.update_task_segment(
        task_id,
        segment["id"],
        segment["revision"],
        translated_text="您好",
    )
    assert changed is not None
    assert changed["revision"] == segment["revision"] + 1
    assert changed["dirty"] is True
    assert database.get_task(task_id)["result_stale"] == 1
    with pytest.raises(database.SegmentRevisionConflict):
        database.update_task_segment(
            task_id,
            segment["id"],
            segment["revision"],
            translated_text="旧客户端修改",
        )


def test_jobs_are_claimed_fifo_and_interrupted_jobs_recover(review_db):
    first_task = database.create_task("local://first")
    second_task = database.create_task("local://second")
    first_job = database.create_job(first_task, "segment_preview", {"segment_id": "one"})
    second_job = database.create_job(second_task, "dirty_render")

    claimed_first = database.claim_next_job()
    assert claimed_first is not None
    assert claimed_first["id"] == first_job
    assert claimed_first["payload"] == {"segment_id": "one"}
    assert database.recover_interrupted_jobs() == 1

    claimed_again = database.claim_next_job()
    assert claimed_again is not None and claimed_again["id"] == first_job
    assert claimed_again["attempts"] == 2
    assert database.complete_job(first_job) is True
    assert database.get_job(first_job)["progress"] == 100
    claimed_second = database.claim_next_job()
    assert claimed_second is not None and claimed_second["id"] == second_job
    assert database.fail_job(second_job, "render failed") is True
    assert database.get_job(second_job)["error_message"] == "render failed"


def test_video_task_identity_includes_review_and_provider_configuration(review_db):
    assert database.video_task_id("video1", "both") == "video1"
    reviewed = database.video_task_id("video1", "both", "required")
    profiled = database.video_task_id(
        "video1",
        "both",
        "required",
        "translation-profile",
        "tts-profile",
    )
    assert reviewed.startswith("video1-cfg-")
    assert profiled.startswith("video1-cfg-")
    assert reviewed != profiled
