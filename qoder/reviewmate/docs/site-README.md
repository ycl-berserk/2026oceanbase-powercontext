# 项目展示站

纯静态站点，入口为 `index.html`，无构建步骤。

本地预览：

```bash
cd site
python3 -m http.server 8091 --bind 127.0.0.1
# 打开 http://127.0.0.1:8091/
```

发布：

1. 在 Qoder 中通过 Sites 打开本目录并创建站点。
2. 可见范围设为「任何人都可访问」。
3. 发布后把公开网址填回根目录 `README.md` 与 `docs/submission-checklist.md`。

发布前需要替换的占位符：

- `index.html` 中的 `CODE_REPO_URL`（当前链接指向页内占位）。
- 若截图更新，用 `data/screenshots/` 中的最新文件覆盖 `assets/`。

页面中的数字与验收结果来自由 `scripts/verify.py` 生成的真实运行记录。
