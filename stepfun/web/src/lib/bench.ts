import { api } from './api';
import type { ChunkOptions } from './chunker';
import { chunkText } from './chunker';
import type { Embedder } from './embedder';
import { dedupeDocIds, mean, median, mrr, ndcgAtK, recallAtK } from './metrics';
import type { Backend, BenchQueryResult, BenchRun, EvalSet, Precision } from './types';

export interface BenchArgs {
  embedder: Embedder;
  evalSet: EvalSet;
  modelId: string;
  precision: Precision;
  backend: Backend;
  dimension: number;
  modelBytes: number | null;
  loadMs: number;
  chunk: ChunkOptions;
  batchSize: number;
  topK: number;
  onProgress: (pct: number, message: string) => void;
}

const sleep = (ms = 0) => new Promise((r) => setTimeout(r, ms));

/**
 * 用固定评测集跑完整链路：导入 → 端侧向量化 → 写入 seekdb → 刷新 → 检索，
 * 产出与题目要求一致的指标（Recall@K / nDCG@K）与分阶段耗时。
 */
export async function runBenchmark(args: BenchArgs): Promise<BenchRun> {
  const { embedder, evalSet, modelId, precision, backend, dimension, modelBytes, loadMs, chunk, batchSize, topK, onProgress } = args;

  onProgress(2, '读取评测语料…');
  const docs: { id: string; title: string; text: string; file: string }[] = [];
  for (const doc of evalSet.docs) {
    const res = await fetch(`/corpus/${doc.file}`);
    if (!res.ok) throw new Error(`读取 ${doc.file} 失败（HTTP ${res.status}）`);
    docs.push({ id: doc.id, title: doc.title, text: await res.text(), file: doc.file });
  }
  const corpusChars = docs.reduce((sum, d) => sum + d.text.length, 0);

  onProgress(6, '切分文档…');
  const chunks = docs.flatMap((doc) => chunkText(doc.id, doc.title, doc.file, doc.text, chunk));

  const kbName = `bench-${precision}-${backend}`.slice(0, 40);
  try {
    await api.deleteKb(kbName);
  } catch {
    /* 首次运行时不存在 */
  }
  await api.createKb({ name: kbName, label: `评测 ${precision}/${backend}`, model: modelId, dimension });

  onProgress(8, `端侧向量化 ${chunks.length} 个分块…`);
  const embed = await embedder.embed(
    chunks.map((c) => c.text),
    batchSize,
    (done, total) => onProgress(8 + Math.round((done / total) * 42), `端侧向量化 ${done}/${total} 个分块…`)
  );

  onProgress(52, '写入 seekdb 并刷新索引…');
  const writeStarted = performance.now();
  const written = await api.addDocuments(kbName, {
    chunks: chunks.map((c) => ({ id: c.id, text: c.text, metadata: c.metadata as unknown as Record<string, unknown> })),
    embeddings: embed.vectors,
    batchSize: 64,
    refresh: true,
    verify: true,
  });
  const writeRoundTripMs = performance.now() - writeStarted;

  const results: BenchQueryResult[] = [];
  let firstQueryMs = 0;

  for (let i = 0; i < evalSet.queries.length; i++) {
    const q = evalSet.queries[i];
    onProgress(60 + Math.round(((i + 1) / evalSet.queries.length) * 38), `检索评测 ${i + 1}/${evalSet.queries.length}…`);

    const t0 = performance.now();
    const qEmb = await embedder.embed([q.query], 1);
    const queryEmbedMs = performance.now() - t0;

    const res = await api.search(kbName, {
      query: q.query,
      embedding: qEmb.vectors[0],
      keyword: q.query,
      mode: 'hybrid',
      topK,
      poolSize: 40,
    });
    const e2eMs = performance.now() - t0;
    if (i === 0) firstQueryMs = e2eMs;

    const retrieval = dedupeDocIds(res.hits.map((h) => h.id)).slice(0, topK);
    const ranked = { retrieve: retrieval, gold: q.gold, k: topK };
    results.push({
      query: q.query,
      gold: q.gold,
      hits: retrieval,
      recall: recallAtK(ranked),
      ndcg: ndcgAtK(ranked),
      mrr: mrr(ranked),
      queryEmbedMs: +queryEmbedMs.toFixed(1),
      searchMs: res.timings.searchMs,
      e2eMs: +e2eMs.toFixed(1),
    });
    await sleep();
  }

  onProgress(100, '评测完成');

  return {
    id: `run_${Date.now().toString(36)}`,
    createdAt: Date.now(),
    model: modelId,
    precision,
    backend,
    dimension,
    modelBytes,
    docs: docs.length,
    chunks: chunks.length,
    corpusChars,
    loadMs: +loadMs.toFixed(0),
    firstQueryMs: +firstQueryMs.toFixed(1),
    embedMs: +embed.totalMs.toFixed(0),
    embedThroughputCps: +embed.throughputCps.toFixed(1),
    writeMs: written.timings.writeMs,
    refreshMs: written.timings.refreshMs,
    writeRoundTripMs: +writeRoundTripMs.toFixed(1),
    searchMsP50: +median(results.map((r) => r.searchMs)).toFixed(1),
    queryEmbedMsP50: +median(results.map((r) => r.queryEmbedMs)).toFixed(1),
    e2eMsP50: +median(results.map((r) => r.e2eMs)).toFixed(1),
    recall5: mean(results.map((r) => r.recall)),
    ndcg5: mean(results.map((r) => r.ndcg)),
    mrr: mean(results.map((r) => r.mrr)),
    queries: results,
  };
}

export function benchToMarkdown(run: BenchRun): string {
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const mb = (v: number | null) => (v ? `${(v / 1024 / 1024).toFixed(1)} MB` : '—');
  return [
    `### ${run.precision.toUpperCase()} + ${run.backend.toUpperCase()}`,
    '',
    `- 模型：\`${run.model}\`（${run.dimension} 维），精度 ${run.precision}`,
    `- 体积：${mb(run.modelBytes)}；加载 ${run.loadMs} ms；首次查询 ${run.firstQueryMs} ms`,
    `- 语料：${run.docs} 篇 / ${run.chunks} 块 / ${run.corpusChars} 字符`,
    `- 向量化：${run.embedMs} ms（${run.embedThroughputCps} 字符/秒）`,
    `- 写入：${run.writeMs} ms；索引刷新：${run.refreshMs} ms`,
    `- 查询：端侧向量化 P50 ${run.queryEmbedMsP50} ms；seekdb 检索 P50 ${run.searchMsP50} ms；端到端 P50 ${run.e2eMsP50} ms`,
    `- 质量：Recall@5 ${pct(run.recall5)}；nDCG@5 ${pct(run.ndcg5)}；MRR ${run.mrr.toFixed(3)}`,
  ].join('\n');
}
