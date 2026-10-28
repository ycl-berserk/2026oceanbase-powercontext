<script setup lang="ts">
import { computed } from 'vue';
import { useAppStore } from '../stores/app';
import { MODELS } from '../lib/embedder';
import { fmtMb, fmtMs } from '../lib/format';
import type { Precision } from '../lib/types';

const store = useAppStore();

const precisionOptions: { id: Precision; label: string; note: string }[] = [
  { id: 'fp32', label: 'FP32', note: '基线（未量化）' },
  { id: 'fp16', label: 'FP16', note: '半精度' },
  { id: 'int8', label: 'INT8', note: 'q8 动态量化' },
];

const info = computed(() => store.engine.info);
const sizeOf = (p: Precision) => fmtMb(store.model.bytes[p]);

const dirty = computed(() => {
  const i = info.value;
  if (!i) return false;
  return i.modelId !== store.settings.modelId || i.precision !== store.settings.precision || (store.settings.forceWasm && i.backend === 'webgpu');
});

function choosePrecision(p: Precision) {
  store.settings.precision = p;
  store.saveSettings();
}
</script>

<template>
  <section class="card">
    <h2>端侧模型 <span class="hint">Transformers.js · ONNX Runtime Web</span></h2>

    <div class="field">
      <label>模型</label>
      <select v-model="store.settings.modelId" :disabled="store.engine.status === 'loading'" @change="store.saveSettings()">
        <option v-for="m in MODELS" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </div>

    <div class="field">
      <label>精度 <span class="dim">量化方案</span></label>
      <div class="row" style="gap: 6px">
        <button
          v-for="p in precisionOptions"
          :key="p.id"
          class="btn sm"
          :class="{ primary: store.settings.precision === p.id }"
          :title="p.note"
          :disabled="store.engine.status === 'loading'"
          @click="choosePrecision(p.id)"
        >
          {{ p.label }}
        </button>
      </div>
      <div class="tiny dim">
        {{ precisionOptions.find((p) => p.id === store.settings.precision)?.note }} · 权重约
        {{ sizeOf(store.settings.precision) }}
      </div>
    </div>

    <label class="row small muted" style="margin-bottom: 10px">
      <input v-model="store.settings.forceWasm" type="checkbox" @change="store.saveSettings()" />
      强制使用 WASM（验证降级路径）
    </label>

    <button class="btn primary" style="width: 100%" :disabled="store.engine.status === 'loading'" @click="store.loadModel()">
      {{ store.engine.status === 'loading' ? '加载中…' : dirty ? '重新加载模型' : '加载模型' }}
    </button>

    <div v-if="store.engine.status === 'loading'" style="margin-top: 10px">
      <div class="progress"><span :style="{ width: `${Math.round(store.engine.progress * 100)}%` }" /></div>
      <div class="tiny dim" style="margin-top: 4px">
        {{ store.engine.phase === 'init' ? '初始化推理后端…' : `${store.engine.file || '下载模型'} · ${Math.round(store.engine.progress * 100)}%` }}
      </div>
    </div>

    <div v-if="store.engine.error" class="notice error" style="margin-top: 10px">{{ store.engine.error }}</div>

    <div v-if="info" style="margin-top: 10px">
      <div class="stats">
        <div class="stat">
          <div class="k">推理后端</div>
          <div class="v" :style="{ color: info.backend === 'webgpu' ? 'var(--accent)' : 'var(--warn)' }">
            {{ info.backend === 'webgpu' ? 'WebGPU' : 'WASM' }}
          </div>
        </div>
        <div class="stat">
          <div class="k">dtype</div>
          <div class="v">{{ info.dtype }}</div>
        </div>
        <div class="stat">
          <div class="k">加载耗时</div>
          <div class="v">{{ fmtMs(info.loadMs) }}</div>
        </div>
        <div class="stat">
          <div class="k">模型体积</div>
          <div class="v">{{ fmtMb(store.engine.measuredBytes ?? info.downloadBytes) }}</div>
        </div>
      </div>
      <div v-if="info.adapter" class="tiny dim" style="margin-top: 6px">GPU：{{ info.adapter }}</div>
      <div v-if="info.note" class="notice warn" style="margin-top: 8px">{{ info.note }}</div>
      <div v-if="dirty" class="notice warn" style="margin-top: 8px">配置已变更，点击「重新加载模型」后生效。</div>
    </div>

    <div v-else-if="store.engine.gpu" class="tiny dim" style="margin-top: 8px">
      {{ store.engine.gpu.available ? `WebGPU 可用：${store.engine.gpu.adapter}` : store.engine.gpu.reason }}
    </div>
  </section>
</template>
