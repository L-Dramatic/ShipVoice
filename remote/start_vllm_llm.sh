#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PORT="${VLLM_PORT:-11434}"
MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-7B-Instruct}"
HOST="${VLLM_HOST:-0.0.0.0}"
GPU_UTIL="${VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
DTYPE="${VLLM_DTYPE:-auto}"
START_TIMEOUT="${START_TIMEOUT:-180}"

wait_for_models() {
  local url="$1"
  local waited=0
  while (( waited < START_TIMEOUT )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "LLM ready: $url"
      return 0
    fi
    sleep 3
    waited=$(( waited + 3 ))
  done
  echo "LLM failed to become ready within ${START_TIMEOUT}s: $url" >&2
  return 1
}

cd "$PROJECT_DIR"
mkdir -p logs

if [[ -f logs/vllm_service.pid ]]; then
  echo "Existing vLLM pid file found. Stop it first:" >&2
  echo "bash remote/stop_vllm_llm.sh \"$PROJECT_DIR\"" >&2
  exit 1
fi

nohup python -m vllm.entrypoints.openai.api_server \
  --host "$HOST" \
  --port "$PORT" \
  --model "$MODEL" \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-model-len "$MAX_LEN" \
  --dtype "$DTYPE" \
  > logs/vllm_service.log 2>&1 &

echo $! > logs/vllm_service.pid
echo "Started vLLM PID: $(cat logs/vllm_service.pid)"
wait_for_models "http://127.0.0.1:${PORT}/v1/models"

cat <<EOF

vLLM is ready.
Base URL: http://<server-ip>:${PORT}/v1
Model: ${MODEL}

Recommended local runtime.real.env values:
SHIPVOICE_LLM_PROVIDER=vllm
SHIPVOICE_OPENAI_BASE_URL=http://<server-ip>:${PORT}/v1
SHIPVOICE_LLM_MODEL=${MODEL}
EOF
