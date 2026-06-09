# AutoDL Recovery 2026-06-08

## Current State

- Local bundle is ready at `results/autodl_bundle.zip`.
- The latest bundle defaults to `SHUTDOWN_ON_EXIT=0`, so the machine stays online for log/result retrieval.
- If `SHUTDOWN_ON_EXIT=1` is explicitly set, the shutdown is delayed by `POST_EXIT_SHUTDOWN_DELAY_SECONDS` and artifacts are packed first.
- The previous remote run reached `base_eval`, finished downloading `Qwen/Qwen2.5-7B-Instruct`, loaded the model on GPU, then SSH stopped returning a normal banner. Treat that machine as unavailable until the cloud console shows it is running again.

## Safe Relaunch Command

After uploading and extracting `results/autodl_bundle.zip` to `/root/autodl-tmp/shipvoice`, run:

```bash
cd /root/autodl-tmp/shipvoice
mkdir -p logs results outputs
chmod +x remote/*.sh
rm -f NO_SHUTDOWN

PROJECT_DIR=/root/autodl-tmp/shipvoice \
PYTHON_BIN=/root/miniconda3/bin/python \
MODEL_NAME=Qwen/Qwen2.5-7B-Instruct \
SHUTDOWN_ON_EXIT=0 \
HF_ENDPOINT=https://hf-mirror.com \
nohup bash remote/run_autodl_pipeline.sh > logs/pipeline.log 2>&1 &

echo $! > pipeline.pid
```

## Monitor Command

```bash
cd /root/autodl-tmp/shipvoice
cat remote_status.json
ps -p "$(cat pipeline.pid)" -o pid,etime,stat,cmd || true
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader || true
tail -80 logs/base_eval.log 2>/dev/null || true
tail -80 logs/train_lora.log 2>/dev/null || true
tail -80 logs/lora_eval.log 2>/dev/null || true
wc -l results/base_eval.jsonl results/lora_eval.jsonl 2>/dev/null || true
```

## Artifact Retrieval

Before shutting down, retrieve:

```text
remote_status.json
logs/*.log
results/base_eval.jsonl
results/lora_eval.jsonl
results/artifact_manifest.tsv
results/shipvoice_remote_artifacts_*.tar.gz
outputs/qwen_lora_shipvoice/
```

Then explicitly shut down:

```bash
/usr/bin/shutdown -h now || /usr/sbin/poweroff -f || /usr/sbin/halt -p
```
