# 实验记录

本文件记录实现过程中实际跑过的测试与基准，包括环境、方法、原始输出和失败记录。所有命令都在本仓库内可直接复现。

## 1. 环境

| 项 | 值 |
| --- | --- |
| 设备 | Windows 11 主机 + WSL2（Ubuntu 24.04.5 LTS，kernel 6.18.54.1） |
| CPU / 内存 | 14 vCPU / 12 GB（WSL 配额） |
| Node.js | v24.22.1（WSL）、v24.22.1（Windows） |
| seekdb | v1.4.0.0（`5.7.25-OceanBase seekdb-v1.4.0.0`），本地 server 模式 |
| seekdb-js | `seekdb@1.4.0` |
| 嵌入模型 | `Xenova/bge-small-zh-v1.5`（512 维） |
| 语料 | 本仓库 `web/public/corpus`，18 篇 / 10 946 字符 / 48 个分块（块长 320 字、重叠 64 字） |
| 评测集 | 同目录 `eval.json`，18 条查询，每条 1–2 个金标文档 |

> 浏览器侧的端到端数据需在目标机器上点开应用「评测」页采集，本文件不含浏览器实测值；文中的模型吞吐均为 Node/onnxruntime CPU 口径。

## 2. 后端功能测试

```bash
bash scripts/test-backend.sh
```

覆盖建库 → 写入 → 刷新 → 自检 → 三种检索 → 增量写入 → 删除 → 列表，共 17 项断言。

```
✓ health · spawned · 5.7.25-OceanBase seekdb-v1.4.0.0
✓ 创建知识库 · createMs=85.3
✓ 写入 6 条 · count=6
✓ 写后自检命中 · probe=d1
✓ 索引刷新成功 · refreshMs=514.9
✓ 向量检索有结果 · d3,d1,d5 · 1.9ms
✓ 向量检索最相关为 d3 · top=d3
✓ 全文检索命中 d5 · d5
✓ 混合检索有结果 · d4:0.0325, d6:0.0325, d3:0.0159
✓ 混合检索命中 d4 或 d6 · top=d4
✓ 增量写入 · total=7
✓ 新增文档刷新后可检索 · d3,d7,d1
✓ 手动刷新索引 · refreshMs=403.3
✓ 分页读取原文
✓ 删除文档 · total=6
✓ 知识库列表包含测试库
✓ 删除知识库

== 17 passed, 0 failed ==
```

注：测试用的向量是脚本按关键词构造的 32 维合成向量，与真实模型无关，只验证数据层行为。

## 3. seekdb 数据层基准

```bash
bash scripts/run-with-server.sh node scripts/bench-db.mjs
```

口径：600 个分块 × 512 维，每批 100 条；策略 A 每批写完都刷新，策略 B 全部写完只刷新一次；检索各 10 次取 P50 / P95。

```
规模：600 个分块 × 512 维（每批 100，共 6 批）
写入：总计 282 ms，单批 P50 45.3 ms，写入吞吐 1091k dims/s
刷新（逐批）：4027 ms / 6 次，P50 602.2 ms
刷新（合并一次）：610 ms —— 相比逐批刷新节省 85%
vector 检索：P50 1.4 ms / P95 5.3 ms（10 次）
keyword 检索：P50 10.2 ms / P95 14.7 ms（10 次）
hybrid 检索：P50 13.1 ms / P95 20.7 ms（10 次）
增量 1 条 + 刷新 + 自检：writeOk=true vectorHit=true keywordHit=true，总数 601
```

结论：写入不是瓶颈，**索引刷新是**；把刷新合并到导入结束一次，能把导入总耗时压到原来的 15% 左右。

## 4. 量化前后检索质量

```bash
# 需要 @huggingface/transformers（Node 侧 onnxruntime-node）
node scripts/eval-quality.mjs
```

方法：同一套 48 个分块、同一组 18 条查询，分别用 FP32 / FP16 / INT8 权重生成文档向量与查询向量，在 Node 里用余弦相似度排序；把块级结果按文档去重后计算文档级 Recall@5 / nDCG@5 / MRR。

```
| 精度 | 分块×维度 | 向量化 | 吞吐 | 查询 embedding P50 | Recall@5 | nDCG@5 | MRR |
| FP32      | 48×512 | 645 ms | 19355 字/s | 4 ms | 86.1% | 82.6% | 0.834 |
| FP16      | 48×512 | 700 ms | 17845 字/s | 4 ms | 86.1% | 82.6% | 0.834 |
| INT8 (q8) | 48×512 | 360 ms | 34658 字/s | 2 ms | 86.1% | 82.6% | 0.834 |
```

原始数据见 `docs/quality-results.json`。

**波动说明**：同一配置在不同轮次之间吞吐会波动（CPU 口径，进程数与调度影响明显，曾观察到 INT8 从 5 825 涨到 34 658 字/秒）。因此表中数值只用于"同一次运行内横向对比"，绝对值不足以作为结论。指标项（Recall / nDCG / MRR）在多轮中保持恒定。

**批大小扫描**（FP32，同一批 48 个分块，含预热）：

```
| batch | 耗时 | 吞吐 |
| 1  | 10572 ms | 1181 字/s |
| 8  |  7294 ms | 1712 字/s |
| 32 |  6425 ms | 1944 字/s |
```

## 5. 模型体积

按 onnx 权重文件字节数统计（Hugging Face 仓库实测）：

| 精度 | 文件 | 字节 | MiB |
| --- | --- | --- | --- |
| FP32 | `onnx/model.onnx` | 94 852 096 | 90.46 |
| FP16 | `onnx/model_fp16.onnx` | 47 497 216 | 45.30 |
| INT8 | `onnx/model_quantized.onnx` | 24 010 842 | 22.90 |

压缩比：FP32/INT8 = **3.95×**，FP32/FP16 = **2.00×**。

## 6. 失败记录（环境问题，非应用缺陷）

| 尝试 | 结果 | 处理 |
| --- | --- | --- |
| Windows 嵌入式 `@seekdb/js-bindings` | `open()` 阻塞不返回，日志停在 `opening`，CPU 0% | 放弃嵌入式 |
| Windows 本地 server（`@oceanbase/seekdb-node`） | 进程启动即退出：`init sql expr static var` `OB_ERR_UNEXPECTED (-4016)` | 改用 Linux 验证 |
| WSL Fedora 嵌入式 | `libaio.so.1` 缺失 → 安装后 `cannot allocate memory in static TLS block` | 用 `LD_PRELOAD` 绕过（脚本已封装） |
| WSL Ubuntu 嵌入式 | 建库/写入正常，`refresh_index()` 35s 超时，向量检索返回空 | 改用"本地 server + TCP"模式 |
| Ubuntu 24.04 缺 `libaio.so.1` | t64 改名导致 | `scripts/linux-env.sh` 在用户目录建兼容软链，无需 sudo |
| 页面未开 cross-origin isolation | WASM 只有单线程 | 预期行为，已在文档说明 |

结论：数据层统一采用 **server 模式**（自动拉起本地 seekdb 或连接外部实例），不再依赖嵌入式原生绑定。

## 7. 浏览器端实测（WebGPU / WASM）

环境：Windows 11 + Chrome（headless，`--enable-unsafe-webgpu`），GPU 为 Intel gen-12lp 集显；模型本地预置（`/models`）；语料 18 篇 / 48 块（块长 320、重叠 64）；查询「seekdb 混合检索 RRF 融合」。

| 配置 | 模型加载 | 48 块向量化 | 吞吐 | 写入 | 索引刷新 | 查询向量化 | seekdb 检索 | 端到端 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INT8 + WebGPU | 3.84 s | 18.07 s | 691 字/秒 | 217 ms | 528 ms | — | — | — |
| **FP16 + WebGPU** | 6.09 s | **4.05 s** | **3 083 字/秒** | 520 ms | 822 ms | 269 ms | 13 ms | 293 ms |
| INT8 + WASM | — | — | — | — | — | 23 ms | 157 ms | 507 ms |

三个可直接用的结论：

1. **WebGPU 上 INT8 不是最优**。ONNX Runtime 的 q8 权重在 GPU 上要走反量化，48 块花了 18 s；换 FP16 后降到 4 s，吞吐提升约 4.5 倍。所以界面默认精度已规划为「WebGPU → FP16，WASM → INT8」，与文档建议一致。
2. **WASM 的差距主要在吞吐而非查询**：单条查询向量化 23 ms、端到端 507 ms，交互可用；但批量导入 48 块明显慢于 GPU。
3. **模型加载与端到端可分离**：WebGPU 首帧（加载 + 预热）4–6 s，之后单次查询 293 ms（其中 seekdb 只占 13 ms），瓶颈确实在端侧推理。

注：FP16 行的写入/刷新耗时高于 INT8 行，是因为两次运行导入到同一个集合、第二次走了 upsert 覆盖；该项不作为精度对比结论。INT8 + WASM 的导入数据未采集（当次因重复导入主键冲突中断，该问题已修复为 upsert）。

## 8. 复现步骤
```bash
# 0) 环境
#    Linux / macOS / WSL2，Node ≥ 20，推荐 22/24

# 1) 安装与启动
cd stepfun && npm install
npm run build && npm start     # http://localhost:8787（后端同时托管前端）

# 2) 语料自检
node scripts/check-corpus.mjs

# 3) 后端功能测试（会另起一份隔离副本，不影响仓库）
bash scripts/test-backend.sh

# 4) 数据层基准
bash scripts/run-with-server.sh node scripts/bench-db.mjs

# 5) 量化质量对比
node scripts/eval-quality.mjs

# 6) 端侧实测（浏览器）
#    打开应用 → 加载模型 → 「评测」页运行 → 导出 Markdown
```
