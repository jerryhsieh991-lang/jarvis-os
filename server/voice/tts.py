"""Text-to-speech — two free engines:

- "say"    : macOS built-in. Zero install, works immediately.
- "kokoro" : open-source neural TTS (optional: pip install kokoro-onnx and
             download the free model files; see setup.sh --with-kokoro).
"""
from __future__ import annotations

import shutil
import subprocess
import threading


class TTS:
    def __init__(self, engine: str = "say", say_voice: str = "", kokoro_voice: str = "af_heart"):
        self.engine = engine
        self.say_voice = say_voice
        self.kokoro_voice = kokoro_voice
        self._kokoro = None
        self._lock = threading.Lock()  # one voice at a time

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            if self.engine == "kokoro":
                try:
                    self._speak_kokoro(text)
                    return
                except Exception:
                    pass  # fall back to say
            self._speak_say(text)

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
            self._kokoro = Kokoro("models/kokoro-v1.0.onnx", "models/voices-v1.0.bin")
        samples, sample_rate = self._kokoro.create(text, voice=self.kokoro_voice, speed=1.0)
        sd.play(samples, sample_rate)
        sd.wait()
