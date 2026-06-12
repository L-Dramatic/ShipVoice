# 运行手册

## 1. 默认 mock 演示

```powershell
python run_demo.py
```

打开：

```text
http://127.0.0.1:8010
```

面板会调用本地 `/api/run`，默认使用 mock ASR、mock LLM、mock TTS，但 RAG 检索已经使用结构化知识库索引。

## 2. 构建知识库索引

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

## 3. 检索评测

```powershell
python scripts\evaluate_retrieval.py
```

当前目标：固定测试集中有明确答案来源的问题，`hit@3` 必须全中。

## 4. 单条问题调试

```powershell
python scripts\run_single.py "舾装阶段管路试压有哪些安全风险？" --mode full
```

输出包括转写、门控、证据、回答和延迟指标。

## 5. 切换真实 OpenAI-compatible LLM

适用于 Ollama、vLLM、LM Studio、OpenAI-compatible 云服务。

### Ollama 示例

```powershell
$env:SHIPVOICE_LLM_PROVIDER="ollama"
$env:SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:11434/v1"
$env:SHIPVOICE_LLM_MODEL="qwen2.5:7b-instruct"
python run_demo.py
```

### vLLM 示例

```powershell
$env:SHIPVOICE_LLM_PROVIDER="vllm"
$env:SHIPVOICE_OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
$env:SHIPVOICE_LLM_MODEL="Qwen/Qwen2.5-7B-Instruct"
python run_demo.py
```

### 远程 API 示例

```powershell
$env:SHIPVOICE_LLM_PROVIDER="openai_compatible"
$env:SHIPVOICE_OPENAI_BASE_URL="https://your-provider.example.com/v1"
$env:SHIPVOICE_LLM_MODEL="your-model-name"
$env:SHIPVOICE_OPENAI_API_KEY="不要把 key 写进代码"
python run_demo.py
```

如果真实 LLM 服务不可用，Provider 会自动回退到 mock 回答，保证演示面板不崩。

## 6. 生成 SFT 种子数据

```powershell
python scripts\generate_sft_seed.py
```

输出：

```text
data\training\sft_seed.jsonl
```

这是后续 Qwen LoRA/QLoRA 的种子数据，不是最终训练集。最终训练集需要继续扩展到 1000-3000 条领域 QA。

## 7. 当前一键验证

```powershell
python scripts\validate_project.py --quick
```

完整 benchmark：

```powershell
python scripts\validate_project.py --full
```

## 8. 真实 ASR / TTS 服务链路检查

当远端服务已经启动后，可先做 health check 与整链 smoke：

```powershell
$env:SHIPVOICE_ASR_ENDPOINT="http://<server-ip>:8001/asr"
$env:SHIPVOICE_TTS_ENDPOINT="http://<server-ip>:8002/tts"
python scripts\check_real_service_chain.py --sample-id A001
```

输出文件：

```text
results\real_chain_smoke.json
```

这个脚本会同时检查：

1. ASR `/health`
2. TTS `/health`
3. 一条真实录音的 ASR 返回
4. 本地 pipeline 是否已走到 `http_json` ASR/TTS provider

如果 `edge-tts` 在中文文本上返回 `No audio was received`，直接改用备用 backend：

```bash
TTS_BACKEND=gtts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果仍然不稳定，切换到本地中文 TTS 模型：

```bash
TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

如果远端机器访问官方 Hugging Face 不稳定，建议直接带镜像环境变量启动：
```bash
HF_ENDPOINT=https://hf-mirror.com CHATTTS_SOURCE=huggingface TTS_BACKEND=chattts bash remote/start_shipvoice_real_services.sh /root/autodl-tmp/shipvoice
```

当前仓库已经留存一轮验证结果：
```text
results\remote_real_chain_20260612_chattts_48359\
```

该目录包含：

1. `real_chain_smoke.json`：单样本完整冒烟结果
2. `A001.json / A002.json / A003.json`：三条真实录音端到端结果
3. `summary.json`：平均 ASR、检索、首音和总耗时
4. `asr_service.log / tts_service.log`：远端服务日志
