#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
cd "$PROJECT_DIR"

pid_file="logs/vllm_service.pid"
if [[ ! -f "$pid_file" ]]; then
  echo "No pid file for vLLM service"
  exit 0
fi

pid="$(cat "$pid_file")"
if kill "$pid" >/dev/null 2>&1; then
  echo "Stopped vLLM service ($pid)"
  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
    echo "Force killed vLLM service ($pid)"
  fi
else
  echo "vLLM service already stopped or missing ($pid)"
fi
rm -f "$pid_file"
