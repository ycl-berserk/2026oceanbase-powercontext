# 端侧向量化 + seekdb 混合检索 · 迷你知识库

> 2026 OceanBase × 阶跃星辰 赛题「端侧 AI 推理性能优化与 seekdb 混合检索」的实现。
> 浏览器负责 embedding（WebGPU 优先，自动降级 WASM），seekdb 负责向量 + 全文的混合检索。

导入文档 → 浏览器端切块并生成向量 → 写入 seekdb → 刷新索引 → 输入查询 → 查询向量同样在端侧生成 → seekdb 用 `DBMS_HYBRID_SEARCH` 做 RRF 融合 → 展示排序结果与原文。

- 前端：Vue 3 + Vite + TypeScript + Pinia
- 端侧推理：Transformers.js（ONNX Runtime Web），`Xenova/bge-small-zh-v1.5`，支持 FP32 / FP16 / INT8(q8)
- 数据层：seekdb 1.4.0（本地 server，TCP），seekdb-js SDK，HNSW 向量索引 + ik 中文全文索引

## 与赛题要求的对应

| 要求 | 实现 |
| --- | --- |
| 可导入文本、生成向量、写入 seekdb、查询并展示排序结果 | `导入` / `检索` 两个页签，支持拖拽文件、粘贴、示例语料 |
| 文档与查询 embedding 均在浏览器本地计算 | `web/src/lib/embedder.ts`，Transformers.js 前端推理，无任何云端调用 |
| INT8 或 FP16 量化 + 体积 / 质量报告 | 三档精度可切换；体积来自真实文件与浏览器缓存实测；质量见 `docs/EXPERIMENTS.md` |
| 优先 WebGPU，不支持自动降级 WASM 并提示 | 启动时探测 `navigator.gpu`，失败自动降级；顶部徽章显示当前后端与降级原因；可手动强制 WASM 验证降级路径 |
| 向量/原文/元数据存 seekdb，混合检索在库内完成 | 集合结构 = 原文 + 512 维向量 + JSON 元数据；检索走 `collection.hybridSearch()`（`DBMS_HYBRID_SEARCH` + RRF） |
| 增量导入、刷新后可检索、集合与会话状态正确 | 写入后 `refresh_index()` + 写后自检（写入确认 / 向量召回 / 全文召回）；知识库可创建、切换、删除、手动刷新 |
| 性能优化与前后对比 | 批量向量化、批量写入、刷新合并（实测 −85%）、模型缓存复用；见 `docs/EXPERIMENTS.md` |

## 架构

```
┌─────────────────────────── 浏览器 ───────────────────────────┐
│  Vue 3 SPA                                                    │
│   ├─ Transformer.js ──► ONNX Runtime Web                       │
│   │     WebGPU（优先） / WASM（自动降级）                       │
│   │     bge-small-zh-v1.5 · FP32/FP16/INT8                     │
│   ├─ 切块（句子累积 + 重叠）→ 批量向量化 → 进度/耗时             │
│   └─ 查询：端侧生成查询向量 + 关键词                             │
└───────────────┬───────────────────────────────────────────────┘
                │ HTTP /api（向量 + 原文 + 元数据）
┌───────────────▼───────────────────────────────────────────────┐
│  Node 服务（Express 5）                                        │
│   ├─ /api/kbs · /api/kbs/:name/documents · /records · /search  │
│   ├─ seekdb-js（server 模式，mysql2 底层）                      │
│   └─ 运行时管理：自动拉起本地 seekdb（或连接 SEEKDB_HOST）       │
└───────────────┬───────────────────────────────────────────────┘
                │ MySQL 协议（127.0.0.1:2881）
┌───────────────▼───────────────────────────────────────────────┐
│  seekdb 1.4.0                                                  │
│   ├─ kb_registry（关系表：知识库元信息）                         │
│   └─ kb_<name>（集合：原文 / 向量 HNSW / 元数据 + ik 全文索引）  │
│        hybridSearch = 全文召回 + 向量召回 → RRF 融合（库内完成）  │
└───────────────────────────────────────────────────────────────┘
```

## 目录结构

```
stepfun/
├── server/                 # Express + seekdb-js，自动管理本地 seekdb 进程
│   └── src/
│       ├── index.js        # 路由
│       ├── db.js           # 集合/写入/刷新/检索
│       ├── seekdb-runtime.js # 拉起或复用 seekdb
│       └── config.js
├── web/                    # Vue 3 前端
│   ├── src/lib/embedder.ts # 端侧推理：后端探测、精度、批量、缓存体积
│   ├── src/lib/chunker.ts  # 分块
│   ├── src/lib/bench.ts    # 应用内评测（Recall@5 / nDCG@5 / MRR）
│   ├── src/components/     # 导入 / 检索 / 评测 / 模型 / 知识库
│   └── public/corpus/      # 示例语料 18 篇 + 评测集 18 条查询
├── scripts/                # 验证与基准脚本
├── docs/                   # 技术说明与实验记录
└── data/                   # seekdb 数据目录（运行时生成，已 gitignore）
```

## 快速开始

前置：Node.js ≥ 20（推荐 22/24）。**Linux / macOS / WSL2 已验证**；原生 Windows 的 seekdb 二进制在本机初始化失败，见「已知问题」。

```bash
cd stepfun
npm install          # .npmrc 已配置 ignore-scripts / legacy-peer-deps，原因见文件内注释

npm run dev          # 同时起后端(8787)与前端(5173)
# 打开 http://localhost:5173
```

不想依赖 Hugging Face 网络时，可先把模型预置到本地（可选）：

```bash
bash scripts/fetch-model.sh                                   # 下载到 web/public/models
HF_ENDPOINT=https://hf-mirror.com bash scripts/fetch-model.sh # 国内镜像
```

应用启动时会探测 `/models/<model>/config.json`，存在则改为本地加载并在模型面板提示。

生产模式（后端直接托管构建产物）：

```bash
npm run build
npm start            # http://localhost:8787
```

首次启动时后端会用 `node_modules/@oceanbase/seekdb-node-<platform>/` 里的原生二进制拉起一个本地 seekdb（数据在 `data/seekdb`），约需数秒。也可连接已有实例：

```bash
SEEKDB_HOST=127.0.0.1 SEEKDB_PORT=2881 npm start
```

### 界面操作

1. 左侧「端侧模型」选精度 → 点「加载模型」（首次会下载权重，进度可见；第二次走浏览器缓存）。
2. 右上角徽章确认后端是 **WebGPU** 还是 **WASM**；勾选「强制使用 WASM」可复现降级路径。
3. `导入` 页 → 「载入示例语料」→「开始导入」，可看到向量化进度、写入耗时、刷新耗时与写后自检结果。
4. `检索` 页输入问题，切换混合 / 向量 / 全文三种模式，查看排序、分数与端到端耗时。
5. `评测` 页点「运行评测」：自动建集合、重新向量化、跑 18 条查询，输出 Recall@5 / nDCG@5 / MRR 与分阶段耗时，可导出 Markdown 填进技术说明。

## 验证与复现

```bash
# 语料/评测集自检
node scripts/check-corpus.mjs

# 后端端到端测试（自动起 server + seekdb），Linux/WSL
bash scripts/test-backend.sh

# seekdb 数据层基准：写入 / 刷新 / 三类检索延迟
bash scripts/run-with-server.sh node scripts/bench-db.mjs

# 量化前后检索质量对比（Node 侧，需本机装 @huggingface/transformers）
node scripts/eval-quality.mjs
```

> `scripts/run-with-server.sh` 会把当前代码 rsync 到 `~/stepfun-run` 并在那里安装依赖、启动服务，避免污染仓库。

## 已知问题

| 现象 | 原因 / 处理 |
| --- | --- |
| 原生 Windows 上 seekdb 启动失败（`init sql expr static var` / `OB_ERR_UNEXPECTED -4016`） | seekdb 1.4.0 的 Windows 构建在该机器上初始化失败，与体积无关。请用 WSL2（Ubuntu 24.04 已验证）或 Linux 运行后端。 |
| Ubuntu 24.04 报 `libaio.so.1: cannot open shared object file` | 24.04 改名为 `libaio.so.1t64`。`scripts/linux-env.sh` 会在用户目录建兼容软链，无需 sudo。 |
| 嵌入式模式（`@seekdb/js-bindings`）报 `cannot allocate memory in static TLS block` | 需 `LD_PRELOAD=libseekdb.so`；本项目的 server 模式不做此依赖。 |
| 嵌入式模式 `refresh_index()` 超时、向量检索为空 | 该环境下嵌入式实例的索引构建不稳定，因此默认改走「本地 server（spawn）」模式。 |
| WASM 只有单线程 | 页面未开启 cross-origin isolation，`SharedArrayBuffer` 不可用；属预期行为。 |

## 文档

- [`docs/TECHNICAL.md`](docs/TECHNICAL.md) —— 一页技术说明（模型与量化、端侧运行、seekdb 使用、状态与优化）
- [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) —— 实验记录：环境、方法、原始数据、复现命令
