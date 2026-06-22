#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
PORT="${LLM_PORT:-11434}"
HOST="${LLM_HOST:-0.0.0.0}"
BASE_MODEL="${LLM_BASE_MODEL:-Qwen/Qwen2.5-7B-Instruct}"
ADAPTER_DIR="${LLM_ADAPTER_DIR:-$PROJECT_DIR/outputs/qwen_lora_shipvoice_expanded}"
SERVED_MODEL_NAME="${LLM_SERVED_MODEL_NAME:-shipvoice-qwen2.5-7b-lora}"
MAX_NEW_TOKENS="${LLM_MAX_NEW_TOKENS:-512}"
DTYPE="${LLM_DTYPE:-auto}"
START_TIMEOUT="${START_TIMEOUT:-3600}"
HF_HOME="${HF_HOME:-/root/autodl-tmp/hf-cache}"
LOAD_IN_4BIT="${LLM_LOAD_IN_4BIT:-1}"

wait_for_lora_health() {
  local url="$1"
  local waited=0
  while (( waited < START_TIMEOUT )); do
    if "$PYTHON_BIN" - "$url" <<'PY' >/dev/null 2>&1; then
import json
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=5) as response:
    data = json.loads(response.read().decode("utf-8"))
assert data.get("ok") is True
assert data.get("adapter_loaded") is True
assert data.get("served_model")
PY
      echo "LoRA LLM ready: $url"
      return 0
    fi
    sleep 5
    waited=$(( waited + 5 ))
  done
  echo "LoRA LLM failed to become ready within ${START_TIMEOUT}s: $url" >&2
  return 1
}

cd "$PROJECT_DIR"
mkdir -p logs
mkdir -p "$HF_HOME"

if [[ ! -d "$ADAPTER_DIR" ]]; then
  echo "LoRA adapter directory not found: $ADAPTER_DIR" >&2
  exit 1
fi
if [[ ! -f "$ADAPTER_DIR/adapter_config.json" ]]; then
  echo "LoRA adapter_config.json not found: $ADAPTER_DIR/adapter_config.json" >&2
  exit 1
fi

if [[ -f logs/lora_llm.pid ]]; then
  echo "Existing LoRA LLM pid file found. Stop it first:" >&2
  echo "bash remote/stop_lora_llm.sh \"$PROJECT_DIR\"" >&2
  exit 1
fi

extra_args=()
if [[ "$LOAD_IN_4BIT" == "1" || "$LOAD_IN_4BIT" == "true" ]]; then
  extra_args+=(--load-in-4bit)
fi

nohup env \
  HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
  HF_HOME="$HF_HOME" \
  HUGGINGFACE_HUB_CACHE="$HF_HOME/hub" \
  TRANSFORMERS_CACHE="$HF_HOME/transformers" \
  "$PYTHON_BIN" remote/serve_transformers_openai.py \
  --host "$HOST" \
  --port "$PORT" \
  --model-path "$BASE_MODEL" \
  --adapter-path "$ADAPTER_DIR" \
  --served-model-name "$SERVED_MODEL_NAME" \
  --require-adapter \
  --max-new-tokens "$MAX_NEW_TOKENS" \
  --dtype "$DTYPE" \
  "${extra_args[@]}" \
  > logs/lora_llm.log 2>&1 &

echo $! > logs/lora_llm.pid
echo "Started ShipVoice LoRA LLM PID: $(cat logs/lora_llm.pid)"
wait_for_lora_health "http://127.0.0.1:${PORT}/health"

cat <<EOF

ShipVoice LoRA LLM is ready.
Base URL: http://<server-ip>:${PORT}/v1
Model: ${SERVED_MODEL_NAME}
Adapter: ${ADAPTER_DIR}

Recommended runtime values:
SHIPVOICE_LLM_PROVIDER=openai_compatible
SHIPVOICE_OPENAI_BASE_URL=http://<server-ip>:${PORT}/v1
SHIPVOICE_LLM_MODEL=${SERVED_MODEL_NAME}
SHIPVOICE_REQUIRE_LORA=1
EOF
