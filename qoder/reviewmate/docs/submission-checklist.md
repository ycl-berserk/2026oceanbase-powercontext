# 提交清单

提交入口：OceanBase 大赛测试平台 → Qoder 赛题。以下 `<...>` 为待填写占位符。

## 一、提交材料

| # | 材料 | 当前状态 | 提交值 / 位置 |
|---|---|---|---|
| 1 | 项目网站网址 | 已发布，公开访问已验证 | <https://reviewmate-5967u15pefr.qoder.zone> |
| 2 | 代码仓库 | 已推送 | <https://github.com/ycl-berserk/2026oceanbase-powercontext>（私有；分支 `qoder-reviewmate`，目录 `qoder/reviewmate/`，项目内容 commit `d0f8ed2f`；评审需授权） |
| 3 | 运行说明 | 已完成 | `README.md`「快速开始」 |
| 4 | 验证样例 | 已完成并跑通 | `docs/verification.md`、`scripts/verify.py`、`data/verification/report.json` |
| 5 | Qoder 开发记录 | 文字已完成，截图待补 | `docs/qoder-dev-log.md`、`docs/qoder/` |
| 6 | Qoder 账号 UID | 已填写 | `aliyun-1585490604181694` |
| 7 | 使用效果材料（鼓励） | 可选 | 试用人数、次数、匿名反馈；附来源截图 |
| 8 | 演示视频（可选） | 待定 | 1–2 分钟页面流程录屏 |

## 二、Qoder Sites 发布

- [x] 已通过 Qoder CLI 创建站点（无需桌面端）。
- [x] 可见范围已设为「任何人都可访问」。
- [x] 已发布：<https://reviewmate-5967u15pefr.qoder.zone>
- [x] 无痕方式复核：首页 200、样式与 4 张图片正常、无登录墙、无横向溢出。
- [ ] 代码仓库地址确定后，更新站点内 `CODE_REPO_URL` 占位并重新发布。
- [ ] 评审结束前不暂停或删除站点。

站点信息：

| 字段 | 值 |
|---|---|
| 公网地址 | `https://reviewmate-5967u15pefr.qoder.zone` |
| Site ID | `01a177da-3a47-76a5-b329-4e4001edd05e` |
| Project ID | `01a177da-3a44-7a5a-bd29-9b309d86f16d` |
| 发布 action | `4bc0ca6a-2552-466d-a410-d66a24168e74` |
| 公开访问截图 | `data/screenshots/site-public.png` |

## 三、代码仓库

1. 提交基于 `origin/2026-competition-ecosystem` 的独立分支 `qoder-reviewmate`，项目资产位于 `qoder/reviewmate/`；不改动基于 `2026-competition` 的 `work` 分支。
2. 使用独立 worktree `~/2026oceanbase-powercontext-qoder` 准备与提交，避免覆盖原分支的并行修改。
3. 推送前检查：

```bash
git status
git diff --cached
git ls-files | grep -Ei '\.env$|secret|credential|\.key$|\.pem$'
```

4. 确认以下目录未提交：`.venv/`、`data/seekdb/`、`data/powercontext/`、`data/chrome-profile/`、`data/imports/`、日志与 `.env`。
5. 项目 README 已写明路径（`qoder/reviewmate/`）、启动命令与提交分支/commit。
6. 私有仓库需向评审账号开放访问（或提交带 token 的读取地址，token 不写入站点与文档）。

## 四、Qoder 开发记录

- [ ] 从 Qoder 会话导出 3–5 张截图或 1–2 分钟录屏，覆盖：需求拆解、seekdb/PowerContext 验证、编码、调试、验收。
- [ ] 截图内可见 Qoder 界面与项目文件，避免只截结果。
- [x] Qoder 账号 UID 已填写：`aliyun-1585490604181694`。
- [ ] 确保截图中的密钥、个人信息已打码。
- [ ] 将文件放入 `docs/qoder/` 并在开发记录中引用文件名。

## 五、安全与合规

- [ ] `.env.example` 只含占位值；没有真实 API Key、密码、Token、数据库凭据。
- [ ] 样例数据为自编笔记，CC BY 4.0；第三方开源代码与模型已注明来源与许可。
- [ ] 截图、日志、反馈中隐去姓名、学号、联系方式。
- [ ] 项目网站与仓库均不含 `.env`、本地数据库、Chrome profile。

## 六、最终复核

- [ ] `make test` 通过。
- [ ] `make lint` 通过。
- [ ] `make verify` 12/12 通过，报告已更新。
- [ ] 从零按 README 启动一遍：PowerContext → ingest → serve。
- [ ] 无痕窗口打开站点，检查图片、链接、代码仓库入口。
- [ ] 提交平台填写：站点网址、仓库地址、Qoder UID，并上传其余材料。
- [ ] 记录提交时间与版本 commit，保留一份本地材料快照。

## 七、提交信息模板

```
项目名称：温故 ReviewMate
一句话：seekdb 混合检索找到原文，PowerContext 记住薄弱点，让课程复习接着上次继续。
项目网站：https://reviewmate-5967u15pefr.qoder.zone
代码仓库：https://github.com/ycl-berserk/2026oceanbase-powercontext（分支 qoder-reviewmate，目录 qoder/reviewmate/，项目内容 commit d0f8ed2f）
Qoder UID：aliyun-1585490604181694
验证入口：make verify（12 项自动检查）
技术分工：seekdb = 全文 + 向量混合检索 / 检索日志 / 会话映射；PowerContext = 学习进度、薄弱点与复习计划记忆
```
