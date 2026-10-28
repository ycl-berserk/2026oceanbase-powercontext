#!/usr/bin/env node
/**
 * seekdb 连通性 / 能力探针。
 *
 *   node scripts/probe-seekdb.mjs                       # 嵌入式（@seekdb/js-bindings）
 *   node scripts/probe-seekdb.mjs --remote 127.0.0.1:2881  # 连接已有 server（MySQL 协议）
 *
 * 验证：建库 → 建集合（ik 全文 + HNSW 向量）→ 写入 → refresh_index → 向量检索 / RRF 混合检索。
 */
import { performance } from 'node:perf_hooks';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const remoteArg = process.argv.indexOf('--remote');
const remote = remoteArg > 0 ? process.argv[remoteArg + 1] : process.env.SEEKDB_HOST ? `${process.env.SEEKDB_HOST}:${process.env.SEEKDB_PORT ?? 2881}` : null;
const mode = remote ? 'remote' : 'embedded';
const DIM = 8;
const vec = (seed) => Array.from({ length: DIM }, (_, i) => Math.sin(seed * (i + 1)));
const log = (...args) => console.log(`[${(performance.now() / 1000).toFixed(2)}s]`, ...args);
const step = async (label, fn) => {
  const t0 = performance.now();
  const result = await fn();
  log(`${label}: ${(performance.now() - t0).toFixed(0)} ms`);
  return result;
};

const dataDir = path.resolve(process.env.PROBE_DATA_DIR ?? './probe-data');

async function main() {
  const { SeekdbClient, Schema, FulltextIndexConfig, VectorIndexConfig } = await import('seekdb');

  let client;
  let stop = async () => {};
  if (mode === 'embedded') {
    fs.mkdirSync(dataDir, { recursive: true });
    client = await step('open embedded', async () => {
      const { SeekdbAdminClient } = await import('seekdb');
      const admin = new SeekdbAdminClient({ path: dataDir });
      const dbs = (await admin.listDatabases()).map((d) => (typeof d === 'string' ? d : d?.name));
      if (!dbs.includes('probe')) await admin.createDatabase('probe');
      await admin.close();
      return new SeekdbClient({ path: dataDir, database: 'probe', queryTimeout: 120_000 });
    });
  } else {
    const [host, portText] = (remote ?? '127.0.0.1:2881').split(':');
    const port = Number(portText ?? 2881);
    const mysql = (await import('mysql2/promise')).default;
    const conn = await step('connect (mysql protocol)', () =>
      mysql.createConnection({ host, port, user: 'root', password: '', database: 'test' })
    );
    const [rows] = await conn.query('SELECT VERSION() AS v');
    log('server version:', rows[0].v);
    await conn.query('CREATE DATABASE IF NOT EXISTS probe');
    await conn.end();
    client = new SeekdbClient({ host, port, user: 'root', password: '', database: 'probe', queryTimeout: 120_000 });
  }

  try {
    const schema = new Schema({
      fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
      vectorIndex: new VectorIndexConfig({ hnsw: { dimension: DIM, distance: 'cosine' }, embeddingFunction: null }),
    });
    const name = `probe_${Date.now().toString(36)}`;
    const col = await step('createCollection (ik + hnsw)', () => client.createCollection({ name, schema }));

    await step('add 3 docs', () =>
      col.add({
        ids: ['d1', 'd2', 'd3'],
        documents: ['OceanBase 是分布式数据库，支持向量检索', 'seekdb 使用 HNSW 索引做近似最近邻搜索', '浏览器端 embedding 推理可以用 WebGPU 或 WASM'],
        metadatas: [{ docTitle: 'a' }, { docTitle: 'b' }, { docTitle: 'c' }],
        embeddings: [vec(1), vec(2), vec(3)],
      })
    );

    await step('refresh_index', async () => {
      try {
        await col.refresh_index();
        log('  refresh_index OK');
      } catch (err) {
        log('  refresh_index 失败（继续验证检索）：', err?.message ?? err);
      }
    });
    log('count:', await col.count());

    const knn = await step('KNN query', () =>
      col.query({ queryEmbeddings: [vec(1)], nResults: 3, include: ['documents', 'distances'] })
    );
    log('KNN ids:', knn.ids[0].join(', '), 'scores:', (knn.distances?.[0] ?? []).map((d) => Number(d).toFixed(4)).join(', '));

    const hybrid = await step('hybridSearch (RRF)', () =>
      col.hybridSearch({
        query: { whereDocument: { $contains: '向量检索' }, nResults: 10 },
        knn: { queryEmbeddings: [vec(1)], nResults: 10 },
        rank: { rrf: { rankConstant: 60 } },
        nResults: 3,
        include: ['documents', 'distances'],
      })
    );
    log('hybrid ids:', hybrid.ids[0].join(', '), 'scores:', (hybrid.distances?.[0] ?? []).map((d) => Number(d).toFixed(6)).join(', '));

    const keyword = await step('fulltext only', () =>
      col.hybridSearch({ query: { whereDocument: { $contains: 'HNSW' } }, nResults: 3, include: ['documents'] })
    );
    log('fulltext ids:', keyword.ids[0].join(', '));

    await client.deleteCollection?.(name).catch(() => {});
    await client.close();
    log('OK · 数据层全部能力可用（模式：' + mode + '）');
  } finally {
    await stop().catch(() => {});
  }
}

main().catch((err) => {
  console.error('PROBE FAILED:', err?.message ?? err);
  process.exit(1);
});
