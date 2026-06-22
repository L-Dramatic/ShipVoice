#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
SHUTDOWN_AFTER_STOP="${SHUTDOWN_AFTER_STOP:-0}"

cd "$PROJECT_DIR"

bash remote/stop_lora_llm.sh "$PROJECT_DIR" || true
bash remote/stop_shipvoice_real_services.sh "$PROJECT_DIR" || true

echo "Full ShipVoice LoRA stack stopped."

if [[ "$SHUTDOWN_AFTER_STOP" == "1" || "$SHUTDOWN_AFTER_STOP" == "true" ]]; then
  echo "Shutting down this GPU machine now."
  sync
  shutdown -h now
fi
