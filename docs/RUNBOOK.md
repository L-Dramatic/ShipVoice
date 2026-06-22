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
python scripts\check_real_service_chain.py --env-file configs\runtime.real.env --sample-id A001 --require-lora
```

最终验收一键脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_lora_final_validation.ps1 -EnvFile configs\runtime.real.env -SampleId A001
```

输出：

```text
results\real_chain_smoke.json
```

检查项包括：

1. ASR `/health`
2. TTS `/health`
3. LLM `/v1/models` 与 `/health`，确认 ShipVoice LoRA adapter 已加载
4. 一条真实录音是否能跑通
5. 本地 pipeline 是否真的走了真实 provider

## 7. 全项目 quick validation

```powershell
python scripts\validate_project.py --quick
```

这一步只做结构、数据、评测脚本和编译检查，不调用真实 ASR/LLM/TTS。

## 8. 全项目 full validation

```powershell
python scripts\validate_project.py --full
```

真实服务已经全部在线时，再运行：

```powershell
python scripts\validate_project.py --quick --with-services
```

## 9. 容器方式启动

```powershell
docker compose -f docker-compose.app.yml up --build
```

## 10. 远程 GPU 服务

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
