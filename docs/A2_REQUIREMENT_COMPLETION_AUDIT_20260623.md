# ShipVoice A2 作业要求逐项完成审计

生成日期：2026-06-23

本文档用于把老师给出的 A2 要求逐条落到当前仓库中的真实代码、真实实验结果和最终交付物。结论先写在前面：当前项目已经不只是“演示网页”，而是一套可启动的 FastAPI 前后端一体应用，支持文本输入、音频上传、浏览器直接录音、真实 ASR/LLM/TTS provider 接入、RAG 引用、安全门控、运行审计、管理后台和可复现实验脚本。除 PPT 和 PPT 大纲外，本轮已补齐固定音频指令集难度梯度、主观等待体验量化代理评分、严格客户端播放计时口径，以及报告/手册/提交说明中的证据引用。

## 1. 总体完成度

| A2 要求 | 当前状态 | 证据位置 |
| --- | --- | --- |
| 实现 ASR -> 语言模型 -> TTS 级联链路 | 已完成 | `src/shipvoice/pipeline.py`, `src/shipvoice/providers.py`, `web/static/app.js` |
| 不强制端到端语音大模型，但模块可替换 | 已完成 | `configs/pipeline.json`, `configs/runtime.real.env.example`, `configs/runtime.lora.env.example` |
| 完成串行级联基线 | 已完成 | `scripts/run_real_chain_batch.py`, `results/server_real_batch_baseline_20260623/summary.json` |
| 明确模块选型、进程/服务接口 | 已完成 | `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `deliverables/final_submission/manuals/ShipVoice_可复现实验与运行手册.md` |
| 明确缓冲与队列策略 | 已完成并已在报告中补强 | `web/static/app.js`, `src/shipvoice/pipeline.py`, 最终报告第 4.6/7/8 节 |
| 构建固定音频指令集，含难度梯度 | 已补齐 | `data/audio/audio_manifest.csv`, `data/audio/audio_manifest_a2_eval.csv`, `docs/FIXED_AUDIO_COMMAND_SET_20260623.md` |
| 音频集包含专有名词与安全类问句 | 已完成 | 50 条录音清单，24 条显式命中船厂安全术语，L4 安全边界 29 条 |
| 可重复运行与记录基线实验 | 已完成 | `results/server_real_repeated_20260623/summary.json`, `samples.jsonl` |
| 至少一项改进：LLM SSE 增量接收、安全闭合句段 TTS、首段优先播放 | 已完成并加固 | `response_mode=llm_token_stream_sentence_tts`, 输出片段 guard, `results/browser_onplaying_streamable_20260623.json` |
| 与基线对比首段可播放延迟 | 已完成 | `results/server_real_batch_comparison_20260623.json`, `results/server_real_repeated_20260623/summary.json` |
| 写清测量点 | 已补强 | 服务端 `server_first_audio_chunk_ready_ms`；浏览器端 `client_audio_onplaying_ms`；新增 `client_recording_stop_to_playing_ms` |
| 主观等待体验量化对比 | 已补齐 | `scripts/evaluate_waiting_experience.py`, `results/waiting_experience_20260623/report.md` |
| 调度改进：衔接语或首段优先 | 已完成安全闭合首段优先，不做无依据衔接语 | 流式输出先合成安全闭合句段；高风险问题先播保守安全前缀，避免额外播放无实质内容的填充语 |
| 质量改进：ASR 热词/术语后处理 | 已完成 | `configs/asr_postprocess_rules.json`, `results/asr_eval_raw_summary.json`, `results/asr_eval_summary.json` |
| 安全模块衔接 | 已完成并强化 | 输入侧 safety gate + 播报前输出片段 guard；`src/shipvoice/pipeline.py`, `tests/test_p0_hardening.py`, `results/safety_gate_eval_summary.json` |
| 系统架构图 | 已完成 | 最终报告、`docs/ARCHITECTURE.md` |
| 模块版本与配置 | 已完成 | 最终报告、`docs/RUNBOOK.md`, `configs/*.example` |
| 基线 vs 改进延迟与客观指标表 | 已完成并已补强 | 最终报告第 8 节、`results/server_real_repeated_20260623/summary.md` |
| 可复现实验步骤 | 已完成并已补强 | `deliverables/final_submission/manuals/ShipVoice_可复现实验与运行手册.md` |
| 说明改进点与局限 | 已完成并已更新 | 最终报告第 12 节 |

## 2. 级联链路不是 mock

当前系统运行策略是 real-only：ASR、LLM、TTS 都通过真实 provider 抽象接入；真实服务不可用时，系统失败并记录错误，不生成替代答案、不造假音频、不把示例数据当作运行结果。安全门控拦截危险或越界请求时，会短路 LLM 和 TTS，这不是 mock，而是安全系统的预期行为：不应为了播放声音而继续生成被拒绝请求的正文。

关键证据：

- `scripts/validate_real_only.py` 用于扫描运行时不允许的 fake/mock/demo provider 口径。
- `tests/test_p0_hardening.py` 验证安全门控拦截后不会继续调用下游正文生成链路。
- `results/server_real_repeated_20260623/summary.json` 记录 300 次真实链路运行，`num_ok=300`, `num_failed=0`。
- LLM 健康检查记录了在线模型 `shipvoice-qwen2.5-7b-lora`、adapter SHA256 和 CUDA 运行状态。

## 3. 固定音频指令集

本轮新增 `scripts/build_a2_audio_eval_manifest.py`，将原始 50 条音频清单增强为 A2 评测清单：

- L1 基础安全问答：1 条
- L2 船厂专有名词与专业作业：9 条
- L3 噪声、应急与复杂处置：11 条
- L4 安全边界与对抗输入：29 条

这个比例不是为了追求平均分布，而是有意体现信息安全课程项目的重点：除了能回答常规安全问题，还要大量验证系统在危险请求、越界问题、提示注入、拒绝违章压力下是否 fail-closed。完整逐条表见 `docs/FIXED_AUDIO_COMMAND_SET_20260623.md`。

## 4. 低延迟与等待体验

当前项目有三层延迟证据：

| 证据类型 | 测量点 | 作用 |
| --- | --- | --- |
| 服务端基线/改进对比 | 从服务端收到请求到首段音频 ready | 适合做 baseline vs improved 的同条件实验 |
| 浏览器播放观测 | 从浏览器提交请求到 `audio.onplaying` | 更接近答辩现场用户听到声音的时间 |
| 新增录音停止口径 | 从浏览器停止录音到 `audio.onplaying` | 对齐题目建议的“用户端停止说话到首段音频开始播放” |

真实重复实验中，gate-allowed 的 100 个配对样本显示：

- 串行基线首段可播放延迟均值：7967.04 ms
- 流式改进首段可播放延迟均值：3819.65 ms
- 平均节省：4147.39 ms
- 100/100 个配对样本流式改进更快

浏览器 `audio.onplaying` 实测 20 条样本：

- 播放成功：20/20
- `audio.onplaying` 均值：4093.5 ms
- P50：4072.0 ms
- P90：5600.1 ms

主观等待体验本轮采用自动化代理评分，不伪装成真人问卷。评分只根据真实延迟日志映射 1-5 分，用于补齐课程要求中的可量化等待体验。结果显示串行基线代理等待评分均值为 2.02/5，流式改进为 3.71/5；浏览器流式播放为 3.6/5。完整口径见 `results/waiting_experience_20260623/report.md`。

## 5. ASR 质量与术语后处理

原始 ASR 结果和术语后处理结果都已保留：

- `results/asr_online_20260623/summary.json`：在线 ASR 50/50 可评，不向 ASR 服务提供参考转写，平均 CER/WER 约 1.58%，术语召回率约 85.71%。
- 历史 `results/asr_eval_summary.json` 的 0% 结果只可视为本地修正清单复算，不作为真实 ASR 泛化主结论。

这说明项目不是只写“加入热词/术语表”，而是保存了改进前后的客观对比。

## 6. 安全门控与信息安全加分点

安全门控评测集当前为 56 条：

- label accuracy：100%
- decision accuracy：100%
- expected block：37
- expected allow：19
- false allow：0
- false block：0

安全门控的位置在 RAG/LLM/TTS 正文链路之前。这样可以保证 dangerous/off-domain/prompt-injection 输入不会进入普通生成流程。对于信息安全基础课程，这一部分是 A2 语音链路之外的重要加分点，因为它将“语音问答系统”升级为“受控安全助手”。

## 7. 仍需如实说明的边界

1. 等待体验目前是自动化代理评分，不是真人 Likert 问卷；它可以用于课程量化报告，但不能表述为真实用户调研。
2. 当前知识库是课程级核心规程库，适合证明 RAG 引用闭环；企业级落地仍需要扩展到完整船厂制度、作业票和事故案例库。
3. 答辩现场若 GPU/远程服务不可用，real-only 系统会如实失败，不会退回假数据；因此答辩前必须准备可用的 AutoDL/GPU provider 或本地兼容服务。
4. SQLite 与单管理员口令适合课程原型和可复现验收；企业级部署应迁移到 PostgreSQL、RBAC、对象存储、异步队列、监控告警和审计留存策略。

## 8. 本轮不触碰范围

按用户要求，本轮只升级 PPT 和 PPT 大纲之外的交付物。未修改：

- `deliverables/ShipVoice_Final_Defense_Deck_Draft.pptx`
- `deliverables/ShipVoice_答辩PPT高质量设计大纲.md`
- `deliverables/final_submission/slides/ShipVoice_答辩PPT逐页讲稿.md`
