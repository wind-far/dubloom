from __future__ import annotations

from pathlib import Path

from backend.app.providers import (
    OpenAICompatibleTranslationProvider,
    VoxCPM2TTSProvider,
    get_translation_provider,
    get_tts_provider,
    resolve_translation_provider,
    resolve_tts_provider,
)
from backend.app.sources import detect_source


def test_default_provider_registry_and_capabilities():
    translation = get_translation_provider()
    tts = get_tts_provider()

    assert isinstance(translation, OpenAICompatibleTranslationProvider)
    assert translation.capabilities.batch is True
    assert isinstance(tts, VoxCPM2TTSProvider)
    assert tts.capabilities.preview is True
    assert tts.capabilities.voice_cloning is True


def test_openai_provider_delegates_without_changing_artifact(monkeypatch, tmp_path):
    expected = tmp_path / "metadata" / "translation.zh.json"
    received = {}

    def fake_translate(asr_file, session, settings, source):
        received.update(
            asr_file=asr_file,
            session=session,
            settings=settings,
            source=source,
        )
        return expected

    monkeypatch.setattr(
        "backend.app.adapters.openai_translate.translate_asr",
        fake_translate,
    )
    source = detect_source("https://www.youtube.com/watch?v=abcdefghijk")
    result = get_translation_provider().translate(
        tmp_path / "asr.json",
        tmp_path,
        source,
        {"model": "test-model", "translate_concurrency": 4},
    )

    assert result == expected
    assert received["settings"] == {
        "model": "test-model",
        "translate_concurrency": "4",
    }


def test_voxcpm_provider_delegates_without_changing_artifact(monkeypatch, tmp_path):
    expected = tmp_path / "segments" / "tts"
    calls = []

    def fake_generate(
        translation_file,
        vocals_dir,
        session,
        progress_callback=None,
        *,
        original_vocals_file=None,
    ):
        calls.append(
            (
                translation_file,
                vocals_dir,
                session,
                progress_callback,
                original_vocals_file,
            )
        )
        return expected

    monkeypatch.setattr(
        "backend.app.providers.voxcpm2.voxcpm.generate_tts",
        fake_generate,
    )
    callback = lambda _progress, _message: None
    result = get_tts_provider().generate(
        tmp_path / "translation.json",
        tmp_path / "vocals",
        tmp_path,
        callback,
        original_vocals_file=tmp_path / "vocals.wav",
    )

    assert result == expected
    assert calls[0][3] is callback
    assert calls[0][4] == tmp_path / "vocals.wav"


def test_provider_resolution_uses_profile_provider_name():
    assert isinstance(
        resolve_translation_provider(profile={"provider": "openai-compatible"}),
        OpenAICompatibleTranslationProvider,
    )
    assert isinstance(
        resolve_tts_provider(profile={"provider": "voxcpm2"}),
        VoxCPM2TTSProvider,
    )
