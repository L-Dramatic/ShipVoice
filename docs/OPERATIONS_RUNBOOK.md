# ShipVoice 运维操作手册

本文档面向答辩当天和组内交接。当前系统只接受真实 ASR、LLM、TTS provider；没有真实模型服务时，不应执行问答演示。

## 1. 启动前检查

确认 `configs/runtime.real.env` 中至少包含：

```text
SHIPVOICE_ASR_PROVIDER=http_json
SHIPVOICE_ASR_ENDPOINT=http://127.0.0.1:18001/asr
SHIPVOICE_LLM_PROVIDER=openai_compatible
SHIPVOICE_OPENAI_BASE_URL=http://127.0.0.1:18034/v1
SHIPVOICE_LLM_MODEL=shipvoice-qwen2.5-7b-lora
SHIPVOICE_REQUIRE_LORA=1
SHIPVOICE_LORA_ADAPTER_SHA256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
SHIPVOICE_TTS_PROVIDER=http_json
SHIPVOICE_TTS_ENDPOINT=http://127.0.0.1:18002/tts
```

如果服务在 AutoDL/GPU 机器上，先启动远端服务，再建立 SSH 隧道或使用公网端点。

## 2. 启动应用

```powershell
python run_app.py --env-file configs\runtime.real.env --port 8026
```

访问：

```text
http://127.0.0.1:8026/
http://127.0.0.1:8026/admin.html
http://127.0.0.1:8026/docs
```

## 3. 后台登录

建议启动前显式设置管理员密码：

```powershell
$env:SHIPVOICE_ADMIN_PASSWORD="shipvoice-admin"
```

后台可以查看 provider health、知识库、评测数据、运行记录和 case ledger。

## 4. 真实链路检查

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora --require-adapter-sha256 3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
```

检查通过后会写入：

```text
results/real_chain_smoke_streaming.json
results/server_real_batch_comparison_20260623.md
results/server_real_repeated_20260623/summary.json
results/browser_onplaying_streamable_20260623.json
results/asr_online_20260623/summary.json
results/lora_adapter_attestation_20260623.json
```

如果检查失败，按顺序排查：

1. ASR `/health` 是否可访问。
2. LLM `/v1/models` 与 `/health` 是否确认 ShipVoice LoRA adapter 已加载且 SHA 匹配。
3. TTS `/health` 是否可访问。
4. SSH 隧道端口是否一致。
5. 远端模型是否仍在加载。
6. TTS 响应是否包含非空 `audio_base64`。

## 5. 流式低延迟检查

低延迟演示必须选择用户端的“流式低延迟”模式。检查运行详情时，应看到 LLM delta 事件、TTS chunk 事件、WebSocket `audio_chunk` 分段，以及浏览器端 `audio.onplaying` 首播打点。

若 ASR/LLM/TTS 服务器未全部在线，只能展示离线单元测试和已保存证据。服务器侧重复实验 p50/p90/p95 证据见 `results/server_real_repeated_20260623/summary.md`；浏览器 `audio.onplaying` 批量指标见 `results/browser_onplaying_streamable_20260623.json`。

## 6. 答辩演示顺序

1. 打开用户端页面。
2. 用文本问一个正常船厂安全问题。
3. 用危险请求展示安全门控拒答。
4. 用浏览器录音或上传音频展示真实 ASR 输入。
5. 切换到“流式低延迟”模式，展示首个音频片段先于完整答案结束进入播放。
6. 打开后台展示 provider health、知识库和运行审计。
7. 展示 `results/real_chain_smoke_streaming.json`、`results/server_real_repeated_20260623/summary.md`、`results/browser_onplaying_streamable_20260623.json`、`results/asr_online_20260623/report.md` 和 LoRA adapter attestation。

## 7. 失败策略

当前版本不生成替代答案或假音频。如果真实服务失败，应停止现场问答演示，展示后台错误记录、provider health 和已保存的真实链路证据，并说明失败原因。

## 8. GPU 关机

远端任务完成后，先停止服务，再关闭机器：

```bash
bash remote/stop_shipvoice_real_services.sh /root/autodl-tmp/shipvoice || true
bash remote/stop_lora_llm.sh /root/autodl-tmp/shipvoice || true
shutdown -h now
```
