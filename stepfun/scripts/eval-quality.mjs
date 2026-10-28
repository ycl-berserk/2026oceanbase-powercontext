#!/usr/bin/env node
/**
 * 量化前后检索质量对比（不依赖浏览器）：
 * 用同一份语料 + 同一套分块 + 同一组查询，分别以 FP32 / INT8 权重做嵌入，
 * 在 Node 里用余弦相似度排序，计算 Recall@5 / nDCG@5 / MRR。
 *
 * 依赖 @huggingface/transformers（Node 侧走 onnxruntime-node）。
 *   node scripts/eval-quality.mjs [repoRoot]
 */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { pipeline, env } from '@huggingface/transformers';

// 离线/内网环境可以预先下载模型目录，并用 MODEL_DIR 指向它
if (process.env.MODEL_DIR) {
  env.allowRemoteModels = false;
  env.localModelPath = path.resolve(process.env.MODEL_DIR);
}

const repoRoot = path.resolve(process.argv[2] ?? '.');
const corpusDir = path.join(repoRoot, 'web/public/corpus');
const { chunkText } = await import(pathToFileURL(path.join(repoRoot, 'web/src/lib/chunker.ts')).href);

const DIM = 512;
const TOP_K = 5;
const evalSet = JSON.parse(fs.readFileSync(path.join(corpusDir, 'eval.json'), 'utf8'));

/* ---------- 语料 + 分块 ---------- */
const docs = evalSet.docs.map((d) => ({
  ...d,
  text: fs.readFileSync(path.join(corpusDir, d.file), 'utf8'),
}));
const chunks = docs.flatMap((d) => chunkText(d.id, d.title, d.file, d.text, { maxChars: 320, overlap: 64 }));

/* ---------- 指标 ---------- */
const dedupe = (ids) => [...new Set(ids.map((id) => id.split('#')[0]))];
function recallAt(retrieved, gold, k) {
  const rel = new Set(gold);
  const hit = new Set(retrieved.slice(0, k).filter((id) => rel.has(id)));
  return hit.size / gold.length;
}
function ndcgAt(retrieved, gold, k) {
  const rel = new Set(gold);
  let dcg = 0;
  retrieved.slice(0, k).forEach((id, i) => {
    if (rel.has(id)) dcg += 1 / Math.log2(i + 2);
  });
  let idcg = 0;
  for (let i = 0; i < Math.min(gold.length, k); i++) idcg += 1 / Math.log2(i + 2);
  return idcg ? dcg / idcg : 0;
}
function mrrOf(retrieved, gold) {
  const rel = new Set(gold);
  const idx = retrieved.findIndex((id) => rel.has(id));
  return idx < 0 ? 0 : 1 / (idx + 1);
}
const mean = (a) => a.reduce((x, y) => x + y, 0) / (a.length || 1);

function cosine(a, b) {
  let dot = 0;
  for (let i = 0; i < a.length; i++) dot += a[i] * b[i];
  return dot; // 已归一化
}

/* ---------- 运行 ---------- */
async function run(dtype) {
  const extractor = await pipeline('feature-extraction', 'Xenova/bge-small-zh-v1.5', { dtype, device: 'cpu' });
  const embed = async (texts, batch = 8) => {
    const out = [];
    const t0 = performance.now();
    for (let i = 0; i < texts.length; i += batch) {
      const res = await extractor(texts.slice(i, i + batch), { pooling: 'cls', normalize: true });
      out.push(...res.tolist());
    }
    return { vectors: out, ms: performance.now() - t0 };
  };

  const chunkTexts = chunks.map((c) => c.text);
  const docEmb = await embed(chunkTexts);
  const chars = chunkTexts.reduce((s, t) => s + t.length, 0);

  const recall = [];
  const ndcg = [];
  const mrr = [];
  const queryMs = [];
  for (const q of evalSet.queries) {
    const t0 = performance.now();
    const qv = (await embed([q.query], 1)).vectors[0];
    queryMs.push(performance.now() - t0);
    const scored = chunks
      .map((c, i) => ({ id: c.id, s: cosine(qv, docEmb.vectors[i]) }))
      .sort((a, b) => b.s - a.s);
    const retrieved = dedupe(scored.map((x) => x.id));
    recall.push(recallAt(retrieved, q.gold, TOP_K));
    ndcg.push(ndcgAt(retrieved, q.gold, TOP_K));
    mrr.push(mrrOf(retrieved, q.gold));
  }

  await extractor.dispose?.();

  return {
    dtype,
    chunks: chunks.length,
    dim: docEmb.vectors[0]?.length ?? 0,
    embedMs: Math.round(docEmb.ms),
    throughput: Math.round(chars / (docEmb.ms / 1000)),
    queryMsP50: Math.round(queryMs.sort((a, b) => a - b)[Math.floor(queryMs.length / 2)]),
    recall5: mean(recall),
    ndcg5: mean(ndcg),
    mrr: mean(mrr),
  };
}

const rows = [];
for (const dtype of ['fp32', 'fp16', 'q8']) {
  try {
    const r = await run(dtype);
    rows.push(r);
    console.log(`✓ ${dtype}`, JSON.stringify(r));
  } catch (err) {
    console.log(`✗ ${dtype} 失败：${err.message}`);
  }
}

const pct = (v) => `${(v * 100).toFixed(1)}%`;
console.log('\n| 精度 | 分块×维度 | 向量化 | 吞吐 | 查询 embedding P50 | Recall@5 | nDCG@5 | MRR |');
console.log('| --- | --- | --- | --- | --- | --- | --- | --- |');
for (const r of rows) {
  console.log(
    `| ${r.dtype === 'q8' ? 'INT8 (q8)' : r.dtype.toUpperCase()} | ${r.chunks}×${r.dim} | ${r.embedMs} ms | ${r.throughput} 字/s | ${r.queryMsP50} ms | ${pct(r.recall5)} | ${pct(r.ndcg5)} | ${r.mrr.toFixed(3)} |`
  );
}

const outFile = path.join(repoRoot, 'docs', 'quality-results.json');
fs.mkdirSync(path.dirname(outFile), { recursive: true });
fs.writeFileSync(
  outFile,
  JSON.stringify({ generatedAt: new Date().toISOString(), corpus: evalSet.name, topK: TOP_K, rows }, null, 2)
);
console.log(`\n结果已写入 ${outFile}`);

/* ---------- 批量大小对吞吐的影响 ---------- */
if (process.env.BATCH_SWEEP === '1') {
  console.log('\n### 批大小扫描（FP32，同样的 48 个分块）');
  console.log('\n| batch | 耗时 | 吞吐 |');
  console.log('| --- | --- | --- |');
  const chunkTexts = chunks.map((c) => c.text);
  const chars = chunkTexts.reduce((s, t) => s + t.length, 0);
  for (const batch of [1, 8, 32]) {
    const extractor = await pipeline('feature-extraction', 'Xenova/bge-small-zh-v1.5', { dtype: 'fp32', device: 'cpu' });
    // 预热，避免把图优化/首帧成本算进吞吐
    await extractor(['预热文本'], { pooling: 'cls', normalize: true });
    const t0 = performance.now();
    for (let i = 0; i < chunkTexts.length; i += batch) {
      await extractor(chunkTexts.slice(i, i + batch), { pooling: 'cls', normalize: true });
    }
    const ms = performance.now() - t0;
    console.log(`| ${batch} | ${Math.round(ms)} ms | ${Math.round(chars / (ms / 1000))} 字/s |`);
    await extractor.dispose?.();
  }
}
