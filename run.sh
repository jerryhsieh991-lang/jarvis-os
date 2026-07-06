#!/bin/bash
# Start jarvis-os: local brain (if installed) + server + HUD.
set -euo pipefail
cd "$(dirname "$0")"

PORT=$(python3 -c "import json;print(json.load(open('config.json'))['server']['port'])")

# Bring the brain up if Ollama is installed but not running.
if command -v ollama >/dev/null 2>&1; then
  curl -s "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1 || { nohup ollama serve >/tmp/ollama.log 2>&1 & sleep 2; }
fi

echo ">> V.A.U.L.T. online → http://127.0.0.1:${PORT}   (Ctrl-C to stop)"
exec ./.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port "$PORT"
