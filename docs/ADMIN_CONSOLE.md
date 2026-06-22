# ShipVoice 管理后台说明

后台入口：

```text
http://127.0.0.1:<port>/admin.html
```

## 功能

1. 查看知识库条目数量、评测数据和运行审计。
2. 检查 ASR、LLM、TTS provider health。
3. 搜索、新增、编辑、删除知识库条目。
4. 重建知识索引。
5. 查看评测数据集。
6. 查看运行记录和错误日志。
7. 导出运行记录 CSV 或 JSONL。
8. 给异常记录添加 case 状态、严重度和复盘备注。

## Provider Health

后台会显示当前 ASR、LLM、TTS 的 provider 名称、端点和健康检查结果。当前系统只接受真实 provider；如果端点不可达，应先修复模型服务，再进行问答演示。

## 认证

建议启动前设置：

```powershell
$env:SHIPVOICE_ADMIN_PASSWORD="shipvoice-admin"
```

课程项目阶段使用单管理员口令。企业级改进方向是 RBAC、审计签名和操作审批流。
