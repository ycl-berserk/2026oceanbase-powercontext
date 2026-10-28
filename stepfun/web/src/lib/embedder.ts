import { env, pipeline } from '@huggingface/transformers';
import type { Backend, ModelSpec, Precision } from './types';

env.useBrowserCache = true;
// WASM 线程数上限；浏览器未开启 cross-origin isolation 时 ORT 会自动回退单线程
const ortEnv = env.backends?.onnx as { wasm?: { numThreads?: number } } | undefined;
if (ortEnv?.wasm) {
  ortEnv.wasm.numThreads = Math.min(4, Math.max(1, navigator.hardwareConcurrency || 4));
}

const KB = 1024;

export const MODELS: ModelSpec[] = [
  {
    id: 'Xenova/bge-small-zh-v1.5',
    label: 'BGE-small-zh-v1.5（中文，512 维）',
    dimension: 512,
    pooling: 'cls',
    source: 'https://huggingface.co/Xenova/bge-small-zh-v1.5（BAAI/bge-small-zh-v1.5 的 ONNX 版本，MIT）',
    bytes: {
      fp32: 92629 * KB,
      fp16: 46384 * KB,
      int8: 23448 * KB,
    },
  },
  {
    id: 'Xenova/all-MiniLM-L6-v2',
    label: 'all-MiniLM-L6-v2（英文/跨语言，384 维）',
    dimension: 384,
    pooling: 'mean',
    source: 'https://huggingface.co/Xenova/all-MiniLM-L6-v2（sentence-transformers/all-MiniLM-L6-v2 的 ONNX 版本，Apache-2.0）',
    bytes: {
      fp32: 88269 * KB,
      fp16: 44236 * KB,
      int8: 22434 * KB,
    },
  },
];

export function getModel(modelId: string): ModelSpec {
  return MODELS.find((m) => m.id === modelId) ?? MODELS[0];
}

export interface WebGpuStatus {
  available: boolean;
  reason: string;
  adapter?: string;
}

type GpuLike = {
  requestAdapter: () => Promise<{ info?: Record<string, string> } | null>;
};

export async function detectWebGpu(): Promise<WebGpuStatus> {
  const gpu = (navigator as unknown as { gpu?: GpuLike }).gpu;
  if (!gpu) {
    return { available: false, reason: 'navigator.gpu 不存在：浏览器不支持 WebGPU 或已被禁用' };
  }
  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter) {
      return { available: false, reason: 'requestAdapter() 返回 null（无可用 GPU 适配器）' };
    }
    const info = (adapter as unknown as { info?: Record<string, string> }).info ?? {};
    const adapterText =
      [info.vendor, info.architecture, info.description].filter(Boolean).join(' / ') || 'WebGPU 适配器';
    return { available: true, reason: 'WebGPU 可用', adapter: adapterText };
  } catch (err) {
    return { available: false, reason: `WebGPU 初始化异常：${(err as Error).message}` };
  }
}

export function precisionToDtype(precision: Precision): 'fp32' | 'fp16' | 'q8' {
  if (precision === 'fp16') return 'fp16';
  if (precision === 'int8') return 'q8';
  return 'fp32';
}

/**
 * 如果 `web/public/models` 下已预置模型（scripts/fetch-model.sh），改用本地加载，
 * 便于离线 / 内网演示；否则回退到 Hugging Face 在线下载。
 */
export async function resolveModelSource(modelId: string): Promise<{ local: boolean }> {
  try {
    const res = await fetch(`/models/${modelId}/config.json`, { cache: 'no-store' });
    const type = res.headers.get('content-type') ?? '';
    if (res.ok && type.includes('json')) {
      env.allowLocalModels = true;
      env.allowRemoteModels = false;
      env.localModelPath = '/models';
      return { local: true };
    }
  } catch {
    /* 本地不存在，走在线下载 */
  }
  env.allowLocalModels = false;
  env.allowRemoteModels = true;
  return { local: false };
}

function useRemoteModels() {
  env.allowLocalModels = false;
  env.allowRemoteModels = true;
}

export interface LoadOptions {
  modelId: string;
  precision: Precision;
  /** 强制使用 WASM（用于演示降级路径） */
  forceWasm?: boolean;
  onProgress?: (p: { phase: 'download' | 'init'; file?: string; progress: number; loaded: number; total: number }) => void;
}

export interface EmbedderInfo {
  modelId: string;
  dimension: number;
  pooling: 'cls' | 'mean';
  backend: Backend;
  precision: Precision;
  dtype: string;
  adapter?: string;
  /** 自动降级/回退说明，界面需要明确展示 */
  note?: string;
  loadMs: number;
  downloadBytes: number;
  gpu: WebGpuStatus;
}

export interface EmbedResult {
  vectors: number[][];
  totalMs: number;
  chars: number;
  throughputCps: number;
  batchMs: number[];
}

type Extractor = (texts: string[], options: Record<string, unknown>) => Promise<{ tolist: () => number[][] }>;

export class Embedder {
  private extractor: Extractor | null = null;
  private loadedKey = '';
  info: EmbedderInfo | null = null;

  get ready() {
    return this.extractor !== null;
  }

  async load(options: LoadOptions): Promise<EmbedderInfo> {
    const model = getModel(options.modelId);
    const gpu = await detectWebGpu();
    const source = await resolveModelSource(model.id);
    let backend: Backend = options.forceWasm ? 'wasm' : gpu.available ? 'webgpu' : 'wasm';
    let dtype = precisionToDtype(options.precision);
    const notes: string[] = [];
    if (source.local) notes.push('使用本地预置模型（/models）');    if (options.forceWasm) notes.push('已手动切换为 WASM 后端');
    if (backend === 'wasm' && dtype === 'fp16') {
      dtype = 'fp32';
      notes.push('WASM 后端不支持 fp16，已回退为 fp32 权重');
    }

    const key = `${model.id}|${backend}|${dtype}`;
    if (this.extractor && this.loadedKey === key && this.info) return this.info;

    this.dispose();
    const started = performance.now();
    let downloadBytes = 0;
    const progress_callback = (p: { status?: string; file?: string; progress?: number; loaded?: number; total?: number }) => {
      if (typeof p.total === 'number') downloadBytes = Math.max(downloadBytes, p.total);
      if (p.status === 'progress' || p.status === 'download') {
        options.onProgress?.({
          phase: 'download',
          file: p.file,
          progress: Math.max(0, Math.min(1, (p.progress ?? 0) / 100)),
          loaded: p.loaded ?? 0,
          total: p.total ?? 0,
        });
      }
    };

    const create = async (dev: Backend, dt: string) =>
      (await pipeline('feature-extraction', model.id, {
        device: dev === 'webgpu' ? 'webgpu' : 'wasm',
        dtype: dt as never,
        progress_callback,
      })) as unknown as Extractor;

    try {
      this.extractor = await create(backend, dtype);
    } catch (err) {
      const message = (err as Error).message;
      // 本地模型文件不全 / 路径不对时，退回在线模型再试一次
      if (source.local) {
        notes.push(`本地模型加载失败，改用在线模型：${message}`);
        useRemoteModels();
        try {
          this.extractor = await create(backend, dtype);
        } catch (retryErr) {
          if (backend !== 'webgpu') throw retryErr;
          notes.push(`WebGPU 推理初始化失败，已自动降级到 WASM：${(retryErr as Error).message}`);
          backend = 'wasm';
          if (dtype === 'fp16') dtype = 'fp32';
          downloadBytes = 0;
          this.extractor = await create(backend, dtype);
        }
      } else if (backend === 'webgpu') {
        notes.push(`WebGPU 推理初始化失败，已自动降级到 WASM：${message}`);
        backend = 'wasm';
        if (dtype === 'fp16') dtype = 'fp32';
        downloadBytes = 0;
        this.extractor = await create(backend, dtype);
      } else {
        throw err;
      }
    }

    options.onProgress?.({ phase: 'init', progress: 1, loaded: 0, total: 0 });
    // 预热：首帧包含图优化/管线编译，单独计时
    await this.extractor(['预热'], { pooling: model.pooling, normalize: true });

    this.loadedKey = key;
    this.info = {
      modelId: model.id,
      dimension: model.dimension,
      pooling: model.pooling,
      backend,
      precision: options.precision,
      dtype,
      adapter: gpu.adapter,
      note: notes.length ? notes.join('；') : undefined,
      loadMs: performance.now() - started,
      downloadBytes,
      gpu,
    };
    return this.info;
  }

  async embed(texts: string[], batchSize = 8, onProgress?: (done: number, total: number) => void): Promise<EmbedResult> {
    if (!this.extractor || !this.info) throw new Error('模型尚未加载');
    const size = Math.max(1, Math.min(64, batchSize));
    const vectors: number[][] = [];
    const batchMs: number[] = [];
    const started = performance.now();
    let chars = 0;

    for (let i = 0; i < texts.length; i += size) {
      const batch = texts.slice(i, i + size);
      chars += batch.reduce((sum, t) => sum + t.length, 0);
      const t0 = performance.now();
      const out = await this.extractor(batch, { pooling: this.info.pooling, normalize: true });
      vectors.push(...out.tolist());
      batchMs.push(performance.now() - t0);
      onProgress?.(Math.min(texts.length, i + size), texts.length);
      // 让出一帧，保证进度条与按钮状态可以刷新
      await new Promise((r) => setTimeout(r, 0));
    }

    const totalMs = performance.now() - started;
    return {
      vectors,
      totalMs,
      chars,
      throughputCps: totalMs > 0 ? chars / (totalMs / 1000) : 0,
      batchMs,
    };
  }

  dispose() {
    const extractor = this.extractor as unknown as { dispose?: () => Promise<void> } | null;
    extractor?.dispose?.().catch(() => {});
    this.extractor = null;
    this.info = null;
    this.loadedKey = '';
  }
}

/** 读取浏览器 Cache Storage 中该模型的实际缓存体积（下载完成后可用于体积实测） */
export async function cachedModelBytes(modelId: string): Promise<number | null> {
  if (!('caches' in window)) return null;
  const names = await caches.keys();
  let total = 0;
  let found = 0;
  for (const name of names) {
    const cache = await caches.open(name);
    for (const req of await cache.keys()) {
      if (!req.url.includes(modelId)) continue;
      const res = await cache.match(req);
      const len = Number(res?.headers.get('content-length') ?? 0);
      if (len > 0) {
        total += len;
        found += 1;
      }
    }
  }
  return found > 0 ? total : null;
}
