# ShipVoice FastAPI Backend

## 目标

这一版后端是把原来的本地演示链路，升级成可持续扩展的应用后端。当前已经完成四件核心事情：

1. 引入 `FastAPI`，把系统能力整理成标准 API。
2. 引入 `SQLite`，把知识库、运行审计、评测数据持久化。
3. 引入 `WebSocket`，支持前端实时显示推理事件流。
4. 保持原有前台与后台页面可用，降低迁移成本。

## 启动方式

```powershell
python run_app.py
```

或者显式指定运行环境文件：

```powershell
python run_app.py --env-file configs\runtime.mock.env
python run_app.py --env-file configs\runtime.real.env
```

默认优先尝试：

```text
http://127.0.0.1:8022
```

如果端口被占用，会自动顺延到下一个空闲端口。启动后可以访问：

- 前台：`/`
- 后台：`/admin.html`
- API 文档：`/docs`

## 持久化位置

SQLite 数据库路径：

```text
results/runtime/shipvoice.db
```

当前主要表包括：

1. `knowledge_records`
   - 存储船舶安全知识条目
   - 支撑后台知识库 CRUD

2. `run_audits`
   - 存储系统运行审计日志
   - 记录 `session_id`、`run_id`、`gate`、回答摘要、provider、时延、错误

3. `evaluation_datasets`
   - 存储评测数据集元信息
   - 记录名称、来源、指标摘要、样本量

4. `evaluation_rows`
   - 存储评测明细样本
   - 支撑后台按数据集查看每条样本结果

## 当前接口

### 核心接口

- `GET /api/health`
- `GET /api/sessions`
- `POST /api/run`
- `WS /ws/run`

### 后台接口

- `GET /api/admin/overview`
- `GET /api/admin/runs`
- `POST /api/admin/runs/cleanup`
- `GET /api/admin/evaluations`
- `GET /api/admin/evaluations/{dataset_name}`
- `POST /api/admin/evaluations/reload`
- `GET /api/admin/provider-health`
- `GET /api/admin/config`
- `POST /api/admin/config`
- `POST /api/admin/config/reload`
- `GET /api/admin/knowledge`
- `GET /api/admin/knowledge/{record_id}`
- `POST /api/admin/knowledge`
- `PUT /api/admin/knowledge/{record_id}`
- `DELETE /api/admin/knowledge/{record_id}`
- `POST /api/admin/reindex`

## 与旧链路的关系

这不是推倒重来，而是平滑升级：

- 知识库修改后仍会同步写回 `data/knowledge/ship_safety_corpus.jsonl`
- 同时自动重建 `data/knowledge/ship_safety_index.json`
- 现有检索、评测、报告生成脚本仍然可以继续使用

## 自动化验证

当前后端 smoke test 脚本：

```powershell
python scripts\smoke_fastapi_backend.py
```

它会自动完成以下检查：

1. 启动临时 FastAPI 服务
2. 检查 `/api/health`
3. 检查后台概览、评测数据、配置接口
4. 检查知识库新增、查询、删除
5. 检查 `WS /ws/run` 事件流
6. 自动关闭临时服务

项目总体验证：

```powershell
python scripts\validate_project.py --quick
```

切换启动模式的 PowerShell 脚本：

```powershell
.\scripts\start_shipvoice_app.ps1 -Mode mock
.\scripts\start_shipvoice_app.ps1 -Mode real
```

## 当前边界

1. 数据库仍是 `SQLite`，适合课程项目和单机原型，不适合高并发生产环境。
2. 还没有用户系统、权限控制、任务队列、对象存储等企业级能力。
3. 评测结果已经结构化入库，但还没有做更强的趋势分析、回归告警、批量对比。

## 下一阶段建议

1. 接入真实认证与角色权限控制
2. 增加批量评测任务与异步队列
3. 将数据库迁移到 `PostgreSQL`
4. 为前后端补齐部署脚本、监控指标和回归测试
