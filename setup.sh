#!/bin/bash
# jarvis-os one-command install — 100% free stack, no API keys.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3.12}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

echo ">> Python venv ($($PY --version))"
[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

if [ "${1:-}" = "--with-kokoro" ]; then
  echo ">> Optional: Kokoro neural TTS (~340 MB of free model files)"
  ./.venv/bin/pip install -q kokoro-onnx
  mkdir -p models
  [ -f models/kokoro-v1.0.onnx ] || curl -L -o models/kokoro-v1.0.onnx \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  [ -f models/voices-v1.0.bin ] || curl -L -o models/voices-v1.0.bin \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
  echo '   set "tts_engine": "kokoro" in config.json to enable.'
fi

echo ">> Brain check (Ollama — free local LLM)"
if command -v ollama >/dev/null 2>&1; then
  MODEL=$(python3 -c "import json;print(json.load(open('config.json'))['llm']['model'])")
  ollama list | grep -q "${MODEL%%:*}" || { echo "   pulling $MODEL…"; ollama pull "$MODEL"; }
else
  echo "   Ollama not found. Install it free:  brew install ollama   (then re-run setup)"
  echo "   The OS still runs without it — regex commands + HUD work; chat answers will hint."
fi

[ -f .env ] || cp .env.example .env
echo
echo "OK — start it with:  ./run.sh   →  http://127.0.0.1:8765"
