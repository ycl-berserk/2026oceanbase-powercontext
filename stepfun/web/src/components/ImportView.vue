<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useAppStore } from '../stores/app';
import { fmtInt, fmtMs } from '../lib/format';

const emit = defineEmits<{ (e: 'go-search'): void }>();
const store = useAppStore();

const over = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const error = ref('');
const paste = reactive({ open: false, title: '', text: '' });

const chunks = computed(() => (store.sources.length ? store.buildChunks() : []));
const chars = computed(() => store.sources.reduce((sum, d) => sum + d.text.length, 0));
const result = computed(() => store.importState.lastImport);

const ready = computed(() => store.engine.status === 'ready');
const busy = computed(() => store.importState.running);

function pickFiles() {
  fileInput.value?.click();
}

async function addFiles(files: FileList | File[]) {
  error.value = '';
  const next = [...store.sources];
  for (const file of Array.from(files)) {
    if (!/\.(txt|md|markdown)$/i.test(file.name)) continue;
    const text = await file.text();
    const title = file.name.replace(/\.(txt|md|markdown)$/i, '');
    next.push({
      id: `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 24) || 'doc'}-${Math.random().toString(36).slice(2, 6)}`,
      title,
      text,
      source: file.name,
    });
  }
  store.setSources(next);
}

async function onDrop(e: DragEvent) {
  over.value = false;
  if (e.dataTransfer?.files?.length) await addFiles(e.dataTransfer.files);
}

async function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files) await addFiles(input.files);
  input.value = '';
}

async function loadSample() {
  error.value = '';
  try {
    await store.loadSampleCorpus();
  } catch (err) {
    error.value = (err as Error).message;
  }
}

function addPaste() {
  if (!paste.title.trim() || !paste.text.trim()) return;
  store.addPastedDoc(paste.title.trim(), paste.text.trim());
  paste.title = '';
  paste.text = '';
  paste.open = false;
}

async function runImport() {
  error.value = '';
  try {
    await store.importSources();
  } catch (err) {
    error.value = (err as Error).message;
  }
}
</script>

<template>
  <div class="split">
    <!-- 左：语料 -->
    <section class="card">
      <h2>
        语料
        <span class="hint">{{ store.sources.length }} 篇 · {{ fmtInt(chars) }} 字符 · {{ chunks.length }} 块</span>
      </h2>

      <div
        class="drop"
        :class="{ over }"
        @dragover.prevent="over = true"
        @dragleave.prevent="over = false"
        @drop.prevent="onDrop"
        @click="pickFiles"
      >
        拖入 .txt / .md 文件，或点击选择
        <div class="tiny dim" style="margin-top: 4px">文件只在浏览器内解析，向量也在本地计算</div>
      </div>
      <input ref="fileInput" type="file" accept=".txt,.md,.markdown" multiple hidden @change="onFileInput" />

      <div class="row" style="margin-top: 10px">
        <button class="btn sm" @click="loadSample">载入示例语料（{{ store.evalSet?.docs.length ?? 0 }} 篇）</button>
        <button class="btn sm ghost" @click="paste.open = !paste.open">粘贴文本</button>
        <div class="spacer" />
        <button v-if="store.sources.length" class="btn sm ghost" @click="store.setSources([])">清空</button>
      </div>

      <div v-if="paste.open" style="margin-top: 10px">
        <div class="field">
          <label>标题</label>
          <input v-model="paste.title" placeholder="文档标题" />
        </div>
        <div class="field">
          <label>正文</label>
          <textarea v-model="paste.text" rows="5" placeholder="粘贴任意文本内容…" />
        </div>
        <button class="btn sm primary" @click="addPaste">添加</button>
      </div>

      <h3>分块策略</h3>
      <div class="row" style="align-items: flex-end">
        <div class="field grow" style="margin: 0">
          <label>最大块长（字符）</label>
          <input v-model.number="store.settings.chunk.maxChars" type="number" min="80" max="1200" step="20" @change="store.saveSettings()" />
        </div>
        <div class="field grow" style="margin: 0">
          <label>重叠（字符）</label>
          <input v-model.number="store.settings.chunk.overlap" type="number" min="0" max="300" step="8" @change="store.saveSettings()" />
        </div>
      </div>

      <div v-if="store.sources.length" class="list" style="margin-top: 12px; max-height: 240px; overflow-y: auto">
        <div v-for="doc in store.sources" :key="doc.id" class="item" style="cursor: default">
          <div style="min-width: 0">
            <div class="title">{{ doc.title }}</div>
            <div class="meta">{{ fmtInt(doc.text.length) }} 字符 · {{ doc.source }}</div>
          </div>
          <button class="btn sm ghost" @click="store.removeSource(doc.id)">×</button>
        </div>
      </div>
    </section>

    <!-- 右：执行 -->
    <section class="card">
      <h2>
        端侧向量化 → seekdb
        <span class="hint">浏览器内推理，写入后刷新索引</span>
      </h2>

      <div v-if="!ready" class="notice warn">请先在左侧「端侧模型」中加载模型。</div>
      <div v-else class="notice ok">
        {{ store.engine.info?.backend === 'webgpu' ? 'WebGPU' : 'WASM' }} ·
        {{ store.engine.info?.dtype }} · {{ store.model.label }} ·
        批量 {{ store.settings.batchSize }}
      </div>

      <div class="field" style="margin-top: 10px">
        <label>查询 / 写入批量大小</label>
        <input v-model.number="store.settings.batchSize" type="number" min="1" max="64" @change="store.saveSettings()" />
      </div>

      <button class="btn primary" style="width: 100%" :disabled="busy || !ready || !store.sources.length" @click="runImport">
        {{ busy ? '处理中…' : `开始导入（${chunks.length} 块）` }}
      </button>

      <div v-if="busy" style="margin-top: 12px">
        <div class="progress"><span :style="{ width: `${Math.round(store.importState.progress * 100)}%` }" /></div>
        <div class="tiny dim" style="margin-top: 4px">{{ store.importState.message }}</div>
      </div>

      <div v-if="error" class="notice error" style="margin-top: 10px">{{ error }}</div>

      <template v-if="result">
        <h3>本次写入</h3>
        <div class="stats">
          <div class="stat"><div class="k">分块</div><div class="v">{{ fmtInt(result.inserted) }}</div></div>
          <div class="stat"><div class="k">集合总数</div><div class="v">{{ fmtInt(result.total) }}</div></div>
          <div class="stat"><div class="k">向量化</div><div class="v">{{ fmtMs(result.timings.embedMs) }}</div></div>
          <div class="stat"><div class="k">写入</div><div class="v">{{ fmtMs(result.timings.writeMs) }}</div></div>
          <div class="stat"><div class="k">索引刷新</div><div class="v">{{ fmtMs(result.timings.refreshMs) }}</div></div>
          <div class="stat"><div class="k">吞吐</div><div class="v">{{ Math.round(result.timings.throughputCps) }}<span class="tiny dim"> 字/秒</span></div></div>
        </div>

        <div
          v-if="result.verification"
          class="notice"
          :class="(result.verification as any).hit ? 'ok' : 'error'"
          style="margin-top: 10px"
        >
          写后自检：用第 1 块向量回查，{{ (result.verification as any).hit ? '命中自身，索引已生效' : '未命中，请手动刷新索引' }}
          <span class="dim">（{{ fmtMs((result.verification as any).probeMs) }}）</span>
        </div>

        <button class="btn" style="width: 100%; margin-top: 10px" @click="emit('go-search')">去检索 →</button>
      </template>
    </section>
  </div>
</template>
