# 船厂安全实时语音问答助手

本项目对应信息安全基础期末项目 A2：级联式语音问答系统的复现与改进。

目标不是只把 ASR、LLM、TTS 串起来，而是做成一个可演示、可测量、可扩展的船厂安全语音助手：

- 延迟治理：真实 ASR、LoRA LLM、TTS 链路已打通并完成 30×2×5 重复实验与浏览器 `audio.onplaying` 批量取证；`streaming` 模式已实现 LLM token/SSE 流、句级切分、TTS 分段合成和 WebSocket 音频 chunk 首句优先播放。
- 领域增强：造船安全知识库、RAG 检索、术语热词、LLM LoRA/QLoRA 微调。
- 安全增强：领域门控、危险/恶意输入短路拒答、提示注入检测。
- 实验闭环：基线、改进、消融、延迟统计、术语识别与安全拦截评测。

## 运行原则

当前版本采用 real-only 运行策略：ASR、LLM、TTS 必须接入真实 provider。真实服务不可用时，请求会直接失败并在前端、后台和审计日志中暴露错误。

文本输入是一个独立输入路径，不等同于语音识别；音频上传和浏览器录音必须经过真实 ASR 服务。危险请求由安全门控直接拒答，且不会调用 LLM。

## 快速运行

```powershell
python run_app.py --env-file configs\runtime.real.env --port 8026
```

打开：

```text
http://127.0.0.1:8026
```

如果真实 provider 运行在远端 GPU，请先用 SSH 隧道或公网地址把以下服务暴露给本机：

```text
ASR: http://127.0.0.1:18001/asr
ShipVoice LoRA LLM: http://127.0.0.1:18034/v1
TTS: http://127.0.0.1:18002/tts
```

当前接口也支持 `history` 多轮上下文字段，便于把 Part 1 的对话能力接到 Part 2 的语音链路中。
用户端支持三种输入方式：文本提问、音频文件上传、浏览器麦克风直接录音。直接录音使用浏览器 MediaRecorder 生成音频，再按和上传文件相同的 `audio_base64` 协议送入后端 ASR。
回答结果会展示 RAG 证据引用，包括知识条目 ID、来源、风险级别、置信度、标签和匹配词，便于说明答案不是模型凭空生成。
用户端界面已升级为深色工业安全控制台，包含链路总览、作业场景、实时指标、证据卡片、延迟分布和审计日志。

运行真实链路检查：

```powershell
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora --require-adapter-sha256 3462dbff405f71ed3d0b0a0d8484498a2be98ffe84ab5b2f56a2d69e7130d1cf
```

GPU 服务在线后运行最终验收：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

输出文件：

```text
results\real_chain_smoke_streaming.json
results\server_real_batch_comparison_20260623.md
results\server_real_repeated_20260623\summary.json
results\browser_onplaying_streamable_20260623.json
results\asr_online_20260623\summary.json
results\lora_adapter_attestation_20260623.json
```

生成课程验收报告：

```powershell
python scripts\evaluate_citation_quality.py --fail-on-threshold
python scripts\build_acceptance_report.py
```

输出文件：

```text
results\citation_quality_eval.csv
results\citation_quality_summary.json
results\citation_quality_report.md
results\project_acceptance_report.md
results\project_acceptance_report.json
```

## 真实 ASR / LLM / TTS 配置

当前版本通过环境变量指定真实 provider，并在 `/api/health` 与前端界面中显示当前实际链路。

### 1. 真实 LLM

```powershell
$env:SHIPVOICE_LLM_PROVIDER="openai_compatible"
$env:SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:18034/v1"
$env:SHIPVOICE_LLM_MODEL="shipvoice-qwen2.5-7b-lora"
$env:SHIPVOICE_REQUIRE_LORA="1"
python run_app.py --port 8026
```

### 2. 真实 ASR

后端支持 `http_json` ASR provider。约定向 ASR 服务发送：

```json
{
  "audio_base64": "...",
  "audio_name": "sample.wav"
}
```

并从响应 JSON 的 `text` 字段读取转写结果。

```powershell
$env:SHIPVOICE_ASR_PROVIDER="http_json"
$env:SHIPVOICE_ASR_ENDPOINT="http://127.0.0.1:18001/asr"
python run_app.py --port 8026
```

### 3. 真实 TTS

后端支持 `http_json` TTS provider。约定向 TTS 服务发送：

```json
{
  "text": "要合成的回答",
  "voice": "alloy"
}
```

并从响应 JSON 的 `audio_base64` 与 `mime_type` 字段读取音频结果。

```powershell
$env:SHIPVOICE_TTS_PROVIDER="http_json"
$env:SHIPVOICE_TTS_ENDPOINT="http://127.0.0.1:18002/tts"
python run_app.py --port 8026
```

真实服务不可用时系统不会生成替代答案或假音频。请先恢复 ASR、LLM、TTS 服务，再执行问答。

### 4. 远端一键启动真实 ASR + TTS

仓库已经提供远端服务脚本：

- `remote/serve_funasr_asr.py`
- `remote/serve_edge_tts.py`
- `remote/start_shipvoice_real_services.sh`
- `remote/stop_shipvoice_real_services.sh`

在 GPU 机器上完成依赖安装后，可直接启动：

```bash
bash remote/autodl_setup_asr.sh /root/autodl-tmp/shipvoice
bash remote/start_full_lora_stack.sh /root/autodl-tmp/shipvoice
```

如果 `edge-tts` 对中文播报不稳定，可直接切换备用中文 backend：

```bash
TTS_BACKEND=gtts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果需要真正的本地中文 TTS 模型，可进一步切到 `ChatTTS`：

```bash
TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果远端机器访问官方 Hugging Face 不稳定，建议显式指定镜像：
```bash
HF_ENDPOINT=https://hf-mirror.com CHATTTS_SOURCE=huggingface TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

然后在本地演示机上配置：

```powershell
$env:SHIPVOICE_ASR_PROVIDER="http_json"
$env:SHIPVOICE_ASR_ENDPOINT="http://<server-ip>:8001/asr"
$env:SHIPVOICE_LLM_PROVIDER="openai_compatible"
$env:SHIPVOICE_OPENAI_BASE_URL="http://<server-ip>:11434/v1"
$env:SHIPVOICE_LLM_MODEL="shipvoice-qwen2.5-7b-lora"
$env:SHIPVOICE_REQUIRE_LORA="1"
$env:SHIPVOICE_TTS_PROVIDER="http_json"
$env:SHIPVOICE_TTS_ENDPOINT="http://<server-ip>:8002/tts"
python run_app.py --port 8026
```

### 已验证的真实语音链路

2026-06-12 已完成一轮远端真实 ASR/TTS 链路验证，结果归档于 `results/remote_real_chain_20260612_chattts_48359/`。该历史结果中的 LLM 仍是旧受控回答层，不能作为当前 real-only 主链路证据；当前主链路证据应使用 2026-06-23 的 ASR、ShipVoice LoRA LLM、TTS 全真实结果。

- 远端 ASR：`FunASR / SenseVoiceSmall`
- 远端 TTS：`ChatTTS`
- 验证样本：`A001-A003` 共 3 条真实录音
- 平均 ASR：`158 ms`
- 平均检索：`165.67 ms`
- 平均音频载荷就绪：`15238.67 ms`

当前验证已经证明系统具备真实语音输入、ShipVoice LoRA 在线模型和真实语音输出能力。服务器侧低延迟证据见 `results/server_real_repeated_20260623/summary.json`，浏览器首播证据见 `results/browser_onplaying_streamable_20260623.json`，LoRA adapter SHA 证据见 `results/lora_adapter_attestation_20260623.json`。

## 目录结构

```text
configs/                 系统配置、门控策略、延迟目标
data/knowledge/          造船安全知识库种子材料
data/tests/              固定评测问题集
docs/                    架构、实施计划、报告素材
experiments/             后续实验记录
results/                 自动生成的指标表
scripts/                 实验脚本
src/shipvoice/           级联式语音问答核心代码
web/static/              答辩演示面板
```

## 后续真实模型接入路线

1. ASR：SenseVoice/FunASR，先接热词和术语纠错，再评估微调。
2. LLM：当前主线为 Qwen + ShipVoice LoRA adapter 在线服务；后续可继续做 DPO/安全偏好优化。
3. TTS：CosyVoice，优先完成句级流式播报与首句优先播放。
4. 安全：先规则门控，再训练轻量分类器，最后加入提示注入与越权请求测试集。

## 托管执行文档

- 总规划：[docs/MASTER_EXECUTION_PLAN.md](docs/MASTER_EXECUTION_PLAN.md)
- 任务看板：[docs/TASK_BOARD.md](docs/TASK_BOARD.md)
- 运行手册：[docs/RUNBOOK.md](docs/RUNBOOK.md)
- 零准备启动方案：[docs/ZERO_PREP_BOOTSTRAP.md](docs/ZERO_PREP_BOOTSTRAP.md)
- AutoDL 使用方案：[docs/AUTODL_RUNBOOK.md](docs/AUTODL_RUNBOOK.md)
- LoRA 最终验收手册：[docs/FINAL_LORA_VALIDATION_RUNBOOK.md](docs/FINAL_LORA_VALIDATION_RUNBOOK.md)
- 高质量路线：[docs/HIGHEST_QUALITY_PLAN.md](docs/HIGHEST_QUALITY_PLAN.md)
- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 最新验收材料

- 课程高分评分证据：[docs/PHASE1_SCORECARD.md](docs/PHASE1_SCORECARD.md)
- 演示与运维操作手册：[docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md)
- 引用质量评测：[results/citation_quality_report.md](results/citation_quality_report.md)
- 在线 ASR 质量评测：[results/asr_online_20260623/report.md](results/asr_online_20260623/report.md)
- 30×2×5 低延迟重复实验：[results/server_real_repeated_20260623/summary.md](results/server_real_repeated_20260623/summary.md)
- 浏览器首播批量取证：[results/browser_onplaying_streamable_20260623.json](results/browser_onplaying_streamable_20260623.json)
- 一键验收报告：[results/project_acceptance_report.md](results/project_acceptance_report.md)
