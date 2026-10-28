<script setup lang="ts">
import { onMounted, ref } from 'vue';
import AppHeader from './components/AppHeader.vue';
import ModelPanel from './components/ModelPanel.vue';
import KbPanel from './components/KbPanel.vue';
import ImportView from './components/ImportView.vue';
import SearchView from './components/SearchView.vue';
import BenchView from './components/BenchView.vue';
import { useAppStore } from './stores/app';

const store = useAppStore();
const tab = ref<'import' | 'search' | 'bench'>('import');
const tabs = [
  { id: 'import', label: '导入' },
  { id: 'search', label: '检索' },
  { id: 'bench', label: '评测' },
] as const;

onMounted(() => store.init());
</script>

<template>
  <div class="app">
    <AppHeader />

    <div class="layout">
      <aside class="sidebar">
        <ModelPanel />
        <KbPanel />
      </aside>

      <main class="main">
        <div class="tabs">
          <button
            v-for="t in tabs"
            :key="t.id"
            :class="{ active: tab === t.id }"
            @click="tab = t.id"
          >
            {{ t.label }}
          </button>
        </div>

        <div class="view">
          <ImportView v-if="tab === 'import'" @go-search="tab = 'search'" />
          <SearchView v-else-if="tab === 'search'" />
          <BenchView v-else />
        </div>
      </main>
    </div>
  </div>
</template>
