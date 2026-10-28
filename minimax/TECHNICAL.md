# 一页技术说明

## 目标

规格驱动开发（SDD）下，AI 开发助手需要知道三件事：**这次任务受哪些规格约束、要改哪些代码、用什么测试验证**，以及**上次做到哪了**。本模块把这三件事做成可调用的入口，并用 seekdb 与 PowerContext 分别承担"资料检索"和"任务状态"。

## 模块结构

```
sddctx ingest ──► ingest.py ──► db.py（seekdb 嵌入式）
                   │              eng_docs: doc_key/kind/path/symbol/heading/content/start_line/end_line
                   │              FULLTEXT INDEX ... WITH PARSER NGRAM
                   ├─ specs/*.md      → 按 ### R<n> 切节，锚点 spec:<file>#R4
                   ├─ src/**/*.py     → AST 抽函数/类/方法，锚点 code:<module>:list_tickets
                   └─ tests/**/*.py   → AST 抽 test_* 用例，锚点 test:<path>::<name>

sddctx plan ───► retrieve.py ──► 分 kind 召回（spec/code/test 各 5 条）
                   │              命中符号加权 1.5x；无结果时退化为关键词
                   ├─ context.py   → 规格 / 代码 / 测试 / 状态 四段
                   └─ state.py     → PowerContext：scope、todo、done、verified

sddctx status ──► state.py ──► PowerContext HTTP（新进程读取，验证持久化）
```

## 选材方式

- **分路召回，不混排**：规格、代码、测试各取 5 条，避免代码片段挤掉规格条目；三类资料对任务的价值不同，配额比单一 top-k 更稳定。
- **结构化锚点**：每条结果都带 `path:start_line-end_line`，`verify.py` 会打开文件核对行号，输出里不存在"编造来源"。
- **符号加权**：任务里出现 `list_tickets` 时，同名符号得分乘以 1.5，保证"任务点名的函数"一定在上下文里。
- **全文检索而非向量**：NGRAM 全文在规格/代码这种术语密集的语料上足够，且评审环境零模型下载、零网络依赖。向量检索留作扩展，`pyproject` 里没有强制依赖。

## PowerContext 状态模型

- 每个任务一个 scope：`SDD · <task_id>`，创建幂等（`idempotency_key`）；
- 三类记忆：`todo`（待办规格）、`done`（完成事项）、`verified`（验证结论与测试日志尾部）；
- `plan` 读状态、`start` / `done` 写状态，读发生在**新进程**，证明状态不依赖内存。

## 与 MiniMax 的衔接

`plan --json` 的输出就是交给模型的上下文；`scripts/run_minimax.py` 保存请求、模型与参数、原始回复、抽取出的 diff。记录与最终提交的 diff、测试日志一一对应（见 `docs/minimax-dev-log.md`）。运行时不需要模型和密钥。

## 证据链

| 证据 | 位置 |
| --- | --- |
| 改前目标测试失败 | `docs/evidence/before-target.log`、`docs/evidence/red-commit.txt` |
| 改后目标+回归测试通过 | `docs/evidence/after-target.log` |
| 12 项验收 | `docs/verification/report.json` |
| 数据库读写 | `docs/database-queries.md` |
| 状态写入与重启读取 | `docs/powercontext-state.md` |

## 限制

- 规格解析假设条目以 `### R<n>` 开头；换成其他格式需要调整 `ingest.SPEC_HEADING`。
- 只索引单个工程目录；多仓库场景需要按 `kind` 或 `module` 增加过滤。
- 默认英文/中文混合全文检索，不做语义改写；任务描述过于笼统时召回会退化。
