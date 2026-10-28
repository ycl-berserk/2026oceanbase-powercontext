<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useAppStore } from '../stores/app';
import { api } from '../lib/api';
import { fmtInt, fmtMs } from '../lib/format';

const store = useAppStore();
const creating = ref(false);
const form = reactive({ label: '', name: '' });
const busy = ref('');
const message = ref('');

const totalChunks = computed(() => store.kbs.reduce((sum, k) => sum + k.chunks, 0));

function slug(text: string) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32);
}

function onLabel() {
  if (!form.name || form.name === slug(form.label.slice(0, -1))) form.name = slug(form.label);
}

async function create() {
  const name = form.name || slug(form.label);
  if (!store.engine.info) {
    message.value = '请先加载模型（用于确定向量维度）';
    return;
  }
  busy.value = 'create';
  message.value = '';
  try {
    await api.createKb({
      name,
      label: form.label || name,
      model: store.settings.modelId,
      dimension: store.engine.info.dimension,
    });
    await store.refreshKbs();
    store.activeKb = name;
    form.label = '';
    form.name = '';
    creating.value = false;
  } catch (err) {
    message.value = (err as Error).message;
  } finally {
    busy.value = '';
  }
}

async function remove(name: string) {
  if (!confirm(`删除知识库 ${name}？其中的向量与原文会一并删除。`)) return;
  busy.value = name;
  message.value = '';
  try {
    await api.deleteKb(name);
    if (store.activeKb === name) store.activeKb = '';
    await store.refreshKbs();
  } catch (err) {
    message.value = (err as Error).message;
  } finally {
    busy.value = '';
  }
}

async function refreshIndex(name: string) {
  busy.value = name;
  message.value = '';
  try {
    const res = await api.refresh(name);
    message.value = `索引刷新完成：${fmtMs(res.refreshMs)}，共 ${fmtInt(res.total)} 个分块`;
    await store.refreshKbs();
  } catch (err) {
    message.value = (err as Error).message;
  } finally {
    busy.value = '';
  }
}
</script>

<template>
  <section class="card">
    <h2>
      知识库
      <span class="hint">{{ store.kbs.length }} 个 · {{ fmtInt(totalChunks) }} 块</span>
    </h2>

    <div class="list">
      <div
        v-for="kb in store.kbs.filter((k) => !k.name.startsWith('bench-'))"
        :key="kb.name"
        class="item"
        :class="{ active: kb.name === store.activeKb }"
        @click="store.activeKb = kb.name"
      >
        <div style="min-width: 0">
          <div class="title">{{ kb.label }}</div>
          <div class="meta">{{ kb.dimension }}d · {{ fmtInt(kb.chunks) }} 块</div>
        </div>
        <div class="row" style="gap: 4px">
          <button class="btn sm ghost" :disabled="busy === kb.name" title="刷新向量索引" @click.stop="refreshIndex(kb.name)">⟳</button>
          <button class="btn sm danger" :disabled="busy === kb.name" title="删除" @click.stop="remove(kb.name)">×</button>
        </div>
      </div>
      <div v-if="!store.kbs.filter((k) => !k.name.startsWith('bench-')).length" class="empty">
        还没有知识库，导入文档时会自动创建
      </div>
    </div>

    <button v-if="!creating" class="btn ghost sm" style="width: 100%; margin-top: 8px" @click="creating = true">
      + 新建知识库
    </button>

    <div v-else style="margin-top: 10px">
      <div class="field">
        <label>显示名称</label>
        <input v-model="form.label" placeholder="例如：seekdb 资料库" @input="onLabel" />
      </div>
      <div class="field">
        <label>集合名 <span class="dim">小写字母/数字/-/_</span></label>
        <input v-model="form.name" placeholder="seekdb-docs" />
      </div>
      <div class="row">
        <button class="btn primary sm grow" :disabled="busy === 'create'" @click="create">创建</button>
        <button class="btn ghost sm" @click="creating = false">取消</button>
      </div>
    </div>

    <div v-if="message" class="notice tiny" style="margin-top: 10px">{{ message }}</div>

    <div v-if="store.activeKbInfo" class="tiny dim" style="margin-top: 10px">
      当前集合 <span class="tag">{{ store.activeKbInfo.collection }}</span>
      · ik 全文索引 + HNSW 向量索引
    </div>
  </section>
</template>
