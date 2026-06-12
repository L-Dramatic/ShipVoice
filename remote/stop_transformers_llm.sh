#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
cd "$PROJECT_DIR"

pid_file="logs/transformers_llm.pid"
if [[ ! -f "$pid_file" ]]; then
  echo "No pid file for transformers LLM service"
  exit 0
fi

pid="$(cat "$pid_file")"
if kill "$pid" >/dev/null 2>&1; then
  echo "Stopped transformers LLM service ($pid)"
  sleep 1
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill -9 "$pid" >/dev/null 2>&1 || true
    echo "Force killed transformers LLM service ($pid)"
  fi
else
  echo "Transformers LLM service already stopped or missing ($pid)"
fi
rm -f "$pid_file"

