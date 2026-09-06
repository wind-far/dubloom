from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..adapters import voxcpm
from .base import ProgressCallback, ProviderCapabilities


class VoxCPM2TTSProvider:
    """TTS provider backed by the existing local VoxCPM2 adapter."""

    name = "voxcpm2"
    capabilities = ProviderCapabilities(
        batch=True,
        preview=True,
        voice_cloning=True,
        original_audio=True,
    )

    def synthesize(
        self,
        translation_file: Path,
        vocals_dir: Path,
        session: Path,
        *,
        original_vocals_file: Path | None = None,
        progress_callback: ProgressCallback | None = None,
        settings: Mapping[str, Any] | None = None,
    ) -> Path:
        kwargs: dict[str, Any] = {
            "progress_callback": progress_callback,
            "original_vocals_file": original_vocals_file,
        }
        if settings:
            kwargs["settings"] = settings
        return voxcpm.generate_tts(
            translation_file,
            vocals_dir,
            session,
            **kwargs,
        )

    def release(self) -> bool:
        return voxcpm.release_model()

    def generate(
        self,
        translation_file: Path,
        vocals_dir: Path,
        session: Path,
        progress_callback: ProgressCallback | None = None,
        *,
        original_vocals_file: Path | None = None,
    ) -> Path:
        return self.synthesize(
            translation_file,
            vocals_dir,
            session,
            progress_callback=progress_callback,
            original_vocals_file=original_vocals_file,
        )
