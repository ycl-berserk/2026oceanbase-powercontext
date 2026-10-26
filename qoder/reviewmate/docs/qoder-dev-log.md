# Qoder 开发记录

> 项目主要开发工作在 Qoder 中完成。本文按开发阶段整理 Qoder 承担的工作、关键提示词与调试过程。
>
> **Qoder 账号 UID**：`aliyun-1585490604181694`
>
> **待作者补充（提交前）**：从 Qoder 会话导出的关键截图或录屏，放入 `docs/qoder/`。截图应覆盖需求拆解、编码、调试与验收四个环节，并与本文相互对应。

## 开发环境

- Qoder CLI（本机 WSL Ubuntu），工作目录 `~/qoder-reviewmate`，与既有比赛仓库隔离。
- Python 3.12.3，uv 管理虚拟环境；seekdb 通过 `pylibseekdb` 嵌入式打开；PowerContext 1.2.0 以 SQLite 后端运行在 `127.0.0.1:8100`。
- 浏览器验证使用 Chromium 无头模式 + CDP 截图。

## 阶段一：需求拆解与工作区隔离

**提示词（摘要）**

> 阅读本机 WSL 中的 OceanBase 大赛仓库，为 Qoder × OceanBase 赛题做基础工作。不要修改该仓库，因为另一个会话正在修改它。项目方向：课程笔记/论文复习助手；同时使用 seekdb 与 PowerContext。

Qoder 的工作：

- 阅读赛题任务、评分说明、PowerContext 仓库说明，确认提交物与硬性要求。
- 建立独立项目 `qoder-reviewmate`，避免触碰原仓库。
- 确定技术分工：seekdb 做混合检索与日志，PowerContext 做跨会话学习记忆；设计「提问 → 原文引用 → 标记薄弱点 → 复习计划」闭环。

## 阶段二：seekdb 技术验证

Qoder 先写一次性验证脚本，确认嵌入式 seekdb 的能力边界，再把结论固化为正式代码：

- 通过 `pylibseekdb.open()` 获取连接参数，再用 PyMySQL 执行 SQL；`pylibseekdb.Cursor` 不接受参数绑定。
- 中文全文检索使用 `WITH PARSER NGRAM`；默认分词器对中文短语无效。
- 向量索引 `WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag)` 冷启动可能返回空结果，需要短重试。
- 向量做 L2 归一化后，L2 距离可用于近似余弦排序。
- 将正文、全文索引与向量放在同一张 `chunks` 表，避免分开删除/插入产生孤儿向量。

最终 `src/reviewmate/store.py` 用一条 `UNION ALL` SQL 返回全文与向量两路候选，Python 侧做相对阈值过滤与 RRF。

## 阶段三：PowerContext 技术验证

**Qoder 遇到的配置问题**

- 最初尝试的 `POWERCONTEXT_SERVER_DATABASE_PATH` 被服务端拒绝（Pydantic 报 `extra_forbidden`）；改为 `POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:////...`。
- 通过后台方式启动的进程在会话退出后被回收；改为由会话前台托管的后台任务，确认端口与健康检查。
- `/v1/context/prepare` 对原始记忆返回空内容，不作为主路径；应用改用 `/v1/memory/search` 与 `/v1/memory/entries/list`。

验证结果：scope 创建、remember、search、entries 全部可用；第二次提问能检索到第一次写入的记忆。

## 阶段四：应用与界面

Qoder 完成的主要文件：

| 模块 | 文件 | 关键工作 |
|---|---|---|
| 配置 | `src/reviewmate/config.py` | 冻结 dataclass、`.env` 加载、项目根路径 |
| 切分 | `src/reviewmate/chunking.py` | frontmatter、H1/H2/H3、页码标记、420 字切分与重叠、稳定 chunk_id |
| 向量 | `src/reviewmate/embeddings.py` | FastEmbed 懒加载、归一化、SQL 向量字面量 |
| 存储 | `src/reviewmate/store.py` | schema、混合检索、RRF、证据装配、QA 日志、健康统计 |
| 记忆 | `src/reviewmate/memory.py` | 幂等 scope、remember/search/entries、超时与降级 |
| 回答 | `src/reviewmate/llm.py` | DeepSeek 接地提示词、本地摘录回退、相关证据前缀门控 |
| 编排 | `src/reviewmate/service.py` | 导入、提问、自动记忆、薄弱点、复习计划、会话校验 |
| API | `src/reviewmate/api.py` | FastAPI 生命周期、8 个接口、静态站点挂载 |
| CLI | `src/reviewmate/cli.py` | ingest/ask/stats/memory/mark-weak/plan/history |
| 前端 | `web/` | 论文纸感视觉、会话隔离、引用卡、检索轨迹、移动端 |

## 阶段五：调试与体验修正

| 问题 | 处理 |
|---|---|
| `No database selected` | 为 PyMySQL 连接补 `database=test`（seekdb 嵌入式默认库） |
| 回答混入无关课程的向量结果 | 增加相对阈值过滤（全文 ≥ 最高分 25%，向量 ≤ 最小距离 + 0.45），回答只取相关前缀 |
| 引用里可能包含未被回答使用的片段 | 服务端标记 `used`，前端默认展开直接引用、折叠其余候选 |
| 薄弱点文字重复 | 记忆列表去掉与类型标签重复的前缀 |
| 截图里 toast 未消失 | 截图脚本等待 toast 完成淡出后再捕获 |
| 验收脚本竞态 | 标记薄弱点后等待 `薄弱点` 条目出现，再请求复习计划 |

## 阶段六：验收与交付

- 编写 `scripts/verify.py`，把 seekdb 两路检索、原文页码、PowerContext 写入/复用、复习计划、QA 日志固化为 12 项 PASS/FAIL 检查。
- 使用无头 Chromium 实际走通页面并生成 5 张截图，检查控制台异常、记忆数量与计划内容。
- 整理 `README.md`、`Makefile`、架构与验证文档、提交清单与展示站。
- 通过 Qoder CLI 创建并发布 Qoder Sites 展示站，设为公开访问，并用无登录浏览器复核。

**验收命令**

```bash
make test
make lint
make verify
```

最近一次：单元测试 10 通过 / 1 跳过（集成测试需显式开启），ruff 无告警，验收 12/12 通过。

## 提交前还需作者完成

1. 在 Qoder 中打开本项目会话，导出 3–5 张关键截图或一段 1–2 分钟录屏，覆盖需求、编码、调试、验收。
2. 项目已复制到比赛仓库分支 `qoder-reviewmate` 的 `qoder/reviewmate/`，项目内容 commit 为 `d0f8ed2f`。
3. 用无痕窗口复核代码仓库权限与运行说明。
