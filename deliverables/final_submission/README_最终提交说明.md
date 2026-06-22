# ShipVoice 最终提交说明

本文档用于最终打包提交和答辩前检查。按照《信息安全基础》期末项目要求，本组选题为 A2：级联式造船语音问答系统的复现与改进。课程要求提交项目源代码、说明文档以及答辩 PPT，并在说明文档中给出系统架构图、模块版本与配置、基线与改进方案的延迟和客观指标对比表、可复现实验步骤、改进点与局限。ShipVoice 的最终提交材料按这些要求组织，同时额外补充了安全门控、RAG 证据引用、真实语音链路验证、管理后台和运行审计，以便让评审能够确认这不是单页网页演示，而是一套可运行、可测量、可复盘的船厂安全语音问答系统。

## 一、建议压缩包结构

最终压缩包建议命名为：

```text
组长学号-组长姓名-期末项目.zip
```

邮件主题同样建议使用：

```text
组长学号-组长姓名-期末项目
```

压缩包内部建议保持如下结构。组员姓名和学号可以在最终提交前补入，不影响现在的工程和文档内容。

```text
ShipVoice_Final_Submission/
  README_最终提交说明.md
  report/
    ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.docx
    ShipVoice_船厂安全实时语音问答助手_项目报告_最终版.md
  slides/
    ShipVoice_Final_Defense_Deck_Draft.pptx
    ShipVoice_答辩PPT逐页讲稿.md
  manuals/
    ShipVoice_可复现实验与运行手册.md
    ShipVoice_小组分工与提交清单.md
  source/
    README.md
    requirements.txt
    run_app.py
    configs/
    data/
    docs/
    remote/
    scripts/
    src/
    tests/
    web/
  evidence/
    results/project_acceptance_report.md
    results/project_acceptance_report.json
    results/safety_gate_eval_summary.json
    results/asr_eval_summary.json
    results/asr_eval_raw_summary.json
    results/asr_postprocess_summary.json
    results/multiturn_eval_summary.json
    results/citation_quality_summary.json
    results/remote_real_chain_20260612_chattts_48359/summary.json
    deliverables/ShipVoice_Evaluation_Dashboard.html
    deliverables/ShipVoice_Audio_Recording_Pack.html
```

如果压缩包大小受限，优先保留 `source/`、`report/`、`slides/`、`manuals/` 和核心 `evidence/`。真实模型权重、缓存、日志目录和临时运行文件不建议直接放入课程提交压缩包，除非老师要求完整复现实验环境。对于 LoRA 适配器等较大的扩展材料，可以保留说明文档和路径说明，将大文件作为附加材料或网盘链接提交。

## 二、交付物与作业要求的对应关系

作业要求的 A2 核心不是简单做一个聊天页面，而是复现并改进 ASR -> 语言模型 -> TTS 的级联式语音问答链路，并围绕低延迟、可量化对比和可复现实验说明改进点。ShipVoice 的交付物与要求的对应关系如下。

| 作业要求 | ShipVoice 对应交付物 | 说明 |
|---|---|---|
| 系统架构图 | 项目报告第 4 章、`docs/ARCHITECTURE.md` | 报告中说明从文本/语音输入到 ASR、术语后处理、安全门控、RAG、LLM、TTS、审计日志的完整链路。 |
| 模块版本与配置 | 项目报告第 5 章、`configs/pipeline.json`、`configs/runtime.*.env` | 说明 real-only 运行配置，以及 ASR、LLM、TTS、RAG 的真实 provider 接入方式。 |
| 基线 vs 改进指标表 | 项目报告第 8 章、`results/*.json` | 报告中对比级联基线、真实模型链路和安全增强链路，并解释当前瓶颈。 |
| 可复现实验步骤 | `ShipVoice_可复现实验与运行手册.md` | 给出本地启动、后台登录、健康检查、单元测试、评测脚本、真实 provider 切换、远程 GPU 服务验证等步骤。 |
| 改进点与局限 | 项目报告第 9 章、第 12 章 | 改进点包括安全门控、RAG 证据引用、术语后处理、多轮上下文、后台审计、真实 provider 接入；局限包括真实端到端样本仍少、ChatTTS 首音延迟较高、SQLite 尚非生产数据库。 |
| 项目源代码 | `source/` 目录 | 包含前端、后端、模型 provider 抽象、脚本、测试、配置、远程部署脚本。 |
| 说明文档 | `report/` 与 `manuals/` | 项目报告面向评分，运行手册面向复现，提交清单面向答辩前检查。 |
| 答辩 PPT | `slides/` | 保留现有 PPTX，同时提供逐页讲稿，方便按最新系统状态更新和演讲。 |

## 三、项目一句话定位

ShipVoice 是一个面向船厂高风险作业场景的实时安全语音问答助手。用户可以输入文本、上传音频或直接在浏览器中录音，系统将问题转写为文本后，经过术语后处理、安全门控、RAG 证据检索、语言模型生成和 TTS 合成，最终给出带引用依据的安全建议。系统同时提供管理后台，用于知识库维护、provider 健康检查、评测任务、运行审计和异常复盘。

这个定位比“语音问答 Demo”更适合冲高分，因为它同时覆盖了课程 A2 的级联链路要求、低延迟指标要求、实验复现要求，以及信息安全课程中应当体现的安全边界与对抗输入防护。

## 四、答辩时最应该强调的三点

第一，系统是真实可运行的前后端应用。前端页面只是入口，后端有 FastAPI API、WebSocket 事件流、SQLite 持久化、管理后台、知识库 CRUD、运行审计、评测任务和导出能力。评审如果关心“是不是只是网页”，可以直接展示 `/api/health`、`/docs`、`/admin.html`、运行日志和测试结果。

第二，系统不是把 ASR、LLM、TTS 机械串起来，而是在级联链路中加入了造船安全领域约束。安全门控可以对越界问题、危险请求、提示注入进行短路处理，RAG 检索会返回知识条目 ID、来源、风险级别、匹配词和置信度，术语后处理可以修正常见 ASR 误听，例如“舾装阶段”“压载水舱”“动火作业”“测氧测爆”等船厂安全术语。

第三，系统有可量化评测证据。当前安全门控评测 55 条样本，决策准确率 100%，false allow 为 0；ASR 清单评测 50 条录音，后处理后术语召回 100%；多轮问答评测 6 组对话 18 轮，follow-up grounding accuracy 为 100%；引用质量评测 title hit@3 和 ID hit@3 均为 100%；真实语音链路已在远程 GPU 环境完成 3 条样本 smoke test，证明真实 ASR 和 TTS provider 可以接入。

## 五、最终提交前检查清单

最终打包前请逐项确认：

1. 项目报告中的小组成员、学号、课程名称、日期已经补齐。
2. PPT 首页和结尾页的小组成员信息已经补齐。
3. 本地运行 `python -m unittest discover -s tests` 通过。
4. 本地运行 `python scripts\build_acceptance_report.py` 能生成验收报告。
5. 用户端和后台可以正常打开，端口以实际启动输出为准。
6. `results/` 中的关键 JSON、CSV 和报告文件已经一并放入 evidence。
7. 不把 `.git/`、`__pycache__/`、大型模型缓存、临时日志、密钥文件和个人隐私文件打进最终压缩包。
8. 答辩前先启动远程 ASR、LLM、TTS 服务并完成 provider health 检查；如果现场网络或 GPU 不稳定，应暂停真实链路演示并展示已保存的真实链路证据，不再生成替代结果。

## 六、当前版本需要如实说明的边界

为了避免答辩时被追问“是否已经完全企业生产级”，建议在报告和答辩中主动说明边界。当前项目已经显著超过课程 A2 的基本要求，但仍是课程项目与比赛原型阶段，不应夸大为已经生产部署的工业系统。具体来说，真实端到端语音链路目前是 smoke test 级别，样本数为 3 条，不是大规模压测；真实 ChatTTS 链路的首音频延迟约 15 秒，后续需要替换为更快的流式中文 TTS 或做句级并行合成；当前数据库是 SQLite，适合课程演示和单机原型，企业级部署应迁移到 PostgreSQL 并补充 RBAC、监控告警、审批流和灰度发布机制。

主动说明边界不会拉低分数，反而能体现工程判断。因为课程要求关注的是级联链路、改进、指标和可复现，而 ShipVoice 已经在这些方面给出了完整证据。边界部分应作为下一阶段企业级路线，而不是否定当前项目价值。
