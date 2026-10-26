# ReviewMate 架构

## 总览

```
浏览器（web/）
   │  HTTP JSON
   ▼
FastAPI（src/reviewmate/api.py）
   │
   ├── ReviewMateService（service.py）
   │      ├── 导入：chunking.py → embeddings.py → SeekDBStore
   │      ├── 提问：embedding → seekdb 混合检索 → PowerContext 记忆检索
   │      │        → AnswerWriter（DeepSeek 或本地摘录）→ 引用 → QA 日志
   │      ├── 薄弱点 / 笔记：PowerContext remember
   │      └── 复习计划：PowerContext 薄弱点 + 文档清单 → 模板或大模型
   │
   ├── SeekDBStore（store.py）——嵌入式 seekdb（PyMySQL 协议）
   └── PowerContextMemory（memory.py）——PowerContext REST API
```

## 数据模型（seekdb）

| 表 | 作用 |
|---|---|
| `meta` | 记录 embedding 模型与维度，防止配置漂移 |
| `documents` | 文档元数据：课程、标题、来源、许可、标签、路径、sha256、片段数 |
| `chunks` | 检索单元：正文、标题、页码、`VECTOR(512)`、全文索引、HNSW 向量索引 |
| `qa_log` | 每次提问的问题、课程、证据 chunk、回答模式、耗时 |
| `sessions` | ReviewMate 会话 ID 到 PowerContext scope 的映射 |

`chunks` 把正文与向量放在同一张表，避免「向量表与正文表分别删除再插入」导致孤儿向量。全文索引使用 `WITH PARSER NGRAM`，中文无需分词服务；向量索引使用 `DISTANCE=l2, TYPE=hnsw, LIB=vsag`。查询向量做 L2 归一化，因此 L2 距离与余弦相似度单调对应。

## 混合检索

`SeekDBStore.search()` 只发一条 SQL，`UNION ALL` 两路候选：

1. 全文路：`MATCH(content) AGAINST(%s)`，按 `fts_score` 降序。
2. 向量路：`l2_distance(embedding, %s) APPROXIMATE`，按距离升序。

两路都带课程等结构化过滤，并各自 `LIMIT channel_limit`（默认 18）。向量索引刚写入时可能处于预热阶段，检索结果为空时脚本最多重试 6 次（每次 250ms）。

候选进入 Python 后：

- 相对阈值过滤：全文分数 ≥ 本路最高分的 25%；向量距离 ≤ 本路最小距离 + 0.45。
- RRF 融合：`score = Σ 1/(60 + rank)`，同分按距离、chunk_id 稳定排序，最后归一化到最高分为 1。
- 证据装配：按 `doc_id` 批量取文档元数据，生成标题、来源、页码与原文。

检索轨迹会返回浏览器：两路候选数、过滤后保留数、是否重试、阈值参数。界面「查看检索轨迹」可直接核对。

## 回答与引用

`AnswerWriter` 支持两种模式：

- **DeepSeek**：配置 `DEEPSEEK_API_KEY` 后，用编号证据与记忆构造接地提示词，要求只依据证据回答并标注 `[n]`。
- **本地摘录**：没有密钥时的默认模式。按检索顺序选取前缀相关证据，输出「笔记里最相关的段落是：」+ 编号要点，并明确提示当前为摘录模式。

无论哪种模式，服务端都会把被回答使用的 chunk 标为 `used`，前端默认展开直接引用、折叠其余候选，点击引用可回到证据卡片。

## PowerContext 记忆

- 每个 ReviewMate 会话对应一个 PowerContext scope，标题为 `温故 ReviewMate · {session_id}`，使用幂等键创建，映射缓存在 seekdb 的 `sessions` 表。
- 每次提问自动写入 `study-progress` 记忆：问题、课程、参考笔记标题。
- 用户标记薄弱点写入 `weak-point` 记忆：主题 + 补充说明。
- 后续提问先用问题检索 scope 内的记忆，命中结果注入回答；复习计划读取所有 `weak-point`。
- PowerContext 不可用时，检索与回答继续工作，界面显示「未连接」，复习计划降级为仅基于文档的模板。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | seekdb、PowerContext、embedding、LLM 状态 |
| GET | `/api/documents` | 知识库文档与课程统计 |
| POST | `/api/ask` | 提问，返回回答、引用、记忆与检索轨迹 |
| GET | `/api/memory` | 当前会话记忆 |
| POST | `/api/memory/weak` | 标记薄弱点 |
| POST | `/api/memory/note` | 手动记录学习笔记 |
| POST | `/api/review-plan` | 生成复习计划 |
| GET | `/api/history` | 会话问答记录 |

会话 ID 只允许字母、数字、下划线与短横线，长度 1–64，避免把任意字符串传给外部服务。

## 降级与边界

| 场景 | 行为 |
|---|---|
| PowerContext 未启动 | 检索与回答正常；记忆区提示未连接；计划退化为文档模板 |
| 无 DeepSeek Key | 本地摘录模式，引用与原文定位不受影响 |
| 首次运行 / 模型未缓存 | 需要联网下载 embedding 模型；之后可离线 |
| seekdb 向量索引冷启动 | 检索自动重试；验收脚本会记录 `attempts` |
| DB 的 embedding 维度与配置不符 | 启动时抛错，避免写入错维向量 |

## 取舍

- **单表存正文与向量**：写入/删除一致，代价是表更宽，适合个人复习规模。
- **Python 侧 RRF**：seekdb 一次 SQL 返回两路候选，融合逻辑可测试、可解释；没有依赖数据库扩展。
- **本地 embedding + 可选大模型**：评审无需申请 API Key 即可跑通；有 Key 时再提升生成质量。
- **PowerContext 记忆不做强一致依赖**：学习记忆是增强项，不是回答正确性的唯一来源。
