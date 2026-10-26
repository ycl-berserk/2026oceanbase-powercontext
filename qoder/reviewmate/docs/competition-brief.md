# 赛题对照与作品说明

赛题：**Build with Qoder——用 Qoder 做一个让学习、科研和工作更高效的项目**（OceanBase 2026 数据库大赛 · Qoder 生态赛道，20 分）。

## 需求对照

| 赛题要求 | ReviewMate 的实现 | 可核对材料 |
|---|---|---|
| 从真实痛点出发 | 笔记分散、答案无出处、薄弱点每次丢失 | README「解决的痛点」、演示流程 |
| 用 Qoder 完成主要开发 | 需求拆解、seekdb/PowerContext 验证、编码、调试、验收脚本、文档均在 Qoder 会话中完成 | `docs/qoder-dev-log.md` + 待补截图/录屏 |
| 实际使用 seekdb 或 PowerContext（至少一种） | 两者同时使用，且有明确分工 | 见下表 |
| 通过 Qoder Sites 发布项目网站，任何人可访问 | 已发布：<https://reviewmate-5967u15pefr.qoder.zone>，无需登录 | `docs/submission-checklist.md` |
| 网站含简介、问题、功能、截图、仓库链接、体验入口 | `site/index.html` 覆盖这些栏目 | 站点与截图 |
| 可运行性 | Makefile 一条命令安装/导入/启动/验收；无 API Key 也可运行 | README、`docs/verification.md` |
| 验证样例 | 固定问题、固定笔记、12 项自动检查、JSON 证据 | `scripts/verify.py`、`data/verification/report.json` |
| 提交不含真实凭据 | `.env.example` 全部占位；`.gitignore` 排除 `.env` 与本地数据 | 仓库检查 |

## 两种指定技术的分工

| 技术 | 不是「只安装」，而是实际参与功能 |
|---|---|
| seekdb | 笔记与向量存储；一条 SQL 的全文 + 向量混合召回；课程过滤；引用原文；QA 日志与会话映射 |
| PowerContext | 每会话 scope；自动记录提问进度；薄弱点写入；第二次提问复用记忆；复习计划读取薄弱点 |

## 评价维度对应

| 维度 | 当前状态 |
|---|---|
| 实用价值 | 面向真实复习流程，问题与操作都来自课程笔记场景 |
| 使用效果 | 已具备可记录的使用日志与 QA 历史；真实用户数据待作者邀请同学试用后补充 |
| 完成度与体验 | Web、CLI、问答、引用、记忆、计划、移动端、降级模式齐全 |
| 技术结合 | seekdb 与 PowerContext 均有可核对的输入输出，不是装饰性依赖 |
| Qoder 开发实践 | 开发记录已按阶段整理；待补 Qoder 截图/录屏与 UID |
| 工程质量 | 配置、测试、lint、验收脚本、架构文档齐全 |

## 风险与待办

| 风险 | 应对 |
|---|---|
| Qoder Sites 未发布 | 已用个人账号发布，可见范围设为「任何人都可访问」，并完成无痕复核 |
| Qoder UID / 截图缺失 | UID 已填写；Qoder 会话截图/录屏仍待作者导出 |
| 评审环境无网络 | 首次 embedding 模型下载需要网络；README 注明，可预置模型缓存 |
| PowerContext 未启动 | 应用自动降级，但记忆类验收项会失败；运行说明将启动步骤放在最前 |
| 真实使用数据不足 | 邀请 3–5 位同学按验证样例试用，保留匿名反馈与使用次数，作为鼓励项而非必需项 |
| 比赛仓库被另一会话修改 | 已改用基于 `origin/2026-competition-ecosystem` 的独立 worktree 与 `qoder-reviewmate` 分支提交，不影响原 `work` 分支 |

## 提交前一句话介绍

> ReviewMate 用 seekdb 把课程笔记做成可回原文的混合检索，用 PowerContext 记住每次提问和薄弱点，让复习从「重新翻笔记」变成「接着上次继续」。
