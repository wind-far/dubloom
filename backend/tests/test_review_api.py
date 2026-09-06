from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import auth, config, database, main, pipeline, review, worker
from backend.tests.conftest import TEST_AUTH_PASSWORD


def _configure(monkeypatch, tmp_path) -> None:
    workfolder = tmp_path / "workfolder"
    workfolder.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.sqlite")
    monkeypatch.setattr(config, "WORKFOLDER", workfolder)
    monkeypatch.setattr(config, "LOG_DIR", logs)
    monkeypatch.setattr(main, "WORKFOLDER", workfolder)
    monkeypatch.setattr(pipeline, "WORKFOLDER", workfolder)
    monkeypatch.setattr(worker, "start", lambda runner: None)
    database.init_db()


def _client() -> TestClient:
    client = TestClient(main.app)
    response = client.post("/api/auth/login", json={"password": TEST_AUTH_PASSWORD})
    assert response.status_code == 200
    client.headers[auth.CSRF_HEADER_NAME] = response.json()["csrf_token"]
    return client


def _review_task(tmp_path, *, status: str = "awaiting_review") -> tuple[str, object]:
    task_id = database.create_task(
        "https://www.youtube.com/watch?v=reviewtask1",
        task_id="reviewtask1",
        review_mode="required",
    )
    session = tmp_path / "workfolder" / "reviewtask1"
    (session / "metadata").mkdir(parents=True)
    (session / "media").mkdir()
    artifact = session / "metadata" / "translation.zh.json"
    artifact.write_text(
        json.dumps(
            {
                "translation": [
                    {
                        "src": "Hello",
                        "dst": "你好",
                        "audio_mode": "tts",
                        "start_time": 0,
                        "end_time": 1000,
                        "speaker": "1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    database.update_task(task_id, status=status, session_path=str(session))
    segments = review.import_translation_artifact(task_id, artifact)
    return task_id, segments[0]


def test_segments_edit_conflict_and_approval(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    task_id, original = _review_task(tmp_path)
    monkeypatch.setattr(main, "_ensure_runtime_ready", lambda: None)
    monkeypatch.setattr(
        main.worker,
        "enqueue_job",
        lambda task_id, job_type, payload=None: database.create_job(task_id, job_type, payload),
    )
    client = _client()

    listing = client.get(f"/api/tasks/{task_id}/segments")
    assert listing.status_code == 200
    assert listing.json()["segments"][0]["translated_text"] == "你好"

    edited = client.patch(
        f"/api/tasks/{task_id}/segments/{original['id']}",
        json={"expected_revision": 1, "translated_text": "您好"},
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2

    conflict = client.patch(
        f"/api/tasks/{task_id}/segments/{original['id']}",
        json={"expected_revision": 1, "translated_text": "过期修改"},
    )
    assert conflict.status_code == 409

    approved = client.post(f"/api/tasks/{task_id}/review/approve")
    assert approved.status_code == 202
    assert approved.json()["status"] == "queued"
    assert approved.json()["review_approved_at"]
    artifact = review.translation_path(database.get_task(task_id))
    assert json.loads(artifact.read_text(encoding="utf-8"))["translation"][0]["dst"] == "您好"


def test_provider_profile_api_never_returns_secrets(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = _client()

    created = client.post(
        "/api/provider-profiles",
        json={
            "kind": "translation",
            "name": "private",
            "provider": "openai-compatible",
            "model": "test-model",
            "config": {"base_url": "https://example.com/v1"},
            "secrets": {"api_key": "sk-do-not-return"},
        },
    )
    assert created.status_code == 201
    assert created.json()["has_secrets"] is True
    assert "sk-do-not-return" not in created.text

    profiles = client.get("/api/provider-profiles")
    assert profiles.status_code == 200
    assert profiles.json()[0]["has_secrets"] is True
    assert "sk-do-not-return" not in profiles.text


def test_segment_audio_rejects_paths_outside_task_session(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    task_id, segment = _review_task(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"not-a-real-wave")
    database.set_segment_preview(task_id, segment["id"], "ready", str(outside))

    with pytest.raises(PermissionError, match="outside the task session"):
        review.safe_segment_audio(task_id, segment["id"], "preview")


def test_provider_runtime_merges_profile_config_secret_and_task_snapshot(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    profile_id = database.create_provider_profile(
        "translation",
        "custom",
        "openai-compatible",
        "profile-model",
        {"base_url": "https://profile.example/v1", "translate_concurrency": "8"},
        {"api_key": "sk-secret"},
    )
    task_id = database.create_task(
        "https://www.youtube.com/watch?v=runtimecfg1",
        task_id="runtimecfg1",
        translation_profile_id=profile_id,
        config_snapshot={
            "translation": {
                "provider": "openai-compatible",
                "model": "snapshot-model",
                "config": {"base_url": "https://snapshot.example/v1"},
            }
        },
    )

    provider, settings = review.provider_runtime(database.get_task(task_id), "translation")

    assert provider == "openai-compatible"
    assert settings == {
        "base_url": "https://snapshot.example/v1",
        "translate_concurrency": "8",
        "api_key": "sk-secret",
        "model": "snapshot-model",
    }

    override_id = database.create_provider_profile(
        "translation",
        "row override",
        "openai-compatible",
        "override-model",
        {"base_url": "https://override.example/v1", "translate_concurrency": "2"},
        {"api_key": "sk-override"},
    )
    override_provider, override_settings = review.provider_runtime(
        database.get_task(task_id),
        "translation",
        profile_id=override_id,
    )
    assert override_provider == "openai-compatible"
    assert override_settings == {
        "base_url": "https://override.example/v1",
        "translate_concurrency": "2",
        "api_key": "sk-override",
        "model": "override-model",
    }


def test_pipeline_stops_at_review_gate(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    task_id = database.create_task(
        "https://www.youtube.com/watch?v=reviewgate1",
        task_id="reviewgate1",
        review_mode="required",
    )
    session = tmp_path / "workfolder" / task_id
    (session / "metadata").mkdir(parents=True)

    def stage_noop(self, task):
        self.artifacts.session = session
        database.update_task(self.task_id, session_path=str(session))

    def translate(self, task):
        stage_noop(self, task)
        artifact = session / "metadata" / "translation.zh.json"
        artifact.write_text(
            '{"translation":[{"src":"Hi","dst":"嗨","audio_mode":"tts",'
            '"start_time":0,"end_time":800,"speaker":"1"}]}',
            encoding="utf-8",
        )
        self.artifacts.translation_file = artifact
        review.import_translation_artifact(self.task_id, artifact)

    for name in ("_download", "_separate", "_asr", "_asr_fix"):
        monkeypatch.setattr(pipeline.PipelineRunner, name, stage_noop)
    monkeypatch.setattr(pipeline.PipelineRunner, "_translate", translate)
    monkeypatch.setattr(pipeline, "validate_runtime_device", lambda: None)
    monkeypatch.setattr(pipeline, "device_plan_summary", lambda: "test")

    pipeline.PipelineRunner(task_id).run()

    task = database.get_task(task_id)
    assert task["status"] == "awaiting_review"
    assert task["current_stage"] == "translate"
    assert [stage["status"] for stage in task["stages"][:5]] == ["succeeded"] * 5
    assert [stage["status"] for stage in task["stages"][5:]] == ["pending"] * 4
