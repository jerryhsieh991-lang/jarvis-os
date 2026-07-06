"""Speech-to-text — faster-whisper, fully local and free.

The model (default: tiny, ~75 MB) downloads once on first use and is cached
in ~/.cache/huggingface. `language="auto"` handles mixed 中文/English.
"""
from __future__ import annotations

import numpy as np


class STT:
    def __init__(self, model_size: str = "tiny", compute_type: str = "int8", language: str = "auto"):
        self.model_size = model_size
        self.compute_type = compute_type
        self.language = None if language == "auto" else language
        self._model = None  # lazy — first call pays the load, not import

    @property
    def model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device="cpu", compute_type=self.compute_type)
        return self._model

    def transcribe_array(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe a mono float32 numpy array in [-1, 1]."""
        if sample_rate != 16000:
            # cheap linear resample — fine for speech
            target = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio), target, endpoint=False),
                np.arange(len(audio)),
                audio,
            ).astype(np.float32)
        segments, _info = self.model.transcribe(audio, language=self.language, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe_file(self, path: str) -> str:
        segments, _info = self.model.transcribe(path, language=self.language, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
