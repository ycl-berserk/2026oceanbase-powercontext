<script setup lang="ts">
import { computed, ref } from 'vue';
import { useAppStore } from '../stores/app';
import { benchToMarkdown } from '../lib/bench';
import { fmtMb, fmtMs, fmtPct } from '../lib/format';
import type { BenchRun } from '../lib/types';

const store = useAppStore();
const error = ref('');
const showDetail = ref(false);

const latest = computed<BenchRun | null>(() => store.bench.runs[store.bench.runs.length - 1] ?? null);
const canRun = computed(() => store.engine.status === 'ready' && !store.bench.running && !!store.evalSet);

async function run() {
  error.value = '';
  try {
    await store.runBench();
  } catch (err) {
    error.value = (err as Error).message;
  }
}

function download(format: 'md' | 'json') {
  const runs = store.bench.runs;
  if (!runs.length) return;
  const content =
    format === 'md'
      ? [`# 评测结果（${new Date().toLocaleString('zh-CN')}）`, '', ...runs.map(benchToMarkdown)].join('\n\n')
      : JSON.stringify(runs, null, 2);
  const blob = new Blob([content], { type: format === 'md' ? 'text/markdown' : 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `stepfun-bench.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <section class="card">
    <h2>
      固定评测集
      <span class="hint">{{ store.evalSet?.name ?? '未加载' }}</span>
    </h2>

    <div class="notice">
      每次运行都会新建一个 <code>bench-&lt;精度&gt;-&lt;后端&gt;</code> 知识库，把同一批语料重新向量化、写入、刷新，再跑同一组查询，
      指标按文档级去重后计算 Recall@5 / nDCG@5 / MRR。切换精度或后端后再次运行，即可得到可比的三行数据。
    </div>

    <div class="row" style="margin-top: 10px">
      <button class="btn primary" :disabled="!canRun" @click="run">
        {{ store.bench.running ? `评测中… ${Math.round(store.bench.progress)}%` : `运行评测（${store.evalSet?.queries.length ?? 0} 条查询）` }}
      </button>
      <button class="btn sm ghost" :disabled="!store.bench.runs.length" @click="download('md')">导出 Markdown</button>
      <button class="btn sm ghost" :disabled="!store.bench.runs.length" @click="download('json')">导出 JSON</button>
      <div class="spacer" />
      <button class="btn sm ghost" :disabled="!store.bench.runs.length" @click="store.clearBench()">清空</button>
    </div>

    <div v-if="store.bench.running" style="margin-top: 10px">
      <div class="progress"><span :style="{ width: `${Math.round(store.bench.progress)}%` }" /></div>
      <div class="tiny dim" style="margin-top: 4px">{{ store.bench.message }}</div>
    </div>

    <div v-if="error" class="notice error" style="margin-top: 10px">{{ error }}</div>
    <div v-if="!canRun && !store.bench.running" class="notice warn" style="margin-top: 10px">
      请先在左侧加载模型。
    </div>

    <h3 v-if="store.bench.runs.length">结果对比</h3>
    <div v-if="store.bench.runs.length" class="scroll-x">
      <table class="grid">
        <thead>
          <tr>
            <th>配置</th>
            <th>模型体积</th>
            <th>加载</th>
            <th>向量化</th>
            <th>写入</th>
            <th>刷新</th>
            <th>查询向量化 P50</th>
            <th>seekdb P50</th>
            <th>端到端 P50</th>
            <th>Recall@5</th>
            <th>nDCG@5</th>
            <th>MRR</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in store.bench.runs" :key="r.id">
            <td>
              <b>{{ r.precision.toUpperCase() }}</b>
              <span class="tag" style="margin-left: 6px">{{ r.backend }}</span>
            </td>
            <td class="num">{{ fmtMb(r.modelBytes) }}</td>
            <td class="num">{{ fmtMs(r.loadMs) }}</td>
            <td class="num">{{ Math.round(r.embedThroughputCps) }} 字/s</td>
            <td class="num">{{ fmtMs(r.writeMs) }}</td>
            <td class="num">{{ fmtMs(r.refreshMs) }}</td>
            <td class="num">{{ fmtMs(r.queryEmbedMsP50) }}</td>
            <td class="num">{{ fmtMs(r.searchMsP50) }}</td>
            <td class="num">{{ fmtMs(r.e2eMsP50) }}</td>
            <td class="num">{{ fmtPct(r.recall5) }}</td>
            <td class="num">{{ fmtPct(r.ndcg5) }}</td>
            <td class="num">{{ r.mrr.toFixed(3) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <template v-if="latest">
      <h3>
        最近一次明细
        <button class="btn sm ghost" style="float: right" @click="showDetail = !showDetail">
          {{ showDetail ? '收起' : '展开' }}
        </button>
      </h3>
      <div class="stats">
        <div class="stat"><div class="k">文档 / 分块</div><div class="v">{{ latest.docs }} / {{ latest.chunks }}</div></div>
        <div class="stat"><div class="k">语料字符</div><div class="v">{{ latest.corpusChars }}</div></div>
        <div class="stat"><div class="k">首次查询</div><div class="v">{{ fmtMs(latest.firstQueryMs) }}</div></div>
        <div class="stat"><div class="k">写入+刷新往返</div><div class="v">{{ fmtMs(latest.writeRoundTripMs) }}</div></div>
      </div>

      <div v-if="showDetail" class="scroll-x" style="margin-top: 10px">
        <table class="grid">
          <thead>
            <tr><th>#</th><th>查询</th><th>命中</th><th>Recall</th><th>nDCG</th><th>MRR</th><th>查询向量化</th><th>seekdb</th><th>端到端</th></tr>
          </thead>
          <tbody>
            <tr v-for="(q, i) in latest.queries" :key="i">
              <td class="num">{{ i + 1 }}</td>
              <td style="max-width: 320px; white-space: normal">{{ q.query }}</td>
              <td class="num">{{ q.hits.slice(0, 3).join(', ') || '—' }}</td>
              <td class="num" :class="{ dim: q.recall === 0 }">{{ q.recall.toFixed(2) }}</td>
              <td class="num">{{ q.ndcg.toFixed(2) }}</td>
              <td class="num">{{ q.mrr.toFixed(2) }}</td>
              <td class="num">{{ fmtMs(q.queryEmbedMs) }}</td>
              <td class="num">{{ fmtMs(q.searchMs) }}</td>
              <td class="num">{{ fmtMs(q.e2eMs) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <div v-else-if="!store.bench.running" class="empty">还没有评测结果</div>
  </section>
</template>
