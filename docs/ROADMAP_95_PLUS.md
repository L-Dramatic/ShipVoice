# ShipVoice 最终验收路线状态

当前项目的 A2 验收路线已经收敛为真实 provider 链路：

1. 真实 ASR 转写音频。
2. 安全门控在 LLM 前拦截危险请求。
3. RAG 返回可审计知识证据。
4. 真实 LLM 基于证据生成回答。
5. 真实 TTS 返回可播放音频。
6. 后台记录 provider、门控、证据、耗时和错误。

2026-06-23 已完成 50 条在线 ASR 评测、LoRA adapter SHA attestation、30×2×5 真实重复实验和浏览器 `audio.onplaying` 批量取证。下一步重点不是继续扩展页面展示，而是在用户恢复报告/PPT工作时只读 final manifest 统一生成材料。
