# ShipVoice 阶段验收表

## 当前状态

ShipVoice 已从课程原型升级为真实 provider 链路应用。现行验收重点如下：

| 项目 | 状态 | 证据 |
|---|---|---|
| 前后端应用 | 已完成 | `run_app.py`, `src/shipvoice/fastapi_app.py`, `web/static/` |
| 浏览器录音和音频上传 | 已完成 | `web/static/app.js` |
| 真实 ASR 接入 | 已在线复验 | `HttpJsonASRProvider`, `configs/runtime.real.env`, `/api/ready` |
| 真实 LLM 接入 | 已在线复验 | `OpenAICompatibleLLMProvider`, `served_model=shipvoice-qwen2.5-7b-lora`, `adapter_loaded=true` |
| 真实 TTS 接入 | 已在线复验 | `HttpJsonTTSProvider`, `/api/ready` |
| 流式低延迟链路 | 已完成重复实验与浏览器首播取证 | `OpenAICompatibleLLMProvider.stream_answer`, `ShipVoicePipeline._run_streaming_llm_tts`, WebSocket `audio_chunk`, `results/server_real_repeated_20260623/summary.json`, `results/browser_onplaying_streamable_20260623.json` |
| LoRA adapter attestation | 已完成 | `results/lora_adapter_attestation_20260623.json`, `adapter_sha256=3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf` |
| 在线 ASR 质量评测 | 已完成 | `results/asr_online_20260623/summary.json`：50/50 evaluated，平均 CER/WER 1.58%，术语召回 85.71% |
| 安全门控 | 已完成 | `KeywordSafetyGate`, `results/safety_gate_eval_summary.json` |
| RAG 证据引用 | 已完成 | `data/knowledge/`, `results/citation_quality_summary.json` |
| 后台审计 | 已完成 | `src/shipvoice/sqlite_store.py`, `web/static/admin.html` |

## 验收原则

真实 ASR、LLM、TTS 服务缺失时，问答请求必须失败并记录错误。文本输入可以用于 typed input 测试，但不能替代音频 ASR 证据。当前 2026-06-23 服务器侧复验、30×2×5 重复实验、LoRA adapter SHA、在线 ASR 评测和浏览器 `audio.onplaying` 批量表均已完成；最终答辩材料后续只需从同一 manifest 生成。

## 剩余事项

1. 基于最终证据重建 final manifest，并在报告/PPT恢复制作时只读该 manifest。
2. 更新报告和 PPT 中的最终首播延迟表。
3. 继续做生产化长期项：取消传播、持久队列、依赖锁、远端认证和容器加固。
