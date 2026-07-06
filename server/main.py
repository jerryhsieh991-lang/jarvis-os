"""jarvis-os server — ties the five pieces together.

Run:  ./run.sh   (or: .venv/bin/uvicorn server.main:app --port 8765)
HUD:  http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import time
from pathlib import Path

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .llm import LocalLLM
from .memory import Vault
from .router import Router
from .skills_loader import load_skills
from .voice.listener import Listener
from .voice.stt import STT
from .voice.tts import TTS

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

_vault_cfg = CONFIG["vault"]
vault = Vault(
    Path(os.environ.get("JARVIS_VAULT", ROOT / _vault_cfg["path"])),
    inbox=_vault_cfg["inbox_folder"],
    reports=_vault_cfg["report_folder"],
    sessions=_vault_cfg["session_folder"],
)
skills = load_skills(ROOT / "skills")
llm = LocalLLM(
    os.environ.get("OLLAMA_HOST", CONFIG["llm"]["host"]),
    CONFIG["llm"]["model"],
    CONFIG["llm"].get("temperature", 0.4),
    CONFIG["llm"].get("max_tokens", 1024),
)
router = Router(llm, vault, skills, CONFIG["assistant"]["name"])
tts = TTS(
    CONFIG["voice"].get("tts_engine", "say"),
    CONFIG["voice"].get("say_voice", ""),
    CONFIG["voice"].get("kokoro_voice", "af_heart"),
)
stt = STT(
    CONFIG["voice"].get("stt_model", "tiny"),
    CONFIG["voice"].get("stt_compute", "int8"),
    CONFIG["assistant"].get("language", "auto"),
)

START_TIME = time.time()
app = FastAPI(title="jarvis-os")


# ---------------------------------------------------------------- WS bus
class Bus:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def emit(self, kind: str, payload: dict) -> None:
        message = json.dumps({"kind": kind, "payload": payload, "ts": time.time()})
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.clients -= dead


bus = Bus()


async def run_command(text: str, speak: bool = True) -> dict:
    await bus.emit("command", {"text": text})
    await bus.emit("voice_state", {"state": "thinking"})
    result = await asyncio.to_thread(router.handle, text)
    await bus.emit("response", {"text": result.text, "lane": result.lane, "saved_to": result.saved_to})
    if speak:
        await bus.emit("voice_state", {"state": "speaking"})
        await asyncio.to_thread(tts.speak, result.text)
    await bus.emit("voice_state", {"state": "idle"})
    return {"text": result.text, "lane": result.lane, "saved_to": result.saved_to}


# ---------------------------------------------------------------- routes
class Command(BaseModel):
    text: str
    speak: bool = False


@app.get("/")
async def index():
    return FileResponse(ROOT / "hud" / "index.html")


@app.get("/api/config")
async def api_config():
    return {"assistant": CONFIG["assistant"], "theme": CONFIG["theme"]}


@app.get("/api/state")
async def api_state():
    mem = vault.stats()
    return {
        "assistant": CONFIG["assistant"]["name"],
        "brain": {"model": CONFIG["llm"]["model"], "online": llm.available()},
        "skills": [{"name": s.name, "description": s.description, "triggers": s.triggers[:6]}
                   for s in skills],
        "memory": mem,
        "metrics": {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": psutil.virtual_memory().percent,
            "uptime_sec": int(time.time() - START_TIME),
            "host": platform.node(),
        },
        "schedule": _read_schedule(),
    }


@app.post("/api/command")
async def api_command(cmd: Command):
    if not cmd.text.strip():
        return JSONResponse({"error": "empty"}, status_code=400)
    return await run_command(cmd.text.strip(), speak=cmd.speak)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    bus.clients.add(ws)
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if text := data.get("command", "").strip():
                asyncio.create_task(run_command(text, speak=data.get("speak", False)))
    except WebSocketDisconnect:
        pass
    finally:
        bus.clients.discard(ws)


def _read_schedule() -> list[str]:
    path = vault.root / "Schedule.md"
    if not path.exists():
        return []
    lines = [l.strip("- ").strip() for l in path.read_text(encoding="utf-8").splitlines()
             if l.strip().startswith("-")]
    return lines[:8]


# ------------------------------------------------------------- lifecycle
listener: Listener | None = None


@app.on_event("startup")
async def startup():
    global listener
    if CONFIG["voice"].get("mic_enabled", True):
        listener = Listener(
            stt,
            CONFIG["assistant"]["wake_word"],
            on_event=bus.emit,
            on_command=lambda text: run_command(text, speak=True),
            vad_threshold=CONFIG["voice"].get("vad_threshold", 0.015),
            silence_sec=CONFIG["voice"].get("utterance_silence_sec", 0.9),
            max_utterance_sec=CONFIG["voice"].get("max_utterance_sec", 20),
        )
        asyncio.create_task(listener.run())


@app.on_event("shutdown")
async def shutdown():
    if listener:
        listener.stop()


app.mount("/hud", StaticFiles(directory=ROOT / "hud"), name="hud")
