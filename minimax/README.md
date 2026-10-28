# 规有所依：SDD 工程上下文模块

给 AI 开发助手提供"这次任务该遵守哪些规格、该改哪些代码、该跑哪些测试"，并把任务进度持久化，重启后接着做。规格、代码和测试由 **seekdb** 索引与召回，任务状态由 **PowerContext** 保存，本次 R4–R6 的代码修改由 **MiniMax** 完成。

| 组件 | 实际作用 | 位置 |
| --- | --- | --- |
| seekdb（嵌入式） | `eng_docs` 表保存规格条目、代码符号、测试用例，NGRAM 全文索引，一条 SQL 完成召回 | `src/sdd_context/db.py` |
| PowerContext | 每个任务一个 scope，记录 `todo` / `done` / `verified`，重启后读取复用 | `src/sdd_context/state.py` |
| MiniMax | 根据上下文完成 R4–R6 的代码修改 | `docs/minimax-dev-log.md` |
| 业务工程 | `list_tickets` 的规格、实现与测试（改动对象） | `workspace/` |

## 目录

```
minimax/
├── src/sdd_context/       # 上下文模块（CLI + Python API）
├── workspace/             # 业务工程：specs/ src/ tests/
├── evals/                 # 验证样例与规格更新副本
├── scripts/               # verify.py / run_minimax.py / demo_red_green.sh
├── docs/                  # 开发记录、数据库记录、验证报告、证据
└── Makefile
```

## 环境要求

- Linux 或 macOS（WSL2 Ubuntu 24.04 已验证），Python 3.11+
- [uv](https://docs.astral.sh/uv/)（安装后可能在 `~/.local/bin`，需加入 PATH）
- 无需独立数据库服务：seekdb 以 `pylibseekdb` 嵌入式运行
- PowerContext 从 PyPI 安装（`powercontext[builtin,cli]`），用 SQLite 作为后端

## 快速开始

```bash
export PATH="$HOME/.local/bin:$PATH"
cd minimax

make setup          # 建 .venv 并安装依赖（含 powercontext）
make ingest         # 规格 / 代码 / 测试 → seekdb
make plan TASK="为 list_tickets 增加 priority 过滤，非法 priority 与越界 limit 抛出 InvalidFilter，结果按优先级和创建时间稳定排序"
```

`make plan` 输出四段：适用规格、相关代码、验证测试、任务状态。加上 `--json` 可直接作为模型输入：

```bash
.venv/bin/python -m sdd_context plan --task "..." --task-id sdd-r4-r6 --json
```

## PowerContext：任务状态

一个终端启动服务（前台，端口 8102）：

```bash
make powercontext
```

另一个终端登记任务并读取：

```bash
.venv/bin/python -m sdd_context start --task-id sdd-r4-r6 --items "R4,R5,R6"
.venv/bin/python -m sdd_context status --task-id sdd-r4-r6
.venv/bin/python -m sdd_context done --task-id sdd-r4-r6 \
  --summary "R4-R6 已实现并通过测试" --log docs/evidence/after-target.log
```

`status` 由新进程执行，读的是 PowerContext 里的持久化记录，不是内存状态。

## 验证

```bash
make test-workspace   # 业务工程测试（R4-R6 实现后应全绿）
make verify           # 12 项验收，写 docs/verification/report.json
make red-green        # 现场复现「改前红、改后绿」
```

`make verify` 覆盖：

1. 必需文件齐全；2. 导入计数；3. 三类检索非空；4. R4/R5/R6 与真实行号；5. `list_tickets` 符号；6. 目标测试命中；7. 规格更新重导入后跟随更新；8. PowerContext 健康；9. 空状态写入；10. 新进程读回；11. 红→绿；12. 无凭据入库。

## 验证样例

见 [`evals/task.md`](evals/task.md)：任务描述、必须命中的规格/代码/测试来源、预期输出、重置方法。

## MiniMax 记录

`scripts/run_minimax.py` 把任务与上下文发给 MiniMax，保存请求、回复、diff 与模型信息（不保存任何密钥）：

```bash
export MINIMAX_API_KEY="..."
export MINIMAX_BASE_URL="https://api.minimaxi.com/v1"   # 或 OpenCode Go: https://opencode.ai/zen/go/v1
export MINIMAX_MODEL="Minimax-M3"
export MINIMAX_API_STYLE="openai"                        # OpenCode Go 的 M3 用 anthropic
.venv/bin/python scripts/run_minimax.py --task "..." --task-id sdd-r4-r6
```

运行时的 `plan` / `status` 不调用模型，评审环境无需网络与密钥。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `uv: command not found` | `export PATH="$HOME/.local/bin:$PATH"` |
| `No module named typer / opentelemetry` | 依赖 extras 未装：`uv pip install -e ".[dev]"`（已声明 `powercontext[builtin,cli]`） |
| 端口 8102 被占用 | 换端口并设置 `SDD_POWERCONTEXT_URL` |
| `SDD_DB_PATH` / `SDD_PROJECT` | 指定索引库与业务工程目录，默认 `data/seekdb/sdd.db`、`workspace/` |

## 提交信息

- 仓库：`https://github.com/ycl-berserk/2026oceanbase-powercontext`
- 分支：`minimax`（基于 `2026-competition-ecosystem`）
- 目录：`minimax/`

实现细节见 [`TECHNICAL.md`](TECHNICAL.md)，MiniMax 修改过程见 [`docs/minimax-dev-log.md`](docs/minimax-dev-log.md)。
