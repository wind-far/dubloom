from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from ..sources import SourceConfig


ProgressCallback = Callable[[int, str], None]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    batch: bool = False
    preview: bool = False
    voice_cloning: bool = False
    original_audio: bool = False


@runtime_checkable
class TranslationProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def translate(
        self,
        asr_file: Path,
        session: Path,
        source: SourceConfig,
        settings: Mapping[str, Any],
    ) -> Path: ...


@runtime_checkable
class TTSProvider(Protocol):
    name: str
    capabilities: ProviderCapabilities

    def synthesize(
        self,
        translation_file: Path,
        vocals_dir: Path,
        session: Path,
        *,
        original_vocals_file: Path | None = None,
        progress_callback: ProgressCallback | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> Path: ...

    def generate(
        self,
        translation_file: Path,
        vocals_dir: Path,
        session: Path,
        progress_callback: ProgressCallback | None = None,
        *,
        original_vocals_file: Path | None = None,
    ) -> Path: ...


class UnsupportedProviderCapability(ValueError):
    pass
