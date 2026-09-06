from __future__ import annotations

import json
from typing import Any, Mapping

from .base import (
    ProviderCapabilities,
    TTSProvider,
    TranslationProvider,
    UnsupportedProviderCapability,
)
from .openai_compatible import OpenAICompatibleTranslationProvider
from .voxcpm2 import VoxCPM2TTSProvider


_TRANSLATION_PROVIDERS: dict[str, TranslationProvider] = {
    OpenAICompatibleTranslationProvider.name: OpenAICompatibleTranslationProvider(),
}
_TTS_PROVIDERS: dict[str, TTSProvider] = {
    VoxCPM2TTSProvider.name: VoxCPM2TTSProvider(),
}


def register_translation_provider(provider: TranslationProvider) -> None:
    _TRANSLATION_PROVIDERS[provider.name] = provider


def register_tts_provider(provider: TTSProvider) -> None:
    _TTS_PROVIDERS[provider.name] = provider


def get_translation_provider(name: str = "openai-compatible") -> TranslationProvider:
    try:
        return _TRANSLATION_PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown translation provider: {name}") from exc


def get_tts_provider(name: str = "voxcpm2") -> TTSProvider:
    try:
        return _TTS_PROVIDERS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown TTS provider: {name}") from exc


def _task_snapshot(task: Mapping[str, Any] | None) -> dict[str, Any]:
    if not task:
        return {}
    raw = task.get("config_snapshot")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _profile_for(
    kind: str,
    task: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if profile is not None:
        return profile
    if not task:
        return None
    profile_id = task.get(f"{kind}_profile_id")
    if not profile_id:
        return None
    from .. import database

    return database.get_provider_profile_credentials(str(profile_id))


def resolve_translation_provider(
    task: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
) -> TranslationProvider:
    resolved = _profile_for("translation", task, profile)
    snapshot = _task_snapshot(task)
    name = str(
        (resolved or {}).get("provider")
        or snapshot.get("translation_provider")
        or "openai-compatible"
    )
    return get_translation_provider(name)


def resolve_tts_provider(
    task: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
) -> TTSProvider:
    resolved = _profile_for("tts", task, profile)
    snapshot = _task_snapshot(task)
    name = str(
        (resolved or {}).get("provider")
        or snapshot.get("tts_provider")
        or "voxcpm2"
    )
    return get_tts_provider(name)


def list_provider_capabilities() -> dict[str, dict[str, dict[str, Any]]]:
    def describe(items: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "name": provider.name,
                "capabilities": {
                    field: getattr(provider.capabilities, field)
                    for field in provider.capabilities.__dataclass_fields__
                },
            }
            for name, provider in items.items()
        }

    return {
        "translation": describe(_TRANSLATION_PROVIDERS),
        "tts": describe(_TTS_PROVIDERS),
    }


__all__ = [
    "ProviderCapabilities",
    "TranslationProvider",
    "TTSProvider",
    "UnsupportedProviderCapability",
    "OpenAICompatibleTranslationProvider",
    "VoxCPM2TTSProvider",
    "register_translation_provider",
    "register_tts_provider",
    "get_translation_provider",
    "get_tts_provider",
    "resolve_translation_provider",
    "resolve_tts_provider",
    "list_provider_capabilities",
]
