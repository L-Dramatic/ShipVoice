# ShipVoice LoRA 最终真实链路验收手册

本文档用于下一次开 GPU 后执行最终验收。目标不是跑一个展示样例，而是证明当前系统真正完成：

```text
真实 ASR -> 安全门控 -> RAG -> ShipVoice LoRA 在线模型 -> 真实 TTS
```

只有下面验收全部通过后，才能把项目认定为 A2 真实链路证据完整版本。本文不再使用“95+”自评分作为验收标准。

## 1. 本机准备

本机已生成 AutoDL 上传包：

```text
results\autodl_bundle.zip
```

这个包必须包含：

```text
outputs/qwen_lora_shipvoice_expanded/adapter_config.json
outputs/qwen_lora_shipvoice_expanded/adapter_model.safetensors
remote/start_full_lora_stack.sh
remote/stop_full_lora_stack.sh
scripts/check_real_service_chain.py
scripts/run_lora_final_validation.ps1
```

本机可用以下命令重新生成并检查：

```powershell
python scripts\make_autodl_bundle.py
python scripts\validate_project.py --remote-smoke
```

## 2. 上传并解压到 GPU 机器

在本机把 `results\autodl_bundle.zip` 上传到 AutoDL。远端解压：

```bash
mkdir -p /root/autodl-tmp/shipvoice
unzip -o autodl_bundle.zip -d /root/autodl-tmp/shipvoice
cd /root/autodl-tmp/shipvoice
```

确认 adapter 存在：

```bash
test -f outputs/qwen_lora_shipvoice_expanded/adapter_config.json
test -f outputs/qwen_lora_shipvoice_expanded/adapter_model.safetensors
```

## 3. 远端启动完整真实栈

先安装依赖：

```bash
bash remote/autodl_setup.sh /root/autodl-tmp/shipvoice
bash remote/autodl_setup_asr.sh /root/autodl-tmp/shipvoice
```

启动 ASR、TTS、ShipVoice LoRA LLM：

```bash
bash remote/start_full_lora_stack.sh /root/autodl-tmp/shipvoice
```

必须看到：

```text
Full ShipVoice LoRA stack is ready.
```

如果中途失败，不要继续验收。先看：

```bash
tail -n 120 logs/asr_service.log
tail -n 120 logs/tts_service.log
tail -n 120 logs/lora_llm.log
```

## 4. 本地配置和端口

如果使用 SSH 隧道，把远端端口映射到本地：

```text
remote:8001  -> 127.0.0.1:18001
remote:8002  -> 127.0.0.1:18002
remote:11434 -> 127.0.0.1:18034
```

本地 `configs\runtime.real.env` 应包含：

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

## 5. 本地最终验收

运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

这个脚本会依次执行：

```text
real-only source gate
ShipVoice LoRA real chain check
full project validation with live services
acceptance report rebuild
evaluation dashboard rebuild
final real-only gate
```

当前 2026-06-23 已补充完成的最终证据还包括：

```powershell
python scripts\attest_lora_adapter.py --env-file configs\runtime.real.env --output results\lora_adapter_attestation_20260623.json
python scripts\evaluate_asr_online.py --env-file configs\runtime.real.env --output-dir results\asr_online_20260623
python scripts\run_real_chain_repeated.py --env-file configs\runtime.real.env --limit 30 --split test --repeats 5 --require-lora --output-dir results\server_real_repeated_20260623
python scripts\run_browser_onplaying_harness.py --url http://127.0.0.1:8026 --html results\browser_onplaying_streamable_20260623.html --output results\browser_onplaying_streamable_20260623.json --screenshot results\browser_onplaying_streamable_20260623.png
```

## 6. 通过标准

以下全部满足才算完成当前阶段：

1. `scripts\check_real_service_chain.py --require-lora` 通过。
2. `results\real_chain_smoke_streaming.json` 中 `llm_require_lora` 为 `true`。
3. `results\real_chain_smoke_streaming.json` 中 `llm_health.health.adapter_loaded` 为 `true`。
4. `results\lora_adapter_attestation_20260623.json` 中 `sha_match` 为 `true`。
5. `provider_status.llm` 包含 `shipvoice-qwen2.5-7b-lora`。
6. `provider_status.asr` 为真实 HTTP ASR。
7. `provider_status.tts` 为真实 HTTP TTS。
8. `results\asr_online_20260623\summary.json` 显示 50/50 evaluated，且不使用 transcript hint。
9. `results\server_real_repeated_20260623\summary.json` 显示 300/300 ok，100/100 gate-allowed 配对中 streaming 更快。
10. `results\browser_onplaying_streamable_20260623.json` 显示 20/20 ok，并包含 `client_audio_onplaying_ms` p50/p90/p95。
11. 后续报告、PPT、Dashboard 从最终 manifest 刷新为最新证据，不再引用旧 0% CER 或旧单轮低延迟数字。

如果任一项不满足，不允许在报告或答辩中宣称最终链路已完成。

## 7. 停止服务和关机

远端完成后必须停止服务并关机：

```bash
SHUTDOWN_AFTER_STOP=1 bash remote/stop_full_lora_stack.sh /root/autodl-tmp/shipvoice
```

该脚本内部会执行：

```text
stop ShipVoice LoRA LLM
stop ASR/TTS
shutdown -h now
```

关机后回到 AutoDL 控制台确认实例已停止计费。
