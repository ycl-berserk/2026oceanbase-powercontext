import fs from 'node:fs';
import path from 'node:path';
import express from 'express';
import cors from 'cors';

import { PORT, WEB_DIST } from './config.js';
import {
  initDb,
  serverInfo,
  listKbs,
  createKb,
  deleteKb,
  addChunks,
  refreshKb,
  searchKb,
  listDocs,
  deleteDocs,
  closeDb,
} from './db.js';

const app = express();
app.use(cors());
app.use(express.json({ limit: '64mb' }));

const wrap = (fn) => (req, res, next) => Promise.resolve(fn(req, res, next)).catch(next);

const KB_NAME_RE = /^[a-z0-9][a-z0-9_-]{1,39}$/;

function assertKbName(name) {
  if (!KB_NAME_RE.test(name)) {
    throw Object.assign(new Error('知识库名称只能是小写字母/数字/-/_，长度 2-40'), { status: 400 });
  }
}

app.get('/api/health', wrap(async (_req, res) => {
  res.json({ ok: true, uptime: process.uptime(), ...(await serverInfo()) });
}));

app.get('/api/kbs', wrap(async (_req, res) => {
  res.json({ kbs: await listKbs() });
}));

app.post('/api/kbs', wrap(async (req, res) => {
  const { name, label, model, dimension } = req.body ?? {};
  assertKbName(name ?? '');
  const dim = Number(dimension);
  if (!Number.isInteger(dim) || dim < 8 || dim > 4096) {
    throw Object.assign(new Error('dimension 必须是 8-4096 的整数'), { status: 400 });
  }
  const kb = await createKb({
    name,
    label: String(label ?? name).slice(0, 190),
    model: String(model ?? 'unknown').slice(0, 190),
    dimension: dim,
  });
  res.status(201).json(kb);
}));

app.delete('/api/kbs/:name', wrap(async (req, res) => {
  res.json(await deleteKb(req.params.name));
}));

app.post('/api/kbs/:name/documents', wrap(async (req, res) => {
  const { chunks, embeddings, batchSize, refresh, verify } = req.body ?? {};
  res.json(await addChunks(req.params.name, { chunks, embeddings, batchSize, refresh, verify }));
}));

app.get('/api/kbs/:name/documents', wrap(async (req, res) => {
  const limit = Math.min(500, Number(req.query.limit) || 50);
  const offset = Math.max(0, Number(req.query.offset) || 0);
  res.json({ docs: await listDocs(req.params.name, limit, offset) });
}));

app.delete('/api/kbs/:name/documents', wrap(async (req, res) => {
  res.json(await deleteDocs(req.params.name, req.body?.ids));
}));

app.post('/api/kbs/:name/refresh', wrap(async (req, res) => {
  res.json(await refreshKb(req.params.name));
}));

app.post('/api/kbs/:name/search', wrap(async (req, res) => {
  const t0 = performance.now();
  const result = await searchKb(req.params.name, req.body ?? {});
  result.timings.totalMs = +(performance.now() - t0).toFixed(1);
  res.json(result);
}));

// 生产模式：直接托管构建后的前端
if (fs.existsSync(path.join(WEB_DIST, 'index.html'))) {
  app.use(express.static(WEB_DIST));
  app.get(/^(?!\/api\/).*/, (_req, res) => res.sendFile(path.join(WEB_DIST, 'index.html')));
} else {
  console.warn('[web] 未找到 web/dist，当前仅提供 API。请先执行 npm run build，或使用 npm run dev。');
}

app.use((err, _req, res, _next) => {
  const status = err.status ?? 500;
  if (status >= 500) console.error(err);
  res.status(status).json({ error: err.message ?? String(err) });
});

let server;
try {
  await initDb();
  const info = await serverInfo();
  server = app.listen(PORT, () => {
    console.log(`[seekdb] ${info.mode} · ${info.host}:${info.port} · ${info.version}`);
    console.log(`[seekdb] data dir: ${info.dataDir}`);
    console.log(`[api] http://localhost:${PORT}`);
  });
} catch (err) {
  console.error('[fatal] seekdb 初始化失败：', err);
  process.exit(1);
}

const shutdown = async () => {
  server?.close();
  await closeDb().catch(() => {});
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
