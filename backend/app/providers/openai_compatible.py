from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..sources import SourceConfig
from .base import ProviderCapabilities


class OpenAICompatibleTranslationProvider:
    """Translation provider backed by the existing OpenAI-compatible adapter."""

    name = "openai-compatible"
    capabilities = ProviderCapabilities(batch=True)

    def translate(
        self,
        asr_file: Path,
        session: Path,
        source: SourceConfig,
        settings: Mapping[str, Any],
    ) -> Path:
        # Resolve lazily so existing tests and deployments that replace the
        # adapter module keep working exactly as before this wrapper existed.
        from importlib import import_module

        openai_translate = import_module("backend.app.adapters.openai_translate")
        return openai_translate.translate_asr(
            asr_file,
            session,
            {key: str(value) for key, value in settings.items()},
            source,
        )

    def list_models(self, *, base_url: str, api_key: str) -> list[str]:
        from importlib import import_module

        openai_translate = import_module("backend.app.adapters.openai_translate")
        return openai_translate.list_models(base_url=base_url, api_key=api_key)
