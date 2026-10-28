#!/usr/bin/env node
/**
 * seekdb 数据层基准：写入 / 索引刷新 / 三类检索延迟。
 * 只测数据层（向量由脚本合成），用于技术说明里的「seekdb 检索延迟」一列。
 *
 *   bash scripts/run-with-server.sh node scripts/bench-db.mjs
 */
const base = (process.env.API_BASE ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const DIM = Number(process.env.BENCH_DIM ?? 512);
const CHUNKS = Number(process.env.BENCH_CHUNKS ?? 600);
const QUERIES = Number(process.env.BENCH_QUERIES ?? 30);
const SUFFIX = Date.now().toString(36);

async function req(method, url, body) {
  const res = await fetch(base + url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${text}`);
  return text ? JSON.parse(text) : null;
}

const TOPICS = ['向量索引', '全文检索', '量化推理', '浏览器运行', '数据库架构', '索引刷新', '分块策略', '评测指标'];
const makeText = (i) =>
  `${TOPICS[i % TOPICS.length]} 说明 ${i}：seekdb 在同一引擎内同时维护向量索引与全文索引，查询时由数据库完成召回与融合，客户端只负责提交查询向量与关键词。`;

function makeVector(i) {
  const v = new Array(DIM).fill(0);
  const topic = i % TOPICS.length;
  v[topic] = 1;
  v[(topic + 3) % TOPICS.length] = 0.5;
  let seed = i * 9301 + 49297;
  for (let d = 8; d < DIM; d++) {
    seed = (seed * 9301 + 49297) % 233280;
    v[d] = (seed / 233280 - 0.5) * 0.1;
  }
  return v;
}

function pct(arr, p) {
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
}
const round = (v) => Math.round(v * 10) / 10;

const chunks = Array.from({ length: CHUNKS }, (_, i) => ({
  id: `c${i}#000`,
  text: makeText(i),
  metadata: { docTitle: `doc-${i}`, chunkIndex: 0 },
}));
const vectors = Array.from({ length: CHUNKS }, (_, i) => makeVector(i));
const BATCH = 100;

/* ---------- A：每批写完都刷新（逐批刷新） ---------- */
const kbA = `bench-a-${SUFFIX}`;
await req('POST', '/api/kbs', { name: kbA, label: '逐批刷新', model: 'synthetic', dimension: DIM });
const refreshA = [];
for (let i = 0; i < CHUNKS; i += BATCH) {
  const res = await req('POST', `/api/kbs/${kbA}/documents`, {
    chunks: chunks.slice(i, i + BATCH),
    embeddings: vectors.slice(i, i + BATCH),
    refresh: true,
  });
  refreshA.push(res.timings.refreshMs);
}
const refreshATotal = refreshA.reduce((a, b) => a + b, 0);
await req('DELETE', `/api/kbs/${kbA}`);

/* ---------- B：全部写完后只刷新一次（批量合并刷新） ---------- */
const kb = `bench-b-${SUFFIX}`;
await req('POST', '/api/kbs', { name: kb, label: '基准', model: 'synthetic', dimension: DIM });
const writeTimes = [];
for (let i = 0; i < CHUNKS; i += BATCH) {
  const res = await req('POST', `/api/kbs/${kb}/documents`, {
    chunks: chunks.slice(i, i + BATCH),
    embeddings: vectors.slice(i, i + BATCH),
    refresh: false,
  });
  writeTimes.push(res.timings.writeMs);
}
const tRefresh = Date.now();
await req('POST', `/api/kbs/${kb}/refresh`);
const refreshOnceMs = Date.now() - tRefresh;

/* ---------- 检索延迟 ---------- */
const modes = ['vector', 'keyword', 'hybrid'];
const lat = { vector: [], keyword: [], hybrid: [] };
for (let q = 0; q < QUERIES; q++) {
  const idx = q % CHUNKS;
  const mode = modes[q % modes.length];
  const res = await req('POST', `/api/kbs/${kb}/search`, {
    query: makeText(idx).slice(0, 40),
    embedding: makeVector(idx),
    mode,
    topK: 5,
  });
  lat[mode].push(res.timings.searchMs);
}

/* ---------- 增量写入 + 刷新 + 可见性 ---------- */
const inc = await req('POST', `/api/kbs/${kb}/documents`, {
  chunks: [{ id: 'fresh#000', text: '新导入的一段独特内容，用于验证刷新后是否可见', metadata: { docTitle: 'fresh', chunkIndex: 0 } }],
  embeddings: [makeVector(3)],
  refresh: true,
  verify: true,
});

const writeTotal = writeTimes.reduce((a, b) => a + b, 0);
console.log(`\n## seekdb 数据层基准\n`);
console.log(`- 规模：${CHUNKS} 个分块 × ${DIM} 维（每批 ${BATCH}，共 ${Math.ceil(CHUNKS / BATCH)} 批）`);
console.log(`- 写入：总计 ${Math.round(writeTotal)} ms，单批 P50 ${round(pct(writeTimes, 50))} ms，写入吞吐 ${Math.round((CHUNKS * DIM) / (writeTotal / 1000) / 1000)}k dims/s`);
console.log(`- 刷新（逐批）：${Math.round(refreshATotal)} ms / ${refreshA.length} 次，P50 ${round(pct(refreshA, 50))} ms`);
console.log(`- 刷新（合并一次）：${refreshOnceMs} ms —— 相比逐批刷新节省 ${Math.round((1 - refreshOnceMs / refreshATotal) * 100)}%`);
for (const m of modes) {
  console.log(`- ${m} 检索：P50 ${round(pct(lat[m], 50))} ms / P95 ${round(pct(lat[m], 95))} ms（${lat[m].length} 次）`);
}
console.log(`- 增量 1 条 + 刷新 + 自检：writeOk=${inc.verification?.writeOk} vectorHit=${inc.verification?.vectorHit} keywordHit=${inc.verification?.keywordHit}，总数 ${inc.total}`);

console.log(`\n| 指标 | 数值 |`);
console.log(`| --- | --- |`);
console.log(`| 分块数 / 维度 | ${CHUNKS} / ${DIM} |`);
console.log(`| 写入吞吐 | ${Math.round((CHUNKS * DIM) / (writeTotal / 1000) / 1000)}k dims/s |`);
console.log(`| 索引刷新（合并） | ${refreshOnceMs} ms |`);
console.log(`| 索引刷新（逐批） | ${Math.round(refreshATotal)} ms |`);
console.log(`| 向量检索 | P50 ${round(pct(lat.vector, 50))} ms / P95 ${round(pct(lat.vector, 95))} ms |`);
console.log(`| 全文检索 | P50 ${round(pct(lat.keyword, 50))} ms / P95 ${round(pct(lat.keyword, 95))} ms |`);
console.log(`| 混合检索（RRF） | P50 ${round(pct(lat.hybrid, 50))} ms / P95 ${round(pct(lat.hybrid, 95))} ms |`);

await req('DELETE', `/api/kbs/${kb}`);
