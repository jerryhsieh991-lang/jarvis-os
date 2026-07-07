"""Text-to-speech — two free engines, picked per utterance:

- "kokoro" : open-source neural TTS (models fetched by `setup.sh --with-kokoro`).
             Used for Latin-script text when available.
- "say"    : macOS built-in. Zero install, and the fallback for everything —
             including CJK text, which the bundled Kokoro voices don't cover well.

`speak()` is called per *sentence* by the streaming pipeline, so the first
words play while the model is still generating the rest.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")
_MODELS = Path(__file__).resolve().parents[2] / "models"


class TTS:
    def __init__(self, engine: str = "say", say_voice: str = "", kokoro_voice: str = "af_heart"):
        self.engine = engine
        self.say_voice = say_voice
        self.kokoro_voice = kokoro_voice
        self._kokoro = None
        self._kokoro_broken = False
        self._lock = threading.Lock()  # one voice at a time, sentences queue up

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            if self._use_kokoro(text):
                try:
                    self._speak_kokoro(text)
                    return
                except Exception:
                    self._kokoro_broken = True  # don't retry every sentence
            self._speak_say(text)

    def _use_kokoro(self, text: str) -> bool:
        return (
            self.engine == "kokoro"
            and not self._kokoro_broken
            and not _CJK_RE.search(text)
            and (_MODELS / "kokoro-v1.0.onnx").exists()
        )

    # -- engines --------------------------------------------------------
    def _speak_say(self, text: str) -> None:
        if not shutil.which("say"):
            return  # non-mac host: stay silent rather than crash
        cmd = ["say"]
        if self.say_voice:
            cmd += ["-v", self.say_voice]
        subprocess.run(cmd + [text[:2000]], check=False, timeout=120)

    def _speak_kokoro(self, text: str) -> None:
        import sounddevice as sd

        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(_MODELS / "kokoro-v1.0.onnx"), str(_MODELS / "voices-v1.0.bin"))
        samples, sample_rate = self._kokoro.create(text, voice=self.kokoro_voice, speed=1.0)
        sd.play(samples, sample_rate)
        sd.wait()
