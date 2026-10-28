import { performance } from 'node:perf_hooks';
import mysql from 'mysql2/promise';
import {
  SeekdbClient,
  Schema,
  FulltextIndexConfig,
  VectorIndexConfig,
} from 'seekdb';

import {
  SEEKDB_DATA_DIR,
  SEEKDB_PORT,
  SEEKDB_DATABASE,
  COLLECTION_PREFIX,
  REGISTRY_TABLE,
  ensureDataDir,
} from './config.js';
import { ensureSeekdb } from './seekdb-runtime.js';

/** @type {SeekdbClient | null} */
let client = null;
/** @type {Awaited<ReturnType<typeof ensureSeekdb>> | null} */
let runtime = null;
/** 初始化只跑一次 */
let initPromise = null;

const now = () => Date.now();

function collectionName(kbName) {
  // seekdb 的集合名只允许字母/数字/下划线，KB 名称里的 '-' 统一映射为 '_'
  return `${COLLECTION_PREFIX}${kbName.replace(/[^a-zA-Z0-9_]/g, '_')}`;
}

function kbNameFromCollection(name) {
  return name.startsWith(COLLECTION_PREFIX) ? name.slice(COLLECTION_PREFIX.length) : null;
}

/** 向量 + 中文全文（ik 分词）双索引；嵌入由浏览器端计算，所以 embeddingFunction 置空 */
function buildSchema(dimension) {
  return new Schema({
    fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension, distance: 'cosine' },
      embeddingFunction: null,
    }),
  });
}

async function ensureDatabase(host, port) {
  const conn = await mysql.createConnection({ host, port, user: 'root', password: '' });
  try {
    await conn.query(`CREATE DATABASE IF NOT EXISTS \`${SEEKDB_DATABASE}\``);
  } finally {
    await conn.end();
  }
}

export async function initDb() {
  if (client) return client;
  if (initPromise) return initPromise;

  initPromise = (async () => {
    ensureDataDir();
    runtime = await ensureSeekdb({ dataDir: SEEKDB_DATA_DIR, port: SEEKDB_PORT });
    await ensureDatabase(runtime.host, runtime.port);

    const c = new SeekdbClient({
      host: runtime.host,
      port: runtime.port,
      user: 'root',
      password: '',
      database: SEEKDB_DATABASE,
      queryTimeout: 120_000,
    });
    // 关系表：知识库注册信息（与向量集合在同一个库里）
    await c.execute(
      `CREATE TABLE IF NOT EXISTS ${REGISTRY_TABLE} (
         name VARCHAR(64) NOT NULL,
         label VARCHAR(191) NOT NULL,
         model VARCHAR(191) NOT NULL,
         dimension INT NOT NULL,
         created_at BIGINT NOT NULL,
         updated_at BIGINT NOT NULL,
         PRIMARY KEY (name)
       )`
    );
    client = c;
    return c;
  })();

  return initPromise;
}

export function getClient() {
  if (!client) throw new Error('seekdb 尚未初始化');
  return client;
}

export async function serverInfo() {
  const c = getClient();
  const rows = await c.execute('SELECT VERSION() AS version, DATABASE() AS db');
  return {
    mode: runtime?.mode ?? 'unknown',
    host: runtime?.host ?? '127.0.0.1',
    port: runtime?.port ?? SEEKDB_PORT,
    dataDir: SEEKDB_DATA_DIR,
    database: SEEKDB_DATABASE,
    version: rows?.[0]?.version ?? 'unknown',
  };
}

async function registryRows() {
  const c = getClient();
  return (await c.execute(`SELECT * FROM ${REGISTRY_TABLE} ORDER BY created_at ASC`)) ?? [];
}

export async function listKbs() {
  const c = getClient();
  const rows = await registryRows();
  const out = [];
  for (const row of rows) {
    const colName = collectionName(row.name);
    let chunks = 0;
    let exists = false;
    try {
      if (await c.hasCollection(colName)) {
        const col = await c.getCollection({ name: colName, embeddingFunction: null });
        chunks = await col.count();
        exists = true;
      }
    } catch {
      exists = false;
    }
    out.push({
      name: row.name,
      label: row.label,
      model: row.model,
      dimension: Number(row.dimension),
      chunks,
      collection: colName,
      exists,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at),
    });
  }
  return out;
}

export async function getKb(name) {
  const rows = await registryRows();
  const row = rows.find((r) => r.name === name);
  if (!row) return null;
  return {
    name: row.name,
    label: row.label,
    model: row.model,
    dimension: Number(row.dimension),
    collection: collectionName(row.name),
  };
}

export async function createKb({ name, label, model, dimension }) {
  const c = getClient();
  if (await getKb(name)) {
    const err = new Error(`知识库 ${name} 已存在`);
    err.status = 409;
    throw err;
  }
  const t0 = performance.now();
  const colName = collectionName(name);
  if (await c.hasCollection(colName)) {
    const err = new Error(`名称 ${name} 与已有集合冲突（${colName}），请换一个名称`);
    err.status = 409;
    throw err;
  }
  await c.createCollection({ name: colName, schema: buildSchema(dimension) });
  const ts = now();
  await c.execute(
    `INSERT INTO ${REGISTRY_TABLE} (name, label, model, dimension, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [name, label, model, dimension, ts, ts]
  );
  return { name, label, model, dimension, collection: colName, createMs: +(performance.now() - t0).toFixed(1) };
}

export async function deleteKb(name) {
  const c = getClient();
  const kb = await getKb(name);
  if (!kb) {
    const err = new Error(`知识库 ${name} 不存在`);
    err.status = 404;
    throw err;
  }
  if (await c.hasCollection(kb.collection)) {
    await c.deleteCollection(kb.collection);
  }
  await c.execute(`DELETE FROM ${REGISTRY_TABLE} WHERE name = ?`, [name]);
  return { ok: true };
}

async function requireCollection(name) {
  const kb = await getKb(name);
  if (!kb) {
    const err = new Error(`知识库 ${name} 不存在`);
    err.status = 404;
    throw err;
  }
  return { kb, collection: await getClient().getCollection({ name: kb.collection, embeddingFunction: null }) };
}

function checkVectors(embeddings, dimension) {
  if (!Array.isArray(embeddings) || embeddings.length === 0) {
    throw Object.assign(new Error('缺少 embeddings'), { status: 400 });
  }
  for (const vec of embeddings) {
    if (!Array.isArray(vec) || vec.length !== dimension) {
      throw Object.assign(
        new Error(`向量维度不匹配：期望 ${dimension}，实际 ${Array.isArray(vec) ? vec.length : typeof vec}`),
        { status: 400 }
      );
    }
  }
}

/**
 * 增量写入：分批 add，可选刷新索引，并做写后自检（用首条向量回查）。
 */
export async function addChunks(kbName, { chunks, embeddings, batchSize = 64, refresh = true, verify = true }) {
  const { kb, collection } = await requireCollection(kbName);
  if (!Array.isArray(chunks) || chunks.length === 0) {
    throw Object.assign(new Error('chunks 不能为空'), { status: 400 });
  }
  if (chunks.length !== embeddings.length) {
    throw Object.assign(new Error(`chunks(${chunks.length}) 与 embeddings(${embeddings.length}) 数量不一致`), { status: 400 });
  }
  checkVectors(embeddings, kb.dimension);

  const t0 = performance.now();
  const size = Math.max(1, Math.min(256, Number(batchSize) || 64));
  for (let i = 0; i < chunks.length; i += size) {
    const part = chunks.slice(i, i + size);
    await collection.add({
      ids: part.map((c) => c.id),
      documents: part.map((c) => c.text),
      metadatas: part.map((c) => c.metadata ?? {}),
      embeddings: embeddings.slice(i, i + size),
    });
  }
  const writeMs = performance.now() - t0;

  let refreshMs = 0;
  if (refresh) {
    const t1 = performance.now();
    await collection.refresh_index();
    refreshMs = performance.now() - t1;
  }

  let verification = null;
  if (refresh && verify) {
    const t2 = performance.now();
    const probeId = chunks[0].id;
    const probeText = String(chunks[0].text ?? '');
    const keyword = (probeText.match(/[\u4e00-\u9fa5A-Za-z0-9]{8,}/g) ?? [probeText.slice(0, 8)])[0]?.slice(0, 12) ?? '';
    const present = await collection.get({ ids: [probeId], include: ['documents'] });
    const writeOk = (present.ids ?? []).length > 0;
    let vectorHit = false;
    let keywordHit = false;
    try {
      const vecRes = await collection.query({
        queryEmbeddings: [embeddings[0]],
        nResults: Math.min(20, Math.max(5, chunks.length)),
        include: ['documents'],
      });
      vectorHit = (vecRes.ids?.[0] ?? []).includes(probeId);
    } catch {
      /* 近似索引可能未命中，下面用全文兜底判断 */
    }
    if (keyword) {
      try {
        const kwRes = await collection.hybridSearch({
          query: { whereDocument: { $contains: keyword }, nResults: 5 },
          nResults: 5,
          include: ['documents'],
        });
        keywordHit = (kwRes.ids?.[0] ?? []).includes(probeId);
      } catch {
        /* ignore */
      }
    }
    verification = {
      probeId,
      writeOk,
      vectorHit,
      keywordHit,
      hit: writeOk && (vectorHit || keywordHit),
      probeMs: +(performance.now() - t2).toFixed(1),
    };
  }

  await getClient().execute(`UPDATE ${REGISTRY_TABLE} SET updated_at = ? WHERE name = ?`, [now(), kbName]);

  return {
    inserted: chunks.length,
    total: await collection.count(),
    timings: {
      writeMs: +writeMs.toFixed(1),
      refreshMs: +refreshMs.toFixed(1),
    },
    verification,
  };
}

export async function refreshKb(kbName) {
  const { collection } = await requireCollection(kbName);
  const t0 = performance.now();
  await collection.refresh_index();
  return { refreshMs: +(performance.now() - t0).toFixed(1), total: await collection.count() };
}

/**
 * 检索全部在 seekdb 内完成：
 * - hybrid  : DBMS_HYBRID_SEARCH + RRF 融合（全文 + 向量）
 * - vector  : 纯向量 KNN
 * - keyword : 纯全文匹配
 */
export async function searchKb(kbName, { query, embedding, keyword, mode = 'hybrid', topK = 5, poolSize = 40, rankWindowSize, rankConstant }) {
  const { kb, collection } = await requireCollection(kbName);
  const q = String(query ?? '').trim();
  const kw = String(keyword ?? q).trim();
  const k = Math.max(1, Math.min(50, Number(topK) || 5));
  const include = ['documents', 'metadatas'];

  if (mode !== 'keyword') {
    if (!Array.isArray(embedding) || embedding.length !== kb.dimension) {
      throw Object.assign(new Error(`查询向量维度不匹配：期望 ${kb.dimension}`), { status: 400 });
    }
  }
  if (mode !== 'vector' && !kw) {
    throw Object.assign(new Error('全文检索关键词不能为空'), { status: 400 });
  }

  const t0 = performance.now();
  let result;
  if (mode === 'vector') {
    result = await collection.query({ queryEmbeddings: [embedding], nResults: k, include });
  } else if (mode === 'keyword') {
    result = await collection.hybridSearch({
      query: { whereDocument: { $contains: kw }, nResults: k },
      nResults: k,
      include,
    });
  } else {
    const rank = { rrf: {} };
    if (rankWindowSize) rank.rrf.rankWindowSize = Number(rankWindowSize);
    if (rankConstant) rank.rrf.rankConstant = Number(rankConstant);
    result = await collection.hybridSearch({
      query: { whereDocument: { $contains: kw }, nResults: Math.max(k, Number(poolSize) || 40) },
      knn: { queryEmbeddings: [embedding], nResults: Math.max(k, Number(poolSize) || 40) },
      rank,
      nResults: k,
      include,
    });
  }
  const searchMs = performance.now() - t0;

  const ids = result.ids?.[0] ?? [];
  const docs = result.documents?.[0] ?? [];
  const metas = result.metadatas?.[0] ?? [];
  const scores = result.distances?.[0] ?? [];

  return {
    mode,
    query: q,
    keyword: mode === 'vector' ? null : kw,
    hits: ids.map((id, i) => ({
      id,
      text: docs[i] ?? '',
      metadata: metas[i] ?? null,
      score: scores[i] ?? null,
      rank: i + 1,
    })),
    timings: { searchMs: +searchMs.toFixed(1) },
  };
}

export async function listDocs(kbName, limit = 50, offset = 0) {
  const { collection } = await requireCollection(kbName);
  const res = await collection.get({ limit, offset, include: ['documents', 'metadatas'] });
  const ids = res.ids ?? [];
  const docs = res.documents ?? [];
  const metas = res.metadatas ?? [];
  return ids.map((id, i) => ({ id, text: docs[i] ?? '', metadata: metas[i] ?? null }));
}

export async function deleteDocs(kbName, ids) {
  const { collection } = await requireCollection(kbName);
  if (!Array.isArray(ids) || ids.length === 0) {
    throw Object.assign(new Error('ids 不能为空'), { status: 400 });
  }
  await collection.delete({ ids });
  await collection.refresh_index();
  return { deleted: ids.length, total: await collection.count() };
}

export async function closeDb() {
  if (client) {
    await client.close();
    client = null;
  }
  await runtime?.stop?.();
  runtime = null;
}
