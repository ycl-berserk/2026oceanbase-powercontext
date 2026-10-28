export interface Ranked {
  retrieve: string[];
  gold: string[];
  k: number;
}

/** Recall@K：命中的相关文档数 / 相关文档总数 */
export function recallAtK({ retrieve, gold, k }: Ranked): number {
  if (gold.length === 0) return 0;
  const rel = new Set(gold);
  const hit = new Set(retrieve.slice(0, k).filter((id) => rel.has(id)));
  return hit.size / rel.size;
}

/** nDCG@K（二值相关性） */
export function ndcgAtK({ retrieve, gold, k }: Ranked): number {
  const rel = new Set(gold);
  let dcg = 0;
  retrieve.slice(0, k).forEach((id, i) => {
    if (rel.has(id)) dcg += 1 / Math.log2(i + 2);
  });
  let idcg = 0;
  for (let i = 0; i < Math.min(gold.length, k); i++) idcg += 1 / Math.log2(i + 2);
  return idcg === 0 ? 0 : dcg / idcg;
}

/** MRR：第一个相关结果排名的倒数 */
export function mrr({ retrieve, gold }: Omit<Ranked, 'k'>): number {
  const rel = new Set(gold);
  const idx = retrieve.findIndex((id) => rel.has(id));
  return idx < 0 ? 0 : 1 / (idx + 1);
}

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** 多块命中同一文档时按首次出现去重，保证 doc 级指标可比较 */
export function dedupeDocIds(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    const docId = id.includes('#') ? id.slice(0, id.indexOf('#')) : id;
    if (seen.has(docId)) continue;
    seen.add(docId);
    out.push(docId);
  }
  return out;
}
