"""The brain — a local LLM via Ollama. Free, private, swappable.

If Ollama isn't running the OS still works: regex fast-paths and skills
metadata keep functioning, and the user gets a clear one-line hint.
"""
from __future__ import annotations

import httpx


class LocalLLM:
    def __init__(self, host: str, model: str, temperature: float = 0.4, max_tokens: int = 1024):
        self.host = host.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def available(self) -> bool:
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=2)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, prompt: str, system: str = "", timeout: float = 120) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": "user", "content": prompt}],
        }
        try:
            r = httpx.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except httpx.HTTPError as e:
            return (
                "Brain offline — start it with `ollama serve` and "
                f"`ollama pull {self.model}`. ({type(e).__name__})"
            )
