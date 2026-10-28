<script setup lang="ts">
import { computed } from 'vue';
import { useAppStore } from '../stores/app';
import { fmtMb } from '../lib/format';

const store = useAppStore();

const backend = computed<'webgpu' | 'wasm' | null>(() => {
  if (store.engine.info) return store.engine.info.backend;
  if (store.engine.gpu) return store.engine.gpu.available ? 'webgpu' : 'wasm';
  return null;
});
const backendLabel = computed(() =>
  backend.value === 'webgpu' ? 'WebGPU' : backend.value === 'wasm' ? 'WASM' : '检测中'
);
const precisionLabel = computed(() => {
  const p = store.settings.precision;
  return p === 'int8' ? 'INT8 (q8)' : p.toUpperCase();
});
const modelBytes = computed(() => store.engine.measuredBytes ?? store.model.bytes[store.settings.precision]);
</script>

<template>
  <header class="header">
    <div class="brand">
      <h1>端侧向量化 · seekdb 混合检索</h1>
      <span class="sub">迷你知识库 / 浏览器本地推理 / 向量 + 全文 RRF 融合</span>
    </div>

    <div class="badges">
      <span v-if="store.server.status === 'online'" class="badge accent">
        <i class="dot" /> seekdb 嵌入式 v{{ store.server.info?.version }}
      </span>
      <span v-else-if="store.server.status === 'connecting'" class="badge">
        <i class="dot" /> 连接 seekdb…
      </span>
      <span v-else class="badge danger" :title="store.server.error"><i class="dot" /> seekdb 离线</span>

      <span class="badge" :class="backend === 'webgpu' ? 'accent' : 'warn'" :title="store.engine.info?.note ?? store.engine.gpu?.reason">
        <i class="dot" /> 后端 <b>{{ backendLabel }}</b>
      </span>

      <span class="badge">精度 <b>{{ precisionLabel }}</b></span>
      <span class="badge">模型 <b>{{ store.model.id.split('/')[1] }}</b></span>
      <span class="badge">体积 <b>{{ fmtMb(modelBytes) }}</b></span>
    </div>
  </header>
</template>
