#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
PORT="${LLM_PORT:-11434}"
MODEL="${LLM_MODEL:-Qwen/Qwen2.5-7B-Instruct}"
HOST="${LLM_HOST:-0.0.0.0}"
MAX_NEW_TOKENS="${LLM_MAX_NEW_TOKENS:-512}"
START_TIMEOUT="${START_TIMEOUT:-3600}"
HF_HOME="${HF_HOME:-/root/autodl-tmp/hf-cache}"

wait_for_models() {
  local url="$1"
  local waited=0
  while (( waited < START_TIMEOUT )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "LLM ready: $url"
      return 0
    fi
    sleep 5
    waited=$(( waited + 5 ))
  done
  echo "LLM failed to become ready within ${START_TIMEOUT}s: $url" >&2
  return 1
}

cd "$PROJECT_DIR"
mkdir -p logs
mkdir -p "$HF_HOME"

if [[ -f logs/transformers_llm.pid ]]; then
  echo "Existing transformers LLM pid file found. Stop it first:" >&2
  echo "bash remote/stop_transformers_llm.sh \"$PROJECT_DIR\"" >&2
  exit 1
fi

nohup env \
  HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  HF_HOME="$HF_HOME" \
  HUGGINGFACE_HUB_CACHE="$HF_HOME/hub" \
  TRANSFORMERS_CACHE="$HF_HOME/transformers" \
  "$PYTHON_BIN" remote/serve_transformers_openai.py \
  --host "$HOST" \
  --port "$PORT" \
  --model "$MODEL" \
  --max-new-tokens "$MAX_NEW_TOKENS" \
  > logs/transformers_llm.log 2>&1 &

echo $! > logs/transformers_llm.pid
echo "Started transformers LLM PID: $(cat logs/transformers_llm.pid)"
wait_for_models "http://127.0.0.1:${PORT}/v1/models"

cat <<EOF

Transformers LLM is ready.
Base URL: http://<server-ip>:${PORT}/v1
Model: ${MODEL}
EOF
