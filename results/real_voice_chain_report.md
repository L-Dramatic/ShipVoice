# ShipVoice 真实语音链路验证

## 验证目标

证明项目已经具备真实语音输入与真实语音输出能力，而不是只有本地网页演示。

## 验证环境

- 远端 GPU：RTX 4090 24GB
- 远端 ASR：FunASR / SenseVoiceSmall
- 远端 TTS：ChatTTS
- 语音服务形态：HTTP JSON provider
- 本地问答链路：`http_json_asr -> retrieval -> mock_llm -> http_json_tts`
- 结果目录：`results/remote_real_chain_20260612_chattts_48359/`

## 样本范围

- `A001` 密闭舱室动火作业前要检查什么？
- `A002` 舾装阶段管路试压有哪些安全风险？
- `A003` 船体分段吊装前，需要确认哪些事项？

共 3 条真实录音端到端跑通。

## 汇总结果

- 平均 ASR：`158 ms`
- 平均检索：`165.67 ms`
- 平均 TTS 首音：`14794 ms`
- 平均端到端首音：`15238.67 ms`
- 平均总耗时：`15239 ms`

## 结论

1. 项目已经具备真实 ASR 和真实 TTS 服务集成能力。
2. 当前主要瓶颈不是 ASR，也不是检索，而是 ChatTTS 首音延迟较高。
3. 这轮结果足以作为课程项目“真实系统链路”证据。
4. 企业级下一步应优先优化 TTS 推理延迟，并将 `mock_llm` 替换为真实受控 LLM 服务。
