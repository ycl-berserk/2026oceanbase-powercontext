<script setup lang="ts">
import { computed, ref } from 'vue';
import { useAppStore } from '../stores/app';
import { fmtMs } from '../lib/format';

const store = useAppStore();
const query = ref('');
const error = ref('');
const advanced = ref(false);
const keyword = ref('');

const modes = [
  { id: 'hybrid', label: '混合检索', tip: 'seekdb DBMS_HYBRID_SEARCH：全文 + 向量，RRF 融合' },
  { id: 'vector', label: '向量', tip: '纯 KNN（HNSW，cosine）' },
  { id: 'keyword', label: '全文', tip: '仅全文索引匹配（ik 分词）' },
] as const;

const canSearch = computed(
  () => store.engine.status === 'ready' && !!store.activeKb && !store.search.running
);

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);
}

const highlightTerms = computed(() => {
  const q = store.search.query.trim();
  if (!q) return [];
  const parts = q.split(/[\s,，。.;；:：?？!！/、]+/).filter((t) => t.length >= 2);
  return Array.from(new Set([q, ...parts])).sort((a, b) => b.length - a.length);
});

function highlight(text: string) {
  let html = escapeHtml(text);
  for (const term of highlightTerms.value) {
    const escaped = escapeHtml(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    html = html.replace(new RegExp(escaped, 'gi'), (m) => `<mark>${m}</mark>`);
  }
  return html;
}

async function run() {
  error.value = '';
  try {
    await store.runSearch(keyword.value.trim() ? `${query.value}` : query.value);
  } catch (err) {
    error.value = (err as Error).message;
  }
}
</script>

<template>
  <section class="card">
    <h2>
      检索
      <span class="hint">查询向量在浏览器内生成，召回与融合全部在 seekdb 完成</span>
    </h2>

    <div class="row">
      <input
        v-model="query"
        class="grow"
        placeholder="输入查询，例如：seekdb 的混合检索是怎么做 RRF 融合的？"
        @keyup.enter="canSearch && run()"
      />
      <button class="btn primary" :disabled="!canSearch" @click="run">
        {{ store.search.running ? '检索中…' : '检索' }}
      </button>
    </div>

    <div class="row wrap" style="margin-top: 10px">
      <div class="row" style="gap: 4px">
        <button
          v-for="m in modes"
          :key="m.id"
          class="btn sm"
          :class="{ primary: store.settings.mode === m.id }"
          :title="m.tip"
          @click="store.settings.mode = m.id; store.saveSettings()"
        >
          {{ m.label }}
        </button>
      </div>
      <div class="spacer" />
      <label class="row small muted" style="gap: 6px; width: auto">
        TopK
        <input v-model.number="store.settings.topK" type="number" min="1" max="20" style="width: 64px" @change="store.saveSettings()" />
      </label>
      <button class="btn sm ghost" @click="advanced = !advanced">{{ advanced ? '收起' : '高级' }}</button>
    </div>

    <div v-if="advanced" class="row wrap" style="margin-top: 10px; align-items: flex-end">
      <div class="field grow" style="margin: 0">
        <label>全文关键词 <span class="dim">留空则用查询原文</span></label>
        <input v-model="keyword" placeholder="例如：RRF 融合" />
      </div>
      <div class="field" style="margin: 0; width: 110px">
        <label>候选池</label>
        <input v-model.number="store.settings.poolSize" type="number" min="5" max="200" @change="store.saveSettings()" />
      </div>
      <div class="field" style="margin: 0; width: 110px">
        <label>RRF k</label>
        <input v-model.number="store.settings.rankConstant" type="number" min="1" max="200" @change="store.saveSettings()" />
      </div>
    </div>

    <div v-if="error" class="notice error" style="margin-top: 10px">{{ error }}</div>
    <div v-if="store.search.error" class="notice error" style="margin-top: 10px">{{ store.search.error }}</div>

    <div v-if="store.search.timings" class="stats" style="margin-top: 12px">
      <div class="stat"><div class="k">查询向量化（端侧）</div><div class="v">{{ fmtMs(store.search.timings.queryEmbedMs) }}</div></div>
      <div class="stat"><div class="k">seekdb 检索</div><div class="v">{{ fmtMs(store.search.timings.searchMs) }}</div></div>
      <div class="stat"><div class="k">端到端</div><div class="v">{{ fmtMs(store.search.timings.e2eMs) }}</div></div>
      <div class="stat"><div class="k">模式</div><div class="v" style="font-size: 13px">{{ store.search.result?.mode }}</div></div>
    </div>

    <div v-if="store.search.result" style="margin-top: 14px">
      <div class="row" style="margin-bottom: 8px">
        <span class="small muted">
          命中 {{ store.search.result.hits.length }} 条 · 查询「{{ store.search.result.query }}」
          <template v-if="store.search.result.keyword && store.search.result.mode !== 'vector'">
            · 全文词「{{ store.search.result.keyword }}」
          </template>
        </span>
      </div>

      <div class="hits">
        <article v-for="hit in store.search.result.hits" :key="hit.id" class="hit">
          <div class="hit-head">
            <span class="rank">{{ hit.rank }}</span>
            <b class="small">{{ (hit.metadata as any)?.docTitle ?? hit.id }}</b>
            <span class="tag">#{{ (hit.metadata as any)?.chunkIndex ?? 0 }}</span>
            <span class="spacer" />
            <span class="tiny dim mono">score {{ hit.score == null ? '—' : hit.score.toFixed(4) }}</span>
          </div>
          <div class="text" v-html="highlight(hit.text)" />
        </article>
        <div v-if="!store.search.result.hits.length" class="empty">没有命中结果，试试更换关键词或降低阈值</div>
      </div>
    </div>

    <div v-else-if="!store.search.running" class="empty">
      {{ store.engine.status === 'ready' ? '输入查询开始检索' : '请先加载模型' }}
    </div>
  </section>
</template>
