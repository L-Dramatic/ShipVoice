#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
ASR_PORT="${ASR_PORT:-8001}"
TTS_PORT="${TTS_PORT:-8002}"
ASR_MODEL="${ASR_MODEL:-iic/SenseVoiceSmall}"
ASR_DEVICE="${ASR_DEVICE:-cuda:0}"
EDGE_TTS_VOICE="${EDGE_TTS_VOICE:-zh-CN-XiaoxiaoNeural}"
GTTS_LANG="${GTTS_LANG:-zh-CN}"
TTS_BACKEND="${TTS_BACKEND:-edge}"
CHATTTS_SOURCE="${CHATTTS_SOURCE:-huggingface}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
START_TIMEOUT="${START_TIMEOUT:-120}"

wait_for_health() {
  local url="$1"
  local name="$2"
  local waited=0
  while (( waited < START_TIMEOUT )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name health ready: $url"
      return 0
    fi
    sleep 2
    waited=$(( waited + 2 ))
  done
  echo "$name failed to become healthy within ${START_TIMEOUT}s: $url" >&2
  return 1
}

cd "$PROJECT_DIR"
mkdir -p logs

if [[ -f logs/asr_service.pid ]] || [[ -f logs/tts_service.pid ]]; then
  echo "Existing pid files found. Stop the previous services first:" >&2
  echo "bash remote/stop_shipvoice_real_services.sh \"$PROJECT_DIR\"" >&2
  exit 1
fi

echo "[1/2] Start FunASR ASR service on :$ASR_PORT"
nohup "$PYTHON_BIN" remote/serve_funasr_asr.py \
  --host 0.0.0.0 \
  --port "$ASR_PORT" \
  --model "$ASR_MODEL" \
  --device "$ASR_DEVICE" \
  > logs/asr_service.log 2>&1 &
echo $! > logs/asr_service.pid

echo "[2/2] Start TTS service on :$TTS_PORT (backend=$TTS_BACKEND)"
if [[ "$TTS_BACKEND" == "chattts" ]]; then
  nohup env HF_ENDPOINT="$HF_ENDPOINT" CHATTTS_SOURCE="$CHATTTS_SOURCE" "$PYTHON_BIN" remote/serve_chattts_tts.py \
    --host 0.0.0.0 \
    --port "$TTS_PORT" \
    > logs/tts_service.log 2>&1 &
elif [[ "$TTS_BACKEND" == "gtts" ]]; then
  nohup "$PYTHON_BIN" remote/serve_gtts_tts.py \
    --host 0.0.0.0 \
    --port "$TTS_PORT" \
    --lang "$GTTS_LANG" \
    > logs/tts_service.log 2>&1 &
else
  nohup "$PYTHON_BIN" remote/serve_edge_tts.py \
    --host 0.0.0.0 \
    --port "$TTS_PORT" \
    --voice "$EDGE_TTS_VOICE" \
    > logs/tts_service.log 2>&1 &
fi
echo $! > logs/tts_service.pid

echo "Services started."
echo "ASR PID: $(cat logs/asr_service.pid)"
echo "TTS PID: $(cat logs/tts_service.pid)"

wait_for_health "http://127.0.0.1:${ASR_PORT}/health" "ASR"
wait_for_health "http://127.0.0.1:${TTS_PORT}/health" "TTS"

cat <<EOF

Real service stack is ready.
ASR endpoint: http://<server-ip>:${ASR_PORT}/asr
TTS endpoint: http://<server-ip>:${TTS_PORT}/tts

Recommended next step on your local machine:
python scripts/check_real_service_chain.py --env-file configs/runtime.real.env --sample-id A001 --require-lora
EOF
