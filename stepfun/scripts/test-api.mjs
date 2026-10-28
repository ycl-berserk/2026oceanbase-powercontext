#!/usr/bin/env node
/**
 * 后端端到端测试（不打前端）：直接驱动 HTTP API，验证
 * 建库 → 写入 → 索引刷新 → 向量 / 全文 / 混合检索 → 增量写入 → 删除。
 *
 *   node scripts/test-api.mjs [baseUrl]
 */
const base = (process.env.API_BASE ?? process.argv[2] ?? 'http://127.0.0.1:8787').replace(/\/$/, '');
const KB = `test-${Date.now().toString(36)}`;

let pass = 0;
let fail = 0;
const results = [];

function check(name, cond, detail = '') {
  if (cond) {
    pass += 1;
    results.push(`  ✓ ${name}${detail ? ` · ${detail}` : ''}`);
  } else {
    fail += 1;
    results.push(`  ✗ ${name}${detail ? ` · ${detail}` : ''}`);
  }
}

async function req(method, url, body) {
  const res = await fetch(base + url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(`${method} ${url} → ${res.status} ${data?.error ?? text}`);
  return data;
}

const DIM = 32;
/** 用关键词构造可解释的向量：主题词维度为 1，其余为小噪声 */
function embed(text) {
  const v = new Array(DIM).fill(0);
  const topics = [
    ['数据库', 'seekdb', 'oceanbase', 'sql'],
    ['向量', '检索', 'hnsw', '相似'],
    ['浏览器', 'webgpu', 'wasm', '端侧'],
    ['量化', 'int8', 'fp16', '精度'],
  ];
  topics.forEach((words, i) => {
    if (words.some((w) => text.toLowerCase().includes(w))) v[i] = 1;
  });
  for (let i = 4; i < DIM; i++) v[i] = (text.charCodeAt(i % text.length) % 7) / 100;
  return v;
}

const docs = [
  ['d1', 'seekdb 是 AI 原生检索数据库，支持向量与全文混合检索'],
  ['d2', 'OceanBase 是分布式数据库，seekdb 可以看作它的轻量形态'],
  ['d3', 'HNSW 是常用的向量索引，用于近似最近邻检索'],
  ['d4', '浏览器端可以用 WebGPU 或 WASM 运行 embedding 模型'],
  ['d5', 'INT8 量化把 float32 权重压到 8 位，显著减小模型体积'],
  ['d6', '端侧推理要求模型下载到本地，计算不经过云端'],
];

async function main() {
  console.log(`\n== 后端 API 测试 @ ${base} ==\n`);

  const health = await req('GET', '/api/health');
  check('health', health.ok === true, `${health.mode} · ${health.version}`);

  const created = await req('POST', '/api/kbs', { name: KB, label: '测试库', model: 'test-model', dimension: DIM });
  check('创建知识库', created.name === KB, `createMs=${created.createMs}`);

  const chunks = docs.map(([id, text]) => ({ id, text, metadata: { docTitle: id, chunkIndex: 0, chars: text.length } }));
  const write = await req('POST', `/api/kbs/${KB}/documents`, {
    chunks,
    embeddings: docs.map(([, text]) => embed(text)),
    refresh: true,
    verify: true,
  });
  check('写入 6 条', write.inserted === 6 && write.total === 6, `count=${write.total}`);
  check('写后自检命中', write.verification?.hit === true, `probe=${write.verification?.probeId}`);
  check('索引刷新成功', typeof write.timings.refreshMs === 'number', `refreshMs=${write.timings.refreshMs}`);

  const vector = await req('POST', `/api/kbs/${KB}/search`, {
    query: '向量检索',
    embedding: embed('向量 检索'),
    mode: 'vector',
    topK: 3,
  });
  check('向量检索有结果', vector.hits.length > 0, `${vector.hits.map((h) => h.id).join(',')} · ${vector.timings.searchMs}ms`);
  check('向量检索最相关为 d3', vector.hits[0]?.id === 'd3', `top=${vector.hits[0]?.id}`);

  const keyword = await req('POST', `/api/kbs/${KB}/search`, { query: '量化', mode: 'keyword', topK: 3 });
  check('全文检索命中 d5', keyword.hits.some((h) => h.id === 'd5'), `${keyword.hits.map((h) => h.id).join(',')}`);

  const hybrid = await req('POST', `/api/kbs/${KB}/search`, {
    query: '浏览器端跑 embedding 用什么后端',
    embedding: embed('浏览器 webgpu wasm 端侧'),
    mode: 'hybrid',
    topK: 3,
  });
  check('混合检索有结果', hybrid.hits.length > 0, `${hybrid.hits.map((h) => `${h.id}:${h.score}`).join(', ')}`);
  check('混合检索命中 d4 或 d6', hybrid.hits.some((h) => ['d4', 'd6'].includes(h.id)), `top=${hybrid.hits[0]?.id}`);

  // 增量写入
  const extra = ['d7', 'seekdb 的 refresh_index 让新写入的向量立即可检索'];
  const inc = await req('POST', `/api/kbs/${KB}/documents`, {
    chunks: [{ id: extra[0], text: extra[1], metadata: { docTitle: 'd7', chunkIndex: 0 } }],
    embeddings: [embed(extra[1])],
    refresh: true,
  });
  check('增量写入', inc.inserted === 1 && inc.total === 7, `total=${inc.total}`);

  const afterInc = await req('POST', `/api/kbs/${KB}/search`, {
    query: 'refresh_index',
    embedding: embed('向量 检索'),
    mode: 'vector',
    topK: 3,
  });
  check('新增文档刷新后可检索', afterInc.hits.some((h) => h.id === 'd7'), `${afterInc.hits.map((h) => h.id).join(',')}`);

  const refresh = await req('POST', `/api/kbs/${KB}/refresh`);
  check('手动刷新索引', refresh.total === 7, `refreshMs=${refresh.refreshMs}`);

  const list = await req('GET', `/api/kbs/${KB}/documents?limit=10`);
  check('分页读取原文', list.docs.length === 7 && list.docs.every((d) => d.text.length > 0));

  // 重复导入同一批数据：应当是覆盖（upsert），而不是主键冲突
  const repeat = await req('POST', `/api/kbs/${KB}/documents`, {
    chunks,
    embeddings: docs.map(([, text]) => embed(text)),
    refresh: true,
  });
  check('重复导入可覆盖', repeat.inserted === 6 && repeat.total === 7, `total=${repeat.total}`);

  const del = await req('DELETE', `/api/kbs/${KB}/documents`, { ids: ['d1'] });
  check('删除文档', del.deleted === 1 && del.total === 6, `total=${del.total}`);

  const kbs = await req('GET', '/api/kbs');
  check('知识库列表包含测试库', kbs.kbs.some((k) => k.name === KB));

  await req('DELETE', `/api/kbs/${KB}`);
  const after = await req('GET', '/api/kbs');
  check('删除知识库', !after.kbs.some((k) => k.name === KB));

  console.log(results.join('\n'));
  console.log(`\n== ${pass} passed, ${fail} failed ==\n`);
  process.exit(fail === 0 ? 0 : 1);
}

main().catch((err) => {
  console.error('\n测试异常：', err.message);
  process.exit(1);
});
