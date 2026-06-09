#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/autodl-tmp/shipvoice}"
PYTHON_BIN="${PYTHON_BIN:-/root/miniconda3/bin/python}"
MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-7B-Instruct}"

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

pack_artifacts() {
  find logs outputs results -maxdepth 4 -type f -printf '%p\t%s\n' | sort > results/artifact_manifest.tsv
  tar -czf "results/shipvoice_remote_resume_artifacts_$(date +%Y%m%d_%H%M%S).tar.gz" \
    remote_status.json logs results outputs data/training data/tests configs README.md 2> logs/artifact_pack_resume.log || true
}

finish() {
  code=$?
  set +e
  if [ "$code" -eq 0 ]; then
    status "complete" "resume LoRA training and evaluation completed"
  else
    status "failed" "resume failed with exit code $code"
  fi
  pack_artifacts
  exit "$code"
}
trap finish EXIT

if [ -d outputs/qwen_lora_shipvoice ] && [ ! -f outputs/qwen_lora_shipvoice/adapter_config.json ]; then
  mv outputs/qwen_lora_shipvoice "outputs/qwen_lora_shipvoice_incomplete_$(date +%Y%m%d_%H%M%S)"
fi

status "train" "resuming LoRA training"
MODEL_NAME="$MODEL_NAME" PYTHON_BIN="$PYTHON_BIN" \
  bash remote/train_qwen_lora.sh "$PROJECT_DIR" > logs/train_lora_rerun.log 2>&1

status "lora_eval" "evaluating LoRA adapter"
"$PYTHON_BIN" remote/evaluate_qwen_lora.py \
  --model "$MODEL_NAME" \
  --adapter outputs/qwen_lora_shipvoice \
  --out results/lora_eval.jsonl \
  --load-in-4bit > logs/lora_eval.log 2>&1

status "artifacts" "collecting resume artifact manifest"
pack_artifacts
