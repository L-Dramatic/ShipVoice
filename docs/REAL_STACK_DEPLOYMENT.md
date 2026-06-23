# ShipVoice 真实模型部署指南

## 目标

本指南说明如何部署 ShipVoice 的真实 ASR、LLM、TTS 链路。当前系统只接受真实 provider；服务不可用时请求失败并记录错误。

## 远端服务

在 GPU 机器上准备项目目录后启动：

```bash
bash remote/start_full_lora_stack.sh /root/autodl-tmp/shipvoice
```

建议端口：

```text
ASR: 8001
TTS: 8002
ShipVoice LoRA LLM: 11434 compatible /v1
```

ShipVoice LoRA LLM 端点必须支持 OpenAI-compatible `stream=true` SSE。仓库内 `remote/serve_transformers_openai.py` 已使用 `TextIteratorStreamer` 输出 `chat.completion.chunk`，可用于本项目的流式低延迟链路。本地 ASR、LLM、TTS provider 会复用持久 HTTP client/keep-alive 连接池，因此远端服务应保持标准 HTTP keep-alive 行为，不要在每个 SSE delta 或 JSON 请求后强制异常断开。

## 本地连接

如果通过 SSH 隧道连接，建议映射为：

```text
127.0.0.1:18001 -> remote:8001
127.0.0.1:18002 -> remote:8002
127.0.0.1:18034 -> remote:11434
```

本地 `configs/runtime.real.env`：

```text
SHIPVOICE_ASR_PROVIDER=http_json
SHIPVOICE_ASR_ENDPOINT=http://127.0.0.1:18001/asr
SHIPVOICE_LLM_PROVIDER=openai_compatible
SHIPVOICE_OPENAI_BASE_URL=http://127.0.0.1:18034/v1
SHIPVOICE_LLM_MODEL=shipvoice-qwen2.5-7b-lora
SHIPVOICE_REQUIRE_LORA=1
SHIPVOICE_REQUIRE_LLM_MODEL_SUBSTRING=shipvoice
SHIPVOICE_LORA_ADAPTER_SHA256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
SHIPVOICE_TTS_PROVIDER=http_json
SHIPVOICE_TTS_ENDPOINT=http://127.0.0.1:18002/tts
SHIPVOICE_TTS_VOICE=zh-CN-XiaoxiaoNeural
```

## 启动应用

```powershell
python run_app.py --env-file configs\runtime.real.env --port 8026
```

## 验证

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora --require-adapter-sha256 3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
```

或直接运行完整本地验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

通过后检查 `results/real_chain_smoke_streaming.json` 与 `results/lora_adapter_attestation_20260623.json`，确认 provider 状态、ASR 转写、ShipVoice LoRA 模型、adapter SHA、TTS 音频、流式分段和耗时均有记录。

## 流式低延迟验证

服务全部在线后运行：

```powershell
python scripts\run_single.py "舾装阶段管路试压有哪些安全风险？" --mode streaming
```

批量复验：

```powershell
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode baseline --limit 30 --split test --require-lora --output-dir results\server_real_batch_baseline_20260623
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode streaming --limit 30 --split test --require-lora --output-dir results\server_real_batch_streaming_20260623
python scripts\compare_real_chain_batches.py --baseline results\server_real_batch_baseline_20260623\samples.jsonl --streaming results\server_real_batch_streaming_20260623\samples.jsonl
python scripts\run_real_chain_repeated.py --env-file configs\runtime.real.env --limit 30 --split test --repeats 5 --require-lora --output-dir results\server_real_repeated_20260623
```

浏览器 WebSocket 演示时，确认首个 `audio_chunk` 到达后前端立即入队播放，并记录 `audio.onplaying`。高风险样本应先出现安全前缀或 `output_guard` 事件，证明系统不是把单 token 或不完整半句直接播出。服务器侧重复性能证据见 `results/server_real_repeated_20260623/summary.md`，浏览器首播证据见 `results/browser_onplaying_streamable_20260623.json`。最终性能结论只使用同一批音频在 baseline 与 streaming 下的配对重复结果。

## 关机

任务完成后：

```bash
SHUTDOWN_AFTER_STOP=1 bash remote/stop_full_lora_stack.sh /root/autodl-tmp/shipvoice
```
