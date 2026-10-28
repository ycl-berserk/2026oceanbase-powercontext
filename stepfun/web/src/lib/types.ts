export type Backend = 'webgpu' | 'wasm';
export type Precision = 'fp32' | 'fp16' | 'int8';

export interface ModelSpec {
  id: string;
  label: string;
  dimension: number;
  /** 实测体积（Bytes，来自 Hugging Face 上 onnx/*.onnx 文件大小） */
  bytes: Record<Precision, number>;
  source: string;
  pooling: 'cls' | 'mean';
}

export interface KbInfo {
  name: string;
  label: string;
  model: string;
  dimension: number;
  chunks: number;
  collection: string;
  exists: boolean;
  createdAt: number;
  updatedAt: number;
}

export interface Chunk {
  id: string;
  text: string;
  metadata: {
    docId: string;
    docTitle: string;
    chunkIndex: number;
    chars: number;
    source: string;
  };
}

export interface SearchHit {
  id: string;
  text: string;
  metadata: Record<string, unknown> | null;
  score: number | null;
  rank: number;
}

export interface SearchResponse {
  mode: 'hybrid' | 'vector' | 'keyword';
  query: string;
  keyword: string | null;
  hits: SearchHit[];
  timings: { searchMs: number; totalMs: number };
}

export interface ImportTimings {
  embedMs: number;
  writeMs: number;
  refreshMs: number;
  probeMs?: number;
  throughputCps: number;
}

export interface BenchQueryResult {
  query: string;
  gold: string[];
  hits: string[];
  recall: number;
  ndcg: number;
  mrr: number;
  queryEmbedMs: number;
  searchMs: number;
  e2eMs: number;
}

export interface EvalSet {
  name: string;
  docs: { id: string; title: string; file: string }[];
  queries: { id?: string; query: string; gold: string[] }[];
}

export interface BenchRun {
  id: string;
  createdAt: number;
  model: string;
  precision: Precision;
  backend: Backend;
  dimension: number;
  modelBytes: number | null;
  docs: number;
  chunks: number;
  corpusChars: number;
  loadMs: number;
  firstQueryMs: number;
  embedMs: number;
  embedThroughputCps: number;
  writeMs: number;
  refreshMs: number;
  writeRoundTripMs: number;
  searchMsP50: number;
  queryEmbedMsP50: number;
  e2eMsP50: number;
  recall5: number;
  ndcg5: number;
  mrr: number;
  queries: BenchQueryResult[];
}
