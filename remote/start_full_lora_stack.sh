#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
RESTART="${RESTART:-0}"
ASR_PORT="${ASR_PORT:-8001}"
TTS_PORT="${TTS_PORT:-8002}"
LLM_PORT="${LLM_PORT:-11434}"
START_TIMEOUT="${START_TIMEOUT:-3600}"

wait_for_json() {
  local url="$1"
  local name="$2"
  local waited=0
  while (( waited < START_TIMEOUT )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return 0
    fi
    sleep 3
    waited=$(( waited + 3 ))
  done
  echo "$name did not become ready within ${START_TIMEOUT}s: $url" >&2
  return 1
}

on_error() {
  echo "Full ShipVoice LoRA stack failed to start. Stopping started services..." >&2
  bash remote/stop_full_lora_stack.sh "$PROJECT_DIR" || true
}

cd "$PROJECT_DIR"
trap on_error ERR

if [[ "$RESTART" == "1" || "$RESTART" == "true" ]]; then
  bash remote/stop_full_lora_stack.sh "$PROJECT_DIR" || true
fi

echo "[1/2] Start ASR and TTS"
bash remote/start_shipvoice_real_services.sh "$PROJECT_DIR"

echo "[2/2] Start ShipVoice LoRA LLM"
bash remote/start_lora_llm.sh "$PROJECT_DIR"

wait_for_json "http://127.0.0.1:${ASR_PORT}/health" "ASR"
wait_for_json "http://127.0.0.1:${TTS_PORT}/health" "TTS"
wait_for_json "http://127.0.0.1:${LLM_PORT}/health" "ShipVoice LoRA LLM"
wait_for_json "http://127.0.0.1:${LLM_PORT}/v1/models" "ShipVoice LoRA models"

trap - ERR

cat <<EOF

Full ShipVoice LoRA stack is ready.

Remote endpoints:
ASR: http://<server-ip>:${ASR_PORT}/asr
TTS: http://<server-ip>:${TTS_PORT}/tts
LLM: http://<server-ip>:${LLM_PORT}/v1

Local validation after port mapping:
python scripts/check_real_service_chain.py --env-file configs/runtime.real.env --sample-id A001 --require-lora
python scripts/validate_project.py --quick --with-services
EOF
