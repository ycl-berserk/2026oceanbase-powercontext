# 一页技术说明

**题目**：端侧 AI 推理性能优化与 seekdb 混合检索
**形态**：Vue 3 单页应用 + Node 服务 + 本地 seekdb；文档向量化与查询向量化全部在浏览器内完成，召回与融合全部在 seekdb 内完成。

---

## 1. 模型与量化

**模型**：`Xenova/bge-small-zh-v1.5`（BAAI `bge-small-zh-v1.5` 的 ONNX 发布版，MIT），512 维，CLS pooling + L2 归一化；可切换 `Xenova/all-MiniLM-L6-v2`（384 维）做对照。

| 精度 | dtype | 权重文件 | 体积（onnx 权重） | 压缩比 |
| --- | --- | --- | --- | --- |
| FP32（基线） | `fp32` | `model.onnx` | **90.46 MiB** | 1.00× |
| FP16 | `fp16` | `model_fp16.onnx` | **45.30 MiB** | **2.00×** |
| INT8 | `q8` | `model_quantized.onnx` | **22.90 MiB** | **3.95×** |

> 体积按同一口径统计：Hugging Face 上对应 onnx 文件字节数（另加 tokenizer 0.43 MiB）。应用内还会用 Cache Storage 中各响应的 `content-length` 实测一次，界面上显示的是实测值。

**量化方式**：直接使用仓库提供的 onnxruntime 动态量化权重（权重 INT8、激活推理时按范围量化），无需自行转换；FP16 为权重半精度。三档共用同一套集合结构（维度相同），但向量数值有差异，评测时分别建集合、分别向量化。

**权重获取与（可选）自行量化**：

| 精度 | 下载路径（Hugging Face） |
| --- | --- |
| FP32 | `https://huggingface.co/Xenova/bge-small-zh-v1.5/resolve/main/onnx/model.onnx` |
| FP16 | `.../onnx/model_fp16.onnx` |
| INT8 | `.../onnx/model_quantized.onnx` |

模型由 Transformers.js 按 `dtype` 自动映射到对应文件，不需要手动指定路径。若要从 PyTorch 原始权重自行复现量化：

```bash
optimum-cli export onnx --model BAAI/bge-small-zh-v1.5 --task feature-extraction onnx/base/
optimum-cli onnxruntime quantize --onnx-input onnx/base/model.onnx --avx512 --output onnx/int8/
```

**检索质量**（48 个分块 / 18 条查询 / 文档级 Top-5，同语料同金标）：

| 精度 | Recall@5 | nDCG@5 | MRR |
| --- | --- | --- | --- |
| FP32 | 86.1% | 82.6% | 0.834 |
| FP16 | 86.1% | 82.6% | 0.834 |
| INT8 | 86.1% | 82.6% | 0.834 |

三档在该评测集上排序完全一致，即量化未造成可观测的质量损失。**需要说明局限**：语料只有 18 篇、查询区分度高，属于"小样本一致性"结论；更大的语料上 INT8 通常在 Recall@5 上有零点几个百分点的波动，建议用应用内「评测」页在自有语料上复测。

**端侧吞吐**（同一批 48 个分块，Node/onnxruntime CPU 口径，仅用于横向对比）：

| 精度 | 向量化耗时 | 吞吐 | 单条查询 embedding P50 |
| --- | --- | --- | --- |
| FP32 | 645 ms | 19 355 字/秒 | 4 ms |
| FP16 | 700 ms | 17 845 字/秒 | 4 ms |
| INT8 | 360 ms | 34 658 字/秒 | 2 ms |

批大小影响明显（FP32，同一批文本）：batch=1 → 1 181 字/秒，batch=8 → 1 712，batch=32 → 1 944。应用默认 batch=8，并允许在导入页调整。

---

## 2. 端侧运行

**运行时**：Transformers.js 4.x + ONNX Runtime Web，`pipeline('feature-extraction', model, { device, dtype })`；推理全部发生在浏览器，代码里没有任何云端推理调用。

**WebGPU 优先与 WASM 自动降级**（`web/src/lib/embedder.ts`）：

1. 探测 `navigator.gpu` 并 `requestAdapter()`，记录失败原因（无 API / 适配器为 null / 异常）。
2. 可用 → `device: 'webgpu'`；不可用 → `device: 'wasm'`。
3. 即使用 WebGPU，`pipeline()` 抛错时也会捕获并重建为 WASM（同时把 fp16 回退到 fp32，因为 WASM 无 fp16 支持），并把原因写入 `info.note`。
4. 界面顶部徽章常驻显示当前后端（WebGPU / WASM）与体积、精度；模型面板显示适配器名称、加载耗时与降级原因；勾选「强制使用 WASM」可复现降级路径。

**首帧与后续分开计时**：模型加载后先跑一次"预热"文本，把 ONNX 图优化 / WebGPU 管线编译的成本算进 `loadMs`，用户第一次真实查询不再承担这部分开销。

**验证方式**：Chrome/Edge 上正常进入为 WebGPU；勾选强制 WASM（或在不支持 WebGPU 的环境）后徽章变为 WASM，核心流程（导入、检索、评测）保持可用。

---

## 3. seekdb 使用

**部署**：本地 server 模式。后端启动时若 `SEEKDB_HOST` 未设置，会用 `@oceanbase/seekdb-node-<platform>` 自带原生二进制拉起 seekdb（TCP，默认 2881，数据在 `data/seekdb`），随后用 seekdb-js 以 MySQL 协议连接；也支持连接已有实例。

**数据结构**：

```sql
-- 关系表：知识库注册信息
CREATE TABLE kb_registry (
  name       VARCHAR(64)  NOT NULL,
  label      VARCHAR(191) NOT NULL,
  model      VARCHAR(191) NOT NULL,
  dimension  INT          NOT NULL,
  created_at BIGINT       NOT NULL,
  updated_at BIGINT       NOT NULL,
  PRIMARY KEY (name)
);

-- 集合：seekdb 分配的物理表名形如 c$v2$<uuid>，逻辑名是 kb_<name>
-- 下面是从实例上 SHOW CREATE TABLE 拿到的真实 DDL（512 维示例）
CREATE TABLE `c$v2$<uuid>` (
  `_id`       VARBINARY(512) NOT NULL,       -- <docId>#<chunkIndex>，可复现
  `document`  STRING         DEFAULT NULL,   -- 原文分块
  `embedding` VECTOR(512)    DEFAULT NULL,   -- 浏览器算出的向量
  `metadata`  JSON           DEFAULT NULL,   -- docId / docTitle / chunkIndex / chars / source
  PRIMARY KEY (`_id`),
  FULLTEXT KEY `idx_fts` (`document`)
    WITH PARSER ik PARSER_PROPERTIES=(ik_mode="smart") BLOCK_SIZE 16384,
  VECTOR KEY `idx_vec` (`embedding`)
    WITH (DISTANCE=COSINE, TYPE=HNSW, LIB=VSAG, M=16, EF_CONSTRUCTION=200,
          EF_SEARCH=64, SYNC_MODE=ASYNC) BLOCK_SIZE 16384
) ORGANIZATION HEAP DEFAULT CHARSET = utf8mb4 ROW_FORMAT = DYNAMIC;
```

对应 seekdb-js 的建集合代码（`server/src/db.js`）：

```js
new Schema({
  fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
  vectorIndex: new VectorIndexConfig({
    hnsw: { dimension: 512, distance: 'cosine' },
    embeddingFunction: null,   // 向量由浏览器计算，服务端不做嵌入
  }),
})
```

**混合检索**：调用 `collection.hybridSearch({ query: { whereDocument: { $contains } }, knn: { queryEmbeddings }, rank: { rrf: { rankConstant: 60 } }, nResults })`。seekdb 内部走 `DBMS_HYBRID_SEARCH`：全文召回与向量召回在库内并行执行，再用 RRF 融合，客户端只提交"查询文本 + 查询向量 + 融合参数"，不做二次拼接。界面提供混合 / 向量 / 全文三种模式用于对照。

**增量写入与索引刷新**：一次导入的多批 `add()` 全部完成后才调用一次 `refresh_index()`；随后做写后自检——(a) 按 id 回读确认写入，(b) 用首条向量做 Top-K 召回，(c) 用该块文本片段做全文匹配，三项结果返回给前端展示。新增文档在刷新完成后即可检索（后端测试用例 `新增文档刷新后可检索` 覆盖）。

**数据层实测**（600 分块 × 512 维，本地 server，Ubuntu 24.04/WSL2）：

| 指标 | 数值 |
| --- | --- |
| 写入 600 条 | 282 ms（1.09M dims/s，单批 100 条 P50 45 ms） |
| 索引刷新（合并一次） | **610 ms** |
| 索引刷新（每批都刷，6 次） | 4 027 ms |
| 向量检索 | P50 1.4 ms / P95 5.3 ms |
| 全文检索 | P50 10.2 ms / P95 14.7 ms |
| 混合检索（RRF） | P50 13.1 ms / P95 20.7 ms |

---

## 4. 状态管理与优化

- **集合与会话状态**：每个知识库一个集合，注册表记录模型与维度；切换知识库即切换集合，导入时若维度与当前模型不符会被前端拦截并提示新建；删除知识库会级联删除集合与注册记录；集合名做了 `-`→`_` 的确定性映射（seekdb 集合名只允许字母数字下划线）。
- **刷新合并**：逐批刷新是 O(n) 重建，6 批累计 4 027 ms；合并成导入结束刷新一次只需 610 ms，**节省 85%**。界面把"写入耗时 / 刷新耗时"分开显示，便于观察这一差异。
- **批处理**：向量化 batch=8（可调），写入每批 64 条，兼顾吞吐与进度反馈（每批之间让出一帧，进度条不卡死）。
- **模型缓存**：Transformers.js 走浏览器 Cache Storage，第二次进入页面不重复下载；界面用缓存条目实测体积。
- **检索侧**：RRF 候选窗口 40、`rankConstant` 可调；Top-K 默认 5，与评测口径一致。

**端到端延迟构成**（查询路径）：端侧查询向量化（个位数到数十毫秒，取决于后端与精度）+ seekdb 混合检索（约 13 ms @600 分块）+ 本地 HTTP 往返。因此端侧推理是主要成本项，这也解释了为什么优先 WebGPU、并对模型做量化。

**浏览器内实测**（Chrome + Intel gen-12lp 集显，48 个分块）：

| 配置 | 模型加载 | 48 块向量化 | 吞吐 | 查询向量化 | seekdb | 端到端 |
| --- | --- | --- | --- | --- | --- | --- |
| INT8 + WebGPU | 3.84 s | 18.07 s | 691 字/秒 | — | — | — |
| FP16 + WebGPU | 6.09 s | 4.05 s | 3 083 字/秒 | 269 ms | 13 ms | 293 ms |
| INT8 + WASM | 2.25 s | 23.87 s | 523 字/秒 | 9 ms | 12 ms | 31 ms |

一个重要反直觉结论：**WebGPU 上 INT8 比 FP16 慢约 4.5 倍**，因为 q8 权重需要反量化。因此推荐组合是「WebGPU + FP16」「WASM + INT8」，界面默认值可据此设置。


---

## 5. 已知限制

1. 浏览器侧的分阶段耗时（模型下载/加载、文档向量化、查询向量化、端到端）需要在目标机器上运行应用内「评测」页采集；本文档中的模型吞吐是 Node/onnxruntime CPU 口径，用于横向对比，不等价于浏览器 WebGPU 数值。
2. seekdb 1.4.0 的 Windows 原生构建在本次开发机上初始化失败（`OB_ERR_UNEXPECTED -4016`），因此后端在 Ubuntu 24.04（WSL2）上验证；原生 Windows 建议走 WSL2 或 Linux。
3. 量化质量结论基于 18 篇语料，扩大语料后需复测。
