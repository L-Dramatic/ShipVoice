#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-7B-Instruct}"
SHUTDOWN_ON_EXIT="${SHUTDOWN_ON_EXIT:-0}"
POST_EXIT_SHUTDOWN_DELAY_SECONDS="${POST_EXIT_SHUTDOWN_DELAY_SECONDS:-300}"

cd "$PROJECT_DIR"
mkdir -p logs outputs results

export HF_HOME="${HF_HOME:-/root/autodl-tmp/hf-cache}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-/root/autodl-tmp/hf-cache}"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export TOKENIZERS_PARALLELISM=false

status() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import datetime, json, sys
stage, note = sys.argv[1], sys.argv[2]
json.dump(
    {"stage": stage, "note": note, "updated_at": datetime.datetime.now().isoformat()},
    open("remote_status.json", "w", encoding="utf-8"),
    ensure_ascii=False,
    indent=2,
)
PY
}

shutdown_if_needed() {
  code=$?
  set +e
  if [ "$code" -eq 0 ]; then
    status "complete" "pipeline completed"
  else
    status "failed" "pipeline failed with exit code $code"
  fi
  find logs outputs results -maxdepth 4 -type f -printf '%p\t%s\n' | sort > results/artifact_manifest.tsv
  tar -czf "results/shipvoice_remote_artifacts_$(date +%Y%m%d_%H%M%S).tar.gz" \
    remote_status.json logs results data/training data/tests configs README.md 2> logs/artifact_pack.log
  if [ -f "$PROJECT_DIR/NO_SHUTDOWN" ]; then
    echo "NO_SHUTDOWN exists; skip shutdown."
  elif [ "$SHUTDOWN_ON_EXIT" = "1" ]; then
    sync
    nohup sh -c "sleep $POST_EXIT_SHUTDOWN_DELAY_SECONDS; /usr/bin/shutdown -h now || /usr/sbin/poweroff -f || /usr/sbin/halt -p" > logs/final_shutdown.log 2>&1 &
  fi
  exit "$code"
}
trap shutdown_if_needed EXIT

status "setup" "installing dependencies"
bash remote/autodl_setup.sh "$PROJECT_DIR" > logs/setup.log 2>&1

status "smoke" "running smoke test"
bash remote/autodl_smoke_test.sh "$PROJECT_DIR" > logs/smoke.log 2>&1

status "base_eval" "evaluating base model"
"$PYTHON_BIN" remote/evaluate_qwen_lora.py \
  --model "$MODEL_NAME" \
  --out results/base_eval.jsonl \
  --load-in-4bit > logs/base_eval.log 2>&1

status "train" "training LoRA adapter"
MODEL_NAME="$MODEL_NAME" PYTHON_BIN="$PYTHON_BIN" \
  bash remote/train_qwen_lora.sh "$PROJECT_DIR" > logs/train_lora.log 2>&1

status "lora_eval" "evaluating LoRA adapter"
"$PYTHON_BIN" remote/evaluate_qwen_lora.py \
  --model "$MODEL_NAME" \
  --adapter outputs/qwen_lora_shipvoice \
  --out results/lora_eval.jsonl \
  --load-in-4bit > logs/lora_eval.log 2>&1

status "artifacts" "collecting artifact manifest"
find logs outputs results -maxdepth 3 -type f -printf '%p\t%s\n' | sort > results/artifact_manifest.tsv
