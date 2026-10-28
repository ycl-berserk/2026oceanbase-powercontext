import { defineStore } from 'pinia';
import { computed, reactive, ref } from 'vue';
import { api } from '../lib/api';
import { runBenchmark } from '../lib/bench';
import { chunkText, DEFAULT_CHUNK_OPTIONS, type ChunkOptions } from '../lib/chunker';
import { cachedModelBytes, Embedder, getModel, MODELS, type EmbedderInfo, type WebGpuStatus } from '../lib/embedder';
import type { BenchRun, Chunk, EvalSet, ImportTimings, KbInfo, Precision, SearchResponse } from '../lib/types';

export interface SourceDoc {
  id: string;
  title: string;
  text: string;
  source: string;
}

const LS_SETTINGS = 'stepfun.settings.v1';
const LS_BENCH = 'stepfun.bench.v1';

function uid(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

function slugify(text: string): string {
  const ascii = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (ascii.length >= 2) return ascii.slice(0, 32);
  return `kb-${Date.now().toString(36)}`;
}

export const useAppStore = defineStore('app', () => {
  /* ---------------- 服务端 / 引擎状态 ---------------- */
  const server = reactive({
    status: 'connecting' as 'connecting' | 'online' | 'offline',
    error: '',
    info: null as null | { mode: string; path: string; database: string; version: string },
  });

  const engine = reactive({
    status: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
    error: '',
    progress: 0,
    file: '',
    phase: '' as '' | 'download' | 'init',
    info: null as EmbedderInfo | null,
    gpu: null as WebGpuStatus | null,
    measuredBytes: null as number | null,
  });

  const embedder = new Embedder();

  /* ---------------- 配置 ---------------- */
  const settings = reactive({
    modelId: MODELS[0].id,
    precision: 'int8' as Precision,
    forceWasm: false,
    batchSize: 8,
    chunk: { ...DEFAULT_CHUNK_OPTIONS } as ChunkOptions,
    topK: 5,
    mode: 'hybrid' as 'hybrid' | 'vector' | 'keyword',
    poolSize: 40,
    rankConstant: 60,
  });

  const model = computed(() => getModel(settings.modelId));

  /* ---------------- 知识库 ---------------- */
  const kbs = ref<KbInfo[]>([]);
  const activeKb = ref<string>('');
  const kbBusy = ref(false);
  const activeKbInfo = computed(() => kbs.value.find((k) => k.name === activeKb.value) ?? null);

  /* ---------------- 导入 ---------------- */
  const sources = ref<SourceDoc[]>([]);
  const importState = reactive({
    running: false,
    stage: '' as '' | 'chunk' | 'embed' | 'write' | 'done',
    progress: 0,
    message: '',
    lastImport: null as null | { chunks: number; inserted: number; total: number; timings: ImportTimings; verification: unknown },
  });

  /* ---------------- 检索 ---------------- */
  const search = reactive({
    running: false,
    error: '',
    query: '',
    result: null as SearchResponse | null,
    timings: null as null | { queryEmbedMs: number; searchMs: number; totalMs: number; e2eMs: number },
  });

  /* ---------------- 评测 ---------------- */
  const evalSet = ref<EvalSet | null>(null);
  const bench = reactive({
    running: false,
    progress: 0,
    message: '',
    runs: [] as BenchRun[],
  });

  /* ---------------- 初始化 ---------------- */
  async function init() {
    loadSettings();
    await Promise.all([connectServer(), loadEvalSet()]);
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(LS_SETTINGS);
      if (!raw) return;
      const saved = JSON.parse(raw);
      Object.assign(settings, saved);
      settings.chunk = { ...DEFAULT_CHUNK_OPTIONS, ...(saved.chunk ?? {}) };
    } catch {
      /* ignore */
    }
    try {
      const raw = localStorage.getItem(LS_BENCH);
      if (raw) bench.runs = JSON.parse(raw);
    } catch {
      /* ignore */
    }
  }

  function saveSettings() {
    localStorage.setItem(LS_SETTINGS, JSON.stringify(settings));
  }

  async function connectServer() {
    server.status = 'connecting';
    try {
      server.info = await api.health();
      server.status = 'online';
      server.error = '';
      await refreshKbs();
    } catch (err) {
      server.status = 'offline';
      server.error = (err as Error).message;
    }
  }

  async function refreshKbs() {
    if (server.status !== 'online') return;
    const { kbs: list } = await api.listKbs();
    kbs.value = list;
    if (!activeKb.value && list.length) activeKb.value = list[0].name;
    if (activeKb.value && !list.some((k) => k.name === activeKb.value)) {
      activeKb.value = list[0]?.name ?? '';
    }
  }

  async function loadEvalSet() {
    try {
      const res = await fetch('/corpus/eval.json');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      evalSet.value = await res.json();
    } catch (err) {
      console.warn('评测集加载失败', err);
    }
  }

  /* ---------------- 模型 ---------------- */
  async function loadModel() {
    engine.status = 'loading';
    engine.error = '';
    engine.progress = 0;
    engine.file = '';
    engine.phase = 'download';
    engine.info = null;
    try {
      const info = await embedder.load({
        modelId: settings.modelId,
        precision: settings.precision,
        forceWasm: settings.forceWasm,
        onProgress: (p) => {
          engine.phase = p.phase;
          engine.progress = p.progress;
          if (p.file) engine.file = p.file;
        },
      });
      engine.info = info;
      engine.gpu = info.gpu;
      engine.status = 'ready';
      engine.measuredBytes = await cachedModelBytes(settings.modelId);
      saveSettings();
    } catch (err) {
      engine.status = 'error';
      engine.error = (err as Error).message;
    }
  }

  function recordBench(run: BenchRun) {
    bench.runs = [...bench.runs, run];
    localStorage.setItem(LS_BENCH, JSON.stringify(bench.runs));
  }

  function clearBench() {
    bench.runs = [];
    localStorage.removeItem(LS_BENCH);
  }

  /* ---------------- 语料 ---------------- */
  function setSources(docs: SourceDoc[]) {
    sources.value = docs;
    importState.lastImport = null;
  }

  async function loadSampleCorpus() {
    const set = evalSet.value;
    if (!set) throw new Error('评测集未加载');
    const docs: SourceDoc[] = [];
    for (const d of set.docs) {
      const res = await fetch(`/corpus/${d.file}`);
      if (!res.ok) throw new Error(`读取 ${d.file} 失败`);
      docs.push({ id: d.id, title: d.title, text: await res.text(), source: d.file });
    }
    setSources(docs);
  }

  function addPastedDoc(title: string, text: string) {
    const id = slugify(title) + '-' + Math.random().toString(36).slice(2, 6);
    setSources([...sources.value, { id, title, text, source: '手动粘贴' }]);
  }

  function removeSource(id: string) {
    setSources(sources.value.filter((d) => d.id !== id));
  }

  function buildChunks(): Chunk[] {
    return sources.value.flatMap((doc) => chunkText(doc.id, doc.title, doc.source, doc.text, settings.chunk));
  }

  function ensureKbName() {
    const base = activeKb.value || slugify(`kb-${settings.precision}`);
    return base;
  }

  async function ensureActiveKb(dimension: number): Promise<string> {
    let name = ensureKbName();
    const existing = kbs.value.find((k) => k.name === name);
    if (existing && existing.dimension !== dimension) {
      // 模型维度变了：不打断流程，自动新建一个匹配维度的知识库并切过去
      const nextName = `${name}-${dimension}d`.slice(0, 40);
      await api.createKb({
        name: nextName,
        label: `${existing.label} · ${dimension}d`,
        model: settings.modelId,
        dimension,
      });
      await refreshKbs();
      activeKb.value = nextName;
      importState.message = `原知识库是 ${existing.dimension} 维，已自动新建 ${nextName}（${dimension} 维）`;
      return nextName;
    }
    if (!existing) {
      await api.createKb({ name, label: name, model: settings.modelId, dimension });
      await refreshKbs();
      activeKb.value = name;
    }
    return name;
  }

  async function importSources() {
    if (engine.status !== 'ready' || !engine.info) throw new Error('请先加载模型');
    if (!sources.value.length) throw new Error('没有可导入的文档');

    importState.running = true;
    importState.progress = 0;
    importState.lastImport = null;
    try {
      importState.stage = 'chunk';
      importState.message = '切分文档…';
      const chunks = buildChunks();
      if (!chunks.length) throw new Error('文档切分后为空');

      const kbName = await ensureActiveKb(engine.info.dimension);

      importState.stage = 'embed';
      importState.message = `端侧向量化 ${chunks.length} 个分块…`;
      const embed = await embedder.embed(
        chunks.map((c) => c.text),
        settings.batchSize,
        (done, total) => {
          importState.progress = total ? done / total : 0;
          importState.message = `端侧向量化 ${done}/${total} 个分块…`;
        }
      );

      importState.stage = 'write';
      importState.message = '写入 seekdb 并刷新索引…';
      const written = await api.addDocuments(kbName, {
        chunks: chunks.map((c) => ({ id: c.id, text: c.text, metadata: c.metadata as unknown as Record<string, unknown> })),
        embeddings: embed.vectors,
        batchSize: 64,
        refresh: true,
        verify: true,
      });

      importState.stage = 'done';
      importState.progress = 1;
      importState.message = `完成：${written.inserted} 个分块写入，索引已刷新`;
      importState.lastImport = {
        chunks: chunks.length,
        inserted: written.inserted,
        total: written.total,
        timings: {
          embedMs: embed.totalMs,
          writeMs: written.timings.writeMs,
          refreshMs: written.timings.refreshMs,
          probeMs: written.verification?.probeMs,
          throughputCps: embed.throughputCps,
        },
        verification: written.verification,
      };
      await refreshKbs();
    } finally {
      importState.running = false;
    }
  }

  /* ---------------- 检索 ---------------- */
  async function runSearch(query: string) {
    if (engine.status !== 'ready' || !engine.info) throw new Error('请先加载模型');
    if (!activeKb.value) throw new Error('请先选择或创建知识库');
    const q = query.trim();
    if (!q) throw new Error('查询不能为空');

    search.running = true;
    search.error = '';
    try {
      const t0 = performance.now();
      const embed = await embedder.embed([q], 1);
      const queryEmbedMs = performance.now() - t0;
      const res = await api.search(activeKb.value, {
        query: q,
        embedding: embed.vectors[0],
        keyword: q,
        mode: settings.mode,
        topK: settings.topK,
        poolSize: settings.poolSize,
        rankConstant: settings.rankConstant,
      });
      const e2eMs = performance.now() - t0;
      search.query = q;
      search.result = res;
      search.timings = {
        queryEmbedMs: +queryEmbedMs.toFixed(1),
        searchMs: res.timings.searchMs,
        totalMs: res.timings.totalMs,
        e2eMs: +e2eMs.toFixed(1),
      };
    } catch (err) {
      search.error = (err as Error).message;
      search.result = null;
    } finally {
      search.running = false;
    }
  }

  /* ---------------- 评测 ---------------- */
  async function runBench() {
    if (engine.status !== 'ready' || !engine.info) throw new Error('请先加载模型');
    if (!evalSet.value) throw new Error('评测集未加载');
    bench.running = true;
    bench.progress = 0;
    bench.message = '准备评测…';
    try {
      const run = await runBenchmark({
        embedder,
        evalSet: evalSet.value,
        modelId: settings.modelId,
        precision: settings.precision,
        backend: engine.info.backend,
        dimension: engine.info.dimension,
        modelBytes: engine.measuredBytes ?? engine.info.downloadBytes ?? null,
        loadMs: engine.info.loadMs,
        chunk: settings.chunk,
        batchSize: settings.batchSize,
        topK: settings.topK,
        onProgress: (pct, message) => {
          bench.progress = pct;
          bench.message = message;
        },
      });
      recordBench(run);
      bench.message = `完成：Recall@5=${(run.recall5 * 100).toFixed(1)}%，nDCG@5=${(run.ndcg5 * 100).toFixed(1)}%`;
    } finally {
      bench.running = false;
    }
  }

  return {
    server,
    engine,
    embedder,
    settings,
    model,
    kbs,
    activeKb,
    activeKbInfo,
    kbBusy,
    sources,
    importState,
    search,
    evalSet,
    bench,
    init,
    connectServer,
    refreshKbs,
    loadModel,
    setSources,
    loadSampleCorpus,
    addPastedDoc,
    removeSource,
    buildChunks,
    importSources,
    runSearch,
    runBench,
    clearBench,
    saveSettings,
  };
});
