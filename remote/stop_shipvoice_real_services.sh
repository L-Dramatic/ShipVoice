#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-/root/autodl-tmp/shipvoice}"
cd "$PROJECT_DIR"

for name in asr_service tts_service; do
  pid_file="logs/${name}.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill "$pid" >/dev/null 2>&1; then
      echo "Stopped $name ($pid)"
      sleep 1
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -9 "$pid" >/dev/null 2>&1 || true
        echo "Force killed $name ($pid)"
      fi
    else
      echo "$name already stopped or missing ($pid)"
    fi
    rm -f "$pid_file"
  else
    echo "No pid file for $name"
  fi
done
