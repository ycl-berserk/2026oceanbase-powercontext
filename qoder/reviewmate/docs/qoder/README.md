# Qoder 开发记录材料

本目录是提交用的 Qoder 对话截图。四张截图均取自 **Qoder CLI（qodercn / `qoderclicn` 1.1.78）** 的终端会话，工作目录经 WSL 访问 `~/qoder-reviewmate`。截图时已关闭 Inline Thinking，画面中不含模型思考过程；截图按窗口范围直接截取，未修改内容。

| 文件 | 对应阶段 | 画面内容 |
|---|---|---|
| `01-plan.png` | 交付计划 | `web/` 同步范围（3 个文件与行数）、待确认项、测试与发布顺序 |
| `02-retrieval.png` | seekdb 混合检索 | 一条 `UNION ALL` SQL、两路候选阈值过滤、RRF 计算表与页码引用 |
| `03-session-isolation.png` | PowerContext 记忆 | 两个 session 的 scope、同一问题 hits 2 vs 0、写入薄弱点后下一问命中 |
| `04-verify.png` | 验收与发布 | `make verify` 12 通过 / 0 失败、重启后 `/api/health`、Sites 发布遇到凭据缺失的原始记录 |

账号 UID 见 `docs/qoder-dev-log.md`：`aliyun-1585490604181694`。

几点说明：

- 画面中保留了本机路径、会话账号与窗口状态栏，属于 Qoder CLI 的正常界面，不包含真实密钥或凭据值。
- `04-verify.png` 原样保留了发布环节因终端凭据缺失而中断的记录，没有删改。
- `docs/qoder-dev-log.md` 的阶段划分与本目录截图一一对应。
