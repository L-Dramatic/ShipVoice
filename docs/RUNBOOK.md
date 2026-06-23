# ShipVoice 运行手册

## 1. 启动本地真实链路应用

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode real
```

默认地址：

```text
http://127.0.0.1:8022
```

## 2. 准备真实 provider 配置

先准备：

```powershell
Copy-Item configs\runtime.real.env.example configs\runtime.real.env
```

或：

```powershell
Copy-Item configs\runtime.lora.env.example configs\runtime.real.env
```

确认 ASR、LLM、TTS 端点可用后启动：

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode real
```

## 3. 构建知识库索引

```powershell
python scripts\build_knowledge_index.py
```

输入：

```text
data\knowledge\ship_safety_corpus.jsonl
```

输出：

```text
data\knowledge\ship_safety_index.json
```

## 4. 检索评测

```powershell
python scripts\evaluate_retrieval.py
```

## 5. 单条问题调试

```powershell
python scripts\run_single.py "舾装阶段管路试压有哪些安全风险？" --mode full
```

## 6. 真实链路检查

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora --require-adapter-sha256 3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
```

最终验收一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

输出：

```text
results\server_real_batch_comparison_20260623.md
results\server_real_batch_comparison_20260623.json
results\server_real_repeated_20260623\summary.json
results\browser_onplaying_streamable_20260623.json
results\waiting_experience_20260623\summary.json
results\asr_online_20260623\summary.json
results\lora_adapter_attestation_20260623.json
```

检查项包括：

1. ASR `/health`
2. TTS `/health`
3. LLM `/v1/models` 与 `/health`，确认 ShipVoice LoRA adapter 已加载且 SHA 匹配
4. 一条真实录音是否能跑通
5. 本地 pipeline 是否真的走了真实 provider

## 7. 流式低延迟复验

真实 ASR、支持 SSE 的 ShipVoice LoRA LLM、TTS 服务都在线后，复验 `streaming` mode：

```powershell
python scripts\run_single.py "舾装阶段管路试压有哪些安全风险？" --mode streaming
```

批量复验命令：

```powershell
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode baseline --limit 30 --split test --require-lora --output-dir results\server_real_batch_baseline_20260623
python scripts\run_real_chain_batch.py --env-file configs\runtime.real.env --mode streaming --limit 30 --split test --require-lora --output-dir results\server_real_batch_streaming_20260623
python scripts\compare_real_chain_batches.py --baseline results\server_real_batch_baseline_20260623\samples.jsonl --streaming results\server_real_batch_streaming_20260623\samples.jsonl
python scripts\run_real_chain_repeated.py --env-file configs\runtime.real.env --limit 30 --split test --repeats 5 --require-lora --output-dir results\server_real_repeated_20260623
python scripts\generate_browser_onplaying_harness.py --env-file configs\runtime.real.env --sample-ids A006,A020,A014,A009,A029,A004,A015,A013,A007,A005,A016,A001,A018,A003,A010,A019,A012,A002,A008,A011 --output results\browser_onplaying_streamable_20260623.html
python scripts\run_browser_onplaying_harness.py --url http://127.0.0.1:8026 --html results\browser_onplaying_streamable_20260623.html --output results\browser_onplaying_streamable_20260623.json --screenshot results\browser_onplaying_streamable_20260623.png
```

WebSocket 页面复验时，确认运行详情中出现 `llm_first_delta_ms`、`server_first_audio_chunk_ready_ms`、`streamed_audio_segments`，并且前端首段音频由 `audio_chunk` 队列触发播放。高风险样本还应出现 `output_guard` 事件，说明系统先播安全前缀或在 TTS 前改写不安全片段；非流式完整回答也应在 TTS 前经过输出 guard。ASR、LLM、TTS provider 使用持久 HTTP 连接池，LLM SSE 流式解析不再走每次请求临时 `urlopen` 的短连接路径，`provider_status` 应能看到连接池类型、keepalive 和请求/失败计数。2026-06-23 最终低延迟证据见 `results/server_real_repeated_20260623/summary.md` 和 `results/browser_onplaying_streamable_20260623.json`；最终低延迟结论应使用浏览器 `audio.onplaying` 指标，不使用完整 TTS 返回时间替代首播时间。

运行中取消复验：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8026/api/runs/<run_id>/cancel" -ContentType "application/json" -Body '{"session_id":"<session_id>","metrics":{}}'
```

取消后对应运行状态应变为 `cancelled`，HTTP 路径返回 499；WebSocket 路径可发送 `{ "type": "cancel" }` 控制帧，后端会把取消信号传到 pipeline 和 provider 调用边界。

## 8. A2 固定音频集与等待体验评分

生成 50 条固定音频指令集的难度梯度说明：

```powershell
python scripts\build_a2_audio_eval_manifest.py
```

输出：

```text
data\audio\audio_manifest_a2_eval.csv
docs\FIXED_AUDIO_COMMAND_SET_20260623.md
```

生成主观等待体验代理评分：

```powershell
python scripts\evaluate_waiting_experience.py
```

输出：

```text
results\waiting_experience_20260623\proxy_wait_pairs.csv
results\waiting_experience_20260623\browser_streaming_wait_scores.csv
results\waiting_experience_20260623\summary.json
results\waiting_experience_20260623\report.md
```

该评分使用真实链路延迟日志和浏览器 `audio.onplaying` 结果，不伪造真人问卷。浏览器录音路径还会在运行审计中记录 `client_recording_stop_to_playing_ms`，用于对齐“用户端停止说话到首段音频开始播放”的测量点。

## 9. 全项目 quick validation

```powershell
python scripts\validate_project.py --quick
```

这一步只做结构、数据、评测脚本和编译检查，不调用真实 ASR/LLM/TTS。

## 10. 全项目 full validation

```powershell
python scripts\validate_project.py --full
```

真实服务已经全部在线时，再运行：

```powershell
python scripts\validate_project.py --quick --with-services
```

## 11. 容器方式启动

```powershell
docker compose -f docker-compose.app.yml up --build
```

## 12. 远程 GPU 服务

ASR / TTS：

```bash
bash remote/start_full_lora_stack.sh /root/autodl-tmp/shipvoice
bash remote/stop_full_lora_stack.sh /root/autodl-tmp/shipvoice
```

ShipVoice LoRA LLM：

```bash
bash remote/start_lora_llm.sh /root/autodl-tmp/shipvoice
bash remote/stop_lora_llm.sh /root/autodl-tmp/shipvoice
```
