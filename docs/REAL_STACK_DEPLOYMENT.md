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
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora
```

或直接运行完整本地验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

通过后检查 `results/real_chain_smoke.json`，确认 provider 状态、ASR 转写、ShipVoice LoRA 模型、TTS 音频和耗时均有记录。

## 关机

任务完成后：

```bash
SHUTDOWN_AFTER_STOP=1 bash remote/stop_full_lora_stack.sh /root/autodl-tmp/shipvoice
```
