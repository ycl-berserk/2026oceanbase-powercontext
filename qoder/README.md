# Qoder 生态赛道提交

项目：**温故 ReviewMate** —— 用 seekdb 混合检索回到笔记原文，用 PowerContext 记住薄弱点与复习进度。

| 项目 | 值 |
|---|---|
| 项目目录 | `qoder/reviewmate/` |
| 分支 | `qoder-reviewmate`（基于 `origin/2026-competition-ecosystem`） |
| 项目内容提交 | `56d8579e` |
| 项目网站 | <https://reviewmate-5967u15pefr.qoder.zone> |
| Qoder UID | `aliyun-1585490604181694` |
| 运行说明 | `qoder/reviewmate/README.md`「快速开始」 |
| 验收入口 | 在 `qoder/reviewmate/` 执行 `make verify`（12 项自动检查） |

技术分工：

- **seekdb**：笔记片段与 512 维向量存储；一条 SQL 完成全文 + 向量混合召回；课程过滤；引用原文；问答日志与会话映射。
- **PowerContext**：每个学习会话一个 scope；自动记录提问进度；薄弱点写入；后续提问与复习计划复用记忆。

提交内容不含真实 API Key、密码或数据库文件；`.env.example` 仅含占位值。
