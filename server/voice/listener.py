"""The always-on ear — mic loop with energy VAD and a wake word.

Flow: idle → (speech energy) → record until silence → STT → if the
utterance contains the wake word (or follows a wake within 8 s), route it
as a command. Everything stays on this machine.

First run: macOS will ask for Microphone permission for your terminal.
No mic / no permission? The HUD's text box and /api/command still work.
"""
from __future__ import annotations

import asyncio
import time

import numpy as np

SAMPLE_RATE = 16000
BLOCK = 1600  # 100 ms


class Listener:
    def __init__(self, stt, wake_word: str, on_event, on_command,
                 vad_threshold: float = 0.015, silence_sec: float = 0.9,
                 max_utterance_sec: float = 20.0):
        self.stt = stt
        self.wake_word = wake_word.lower()
        self.on_event = on_event          # async fn(kind, payload) → HUD bus
        self.on_command = on_command      # async fn(text) → router
        self.vad_threshold = vad_threshold
        self.silence_sec = silence_sec
        self.max_utterance_sec = max_utterance_sec
        self._awake_until = 0.0
        self._running = False

    async def run(self) -> None:
        try:
            import sounddevice as sd
        except OSError as e:  # PortAudio missing
            await self.on_event("voice_error", {"detail": f"audio backend unavailable: {e}"})
            return

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=200)

        def _callback(indata, _frames, _time, status):
            if status:
                pass
            block = indata[:, 0].copy()
            try:
                loop.call_soon_threadsafe(queue.put_nowait, block)
            except RuntimeError:
                pass

        self._running = True
        try:
            stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                    blocksize=BLOCK, dtype="float32", callback=_callback)
            stream.start()
        except Exception as e:  # no device / no permission
            await self.on_event("voice_error", {"detail": str(e)})
            return

        await self.on_event("voice_state", {"state": "idle"})
        buffer: list[np.ndarray] = []
        silent_blocks = 0
        recording = False

        try:
            while self._running:
                block = await queue.get()
                level = float(np.sqrt(np.mean(block**2)))

                if not recording:
                    if level >= self.vad_threshold:
                        recording = True
                        buffer = [block]
                        silent_blocks = 0
                        await self.on_event("voice_state", {"state": "listening"})
                    continue

                buffer.append(block)
                silent_blocks = silent_blocks + 1 if level < self.vad_threshold else 0
                too_long = len(buffer) * BLOCK / SAMPLE_RATE > self.max_utterance_sec
                done = silent_blocks * BLOCK / SAMPLE_RATE >= self.silence_sec

                if done or too_long:
                    recording = False
                    audio = np.concatenate(buffer)
                    buffer = []
                    await self.on_event("voice_state", {"state": "thinking"})
                    text = await asyncio.to_thread(self.stt.transcribe_array, audio, SAMPLE_RATE)
                    await self._dispatch(text)
                    await self.on_event("voice_state", {"state": "idle"})
        finally:
            stream.stop()
            stream.close()

    async def _dispatch(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        lowered = text.lower()
        await self.on_event("transcript", {"text": text})

        now = time.monotonic()
        if self.wake_word in lowered:
            self._awake_until = now + 8.0
            command = _strip_wake(lowered, text, self.wake_word)
            if command:
                await self.on_command(command)
            else:
                await self.on_event("wake", {})
        elif now < self._awake_until:
            self._awake_until = 0.0
            await self.on_command(text)

    def stop(self) -> None:
        self._running = False


def _strip_wake(lowered: str, original: str, wake_word: str) -> str:
    idx = lowered.find(wake_word)
    command = original[idx + len(wake_word):]
    return command.strip(" ,.!?，。！？") or ""
