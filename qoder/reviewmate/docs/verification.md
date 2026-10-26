# 验证样例

本页给出评审可直接复现的一组样例：初始数据、操作步骤、预期结果，以及 seekdb 与 PowerContext 实际发挥作用的记录。

## 初始数据

- 知识库：`data/samples/` 下 4 篇自编课程笔记，共 20 个片段；来源与许可见 `data/samples-README.md`。
- seekdb 数据文件：`data/seekdb/reviewmate.db`（首次导入时创建）。
- PowerContext：1.2.0，SQLite 后端，数据文件 `data/powercontext/reviewmate.db`。
- 不需要大模型 Key；默认使用本地 `BAAI/bge-small-zh-v1.5` 与本地摘录回答。

## 步骤一：启动与导入

```bash
make powercontext   # 终端 A，监听 127.0.0.1:8100
make ingest         # 终端 B，导入 4 篇笔记
make serve          # 终端 B，监听 127.0.0.1:8090
```

预期：`make ingest` 输出 4 篇文档、每篇 5 个片段；打开 `http://127.0.0.1:8090` 后右上角 seekdb 与 PowerContext 均为绿色。

## 步骤二：页面体验

1. 点击「换一个」获得新的学习会话。
2. 输入：`LRU 和 FIFO 有什么区别？为什么 FIFO 会出现 Belady 异常？`
3. 点击「检索并回答」。
4. 点击证据下方「需要再复习，加入薄弱点」。
5. 点击「生成复习计划」。

截图：

| 页面 | 文件 |
|---|---|
| 首页 | `data/screenshots/home.png` |
| 回答与引用 | `data/screenshots/answer.png` |
| 复习计划 | `data/screenshots/plan.png` |
| 完整页面 | `data/screenshots/full.png` |
| 移动端 | `data/screenshots/mobile.png` |

预期结果：

- 回答模式显示「本地摘录」，直接引用 1 条，引用标题为《虚拟内存与页面置换》第 4 页 · LRU 与 FIFO 的对比。
- 展开「查看检索轨迹」，可见全文与向量两路候选数、RRF 参数与耗时；正文直接给出 `MATCH ... AGAINST` 与 `l2_distance ... APPROXIMATE` 的 SQL。
- 左侧「学习记忆」先出现自动记录的「进度」，标记后出现「薄弱点」。
- 复习计划显示「取用了 1 条薄弱点，覆盖 4 篇笔记」，第 1 步即回看该薄弱点。

## 步骤三：一键验收

```bash
make verify
```

最近一次实际输出（2026-10-26，WSL Ubuntu，Python 3.12.3）：

```
[PASS] 环境就绪
[PASS] PowerContext 健康检查
[PASS] seekdb 知识库: 4 篇笔记 / 20 个片段 / 4 门课程
[PASS] PowerContext scope 建立
[PASS] 混合检索命中两路: 全文 3 条，向量 5 条，保留全文 1 / 向量 5
[PASS] 引用可回到原文: 《虚拟内存与页面置换》第 4 页 · LRU 与 FIFO 的对比
[PASS] 回答带可用引用: 模式=extractive，直接引用 1/5 条
[PASS] 自动记录提问
[PASS] 薄弱点写入并保留: 记忆 2 条，类型=study-progress,weak-point
[PASS] 后续提问复用记忆: PowerContext 检索命中 2 条历史记忆
[PASS] 复习计划读取薄弱点: 薄弱点 1 条，覆盖 1 篇笔记
[PASS] QA 日志可追溯: 本会话 2 条问答记录
结果：12 通过 / 0 失败
```

完整机器可读记录：`data/verification/report.json`。其中包含：

- `evidence.seekdb_stats`：文档数、片段数、课程分布、累计提问数；
- `evidence.ask.retrieval`：两路候选数、阈值过滤、重试次数、RRF 后的引用列表；
- `evidence.scope_id`：PowerContext scope；
- `evidence.memory_entries`：自动进度与薄弱点的记忆文本、类型、entry_id；
- `evidence.memory_reuse_hits`：第二次提问命中历史记忆数；
- `evidence.plan`：计划模式、薄弱点数量、覆盖文档与正文摘要。

## 指定技术如何发挥作用

### seekdb

- 检索不是关键词匹配的简单替代：同一条 SQL 同时返回全文与向量候选，`report.json` 的 `channels` 同时大于 0 即证明两路均生效。
- 引用可定位到 chunk 的标题、章节、页码与原文；问的是 LRU/FIFO，命中的是《虚拟内存与页面置换》第 4 页，而不是其他课程。
- 课程过滤在数据库层完成；界面切换「操作系统」后，候选不会跨到数据库或网络笔记。
- `qa_log` 记录问题、证据 chunk、回答模式与耗时，可追溯每次提问。

### PowerContext

- 提问后自动写入 `study-progress`，界面与 `memory_entries` 均可看到原文。
- 薄弱点写入后，复习计划读取同一 scope 并与文档交叉生成步骤；`plan.weak_points >= 1` 即证明记忆被复用。
- 第二次提问使用同一 scope，`memory_status.hits = 2`，说明历史记忆参与了回答上下文。
- 新会话拥有独立 scope，记忆互不污染。

## 命令行交叉验证

```bash
.venv/bin/python -m reviewmate ask "LRU 和 FIFO 有什么区别？" --course 操作系统 --session demo --json
.venv/bin/python -m reviewmate memory --session demo
.venv/bin/python -m reviewmate plan --session demo --course 操作系统
```

`ask --json` 输出中的 `trace.retrieval`、`trace.powercontext`、`citations[].used` 与页面轨迹一致。

## HTTP 交叉验证

```bash
curl -s http://127.0.0.1:8090/api/health

curl -s http://127.0.0.1:8090/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"LRU 和 FIFO 有什么区别？","session_id":"demo","course":"操作系统"}'
```

## 清理与重跑

```bash
make clean   # 删除 seekdb、PowerContext 与验收报告
make ingest
make verify
```

清理前请确认不需要保留已有学习记忆。
