# PowerContext 状态记录

PowerContext 以独立进程运行，SQLite 作为服务端数据库；任务状态不落在本地文件，也不在上下文模块进程内。

## 启动

```bash
cd minimax
mkdir -p data/powercontext
POWERCONTEXT_SERVER_DATABASE_URL="sqlite+aiosqlite:///$PWD/data/powercontext/sdd.db" \
  .venv/bin/powercontext server run --host 127.0.0.1 --port 8102
```

健康检查：

```json
{"status":"ready","checks":{"runtime":"ready","database":"ready","artifact_processing_supervisor":"disabled","access_mode":"disabled","authentication_provider":"disabled","access_provider":"disabled"}}
```

## 写入（空状态开始）

```bash
python -m sdd_context start --task-id state-demo --items "R4,R5,R6"
```

```json
{"task_id": "state-demo", "scope_id": "scp_1a4q4knzt6hqyet7j025mdbn2d", "todo": ["R4", "R5", "R6"]}
```

重复执行 `start` 不会产生重复条目（CLI 先比对已有条目再写入）：

```json
{"task_id": "state-demo", "scope_id": "scp_1a4q4knzt6hqyet7j025mdbn2d", "todo": ["R4", "R5", "R6"]}
```

## 新进程读取

```bash
python -m sdd_context status --task-id state-demo --json
```

```json
{
  "available": true,
  "scope_id": "scp_1a4q4knzt6hqyet7j025mdbn2d",
  "todo": ["待办：R4, R5, R6"],
  "done": [],
  "verified": [],
  "entry_count": 1
}
```

`status` 是通过 CLI 启动的**新进程**，读取的是 PowerContext 中的持久化记录；`verify.py` 的第 10 项检查即使用这种子进程方式。

## 完成与验证记录

```bash
python -m sdd_context done --task-id sdd-r4-r6 \
  --summary "R4-R6 已实现并通过测试" --log docs/evidence/after-target.log
```

`done` 写入两条记录：`done`（完成事项）与 `verified`（验证结论 + 测试日志尾部），下次 `plan` 会一并读出。

## 对应用户要求

题面要求"从空状态开始保存任务记录，重启模块后能够读取，并用于后续上下文或任务处理"：

1. 空状态：`verify.py` 第 9 项使用带时间戳的新 task id，确保 scope 内没有历史记录；
2. 重启：第 10 项用新进程执行 `status`；
3. 用于后续任务：`plan` 的 `status` 段直接来自同一 scope，实现 R4–R6 前的 `todo` 与完成后的 `verified` 都会进入上下文。
