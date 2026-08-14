<template>
  <div class="batch-run-panel">
    <!-- Mode switcher -->
    <div class="mode-section">
      <a-radio-group v-model="mode" type="button" size="small">
        <a-radio value="select">
          <template #default>{{ tl('选择套件') }}</template>
        </a-radio>
        <a-radio value="group">
          <template #default>{{ tl('按分组执行') }}</template>
        </a-radio>
      </a-radio-group>
    </div>

    <!-- Select mode: checkbox suite list -->
    <div v-if="mode === 'select'" class="select-section">
      <div class="filter-bar">
        <a-select
          v-model="groupFilter"
          :placeholder="tl('按分组筛选')"
          size="small"
          style="width: 160px"
          allow-clear
        >
          <a-option v-for="g in store.groups" :key="g" :value="g" :label="g" />
        </a-select>
        <span class="selected-count">
          {{ tl('已选择') }} {{ selectedIds.length }} {{ tl('个套件') }}
        </span>
      </div>

      <a-spin :loading="store.suitesLoading">
        <div v-if="filteredSuites.length === 0" class="mini-empty">
          <a-empty :description="tl('暂无可选套件')" />
        </div>
        <div v-else class="suite-list">
          <div
            v-for="suite in filteredSuites"
            :key="suite.id"
            :class="['suite-check-item', { checked: selectedIds.includes(suite.id) }]"
          >
            <a-checkbox
              :model-value="selectedIds.includes(suite.id)"
              @change="(val: boolean) => toggleSelect(suite.id, val)"
            />
            <div class="suite-check-info">
              <span class="suite-check-name">{{ suite.name }}</span>
              <div class="suite-check-meta">
                <a-tag
                  :color="suite.engine === 'midscene' ? 'arcoblue' : 'cyan'"
                  size="small"
                >
                  {{ suite.engine === 'midscene' ? tl('视觉引擎') : tl('语义引擎') }}
                </a-tag>
                <a-tag v-if="suite.group" size="small" color="gray">{{ suite.group }}</a-tag>
                <span class="test-count">{{ suite.test_count }} {{ tl('用例') }}</span>
              </div>
            </div>
          </div>
        </div>
      </a-spin>

      <div class="action-bar">
        <a-button
          type="primary"
          :disabled="selectedIds.length === 0"
          :loading="store.batchLoading"
          @click="handleBatchRun"
        >
          <template #icon><icon-play-arrow /></template>
          {{ tl('批量执行(回归)') }} ({{ selectedIds.length }})
        </a-button>
      </div>
    </div>

    <!-- Group mode -->
    <div v-else class="group-section">
      <a-input
        v-model="groupName"
        :placeholder="tl('输入分组名称')"
        size="small"
        style="width: 240px"
      />
      <a-button
        type="primary"
        :disabled="!groupName.trim()"
        :loading="store.batchLoading"
        @click="handleGroupRun"
        size="small"
      >
        <template #icon><icon-play-arrow /></template>
        {{ tl('批量执行(回归)') }}
      </a-button>
    </div>

    <!-- Batch results -->
    <div v-if="store.batchResult" class="results-section">
      <div class="section-header">
        <span class="section-title">{{ tl('执行结果') }}</span>
        <a-spin v-if="isPolling" :size="14" />
      </div>

      <!-- Summary chips -->
      <div class="summary-chips">
        <div class="chip chip-total">
          <span class="chip-label">{{ tl('总计') }}</span>
          <span class="chip-value">{{ store.batchRuns.length }}</span>
        </div>
        <div class="chip chip-passed">
          <span class="chip-label">{{ tl('通过') }}</span>
          <span class="chip-value">{{ passedCount }}</span>
        </div>
        <div class="chip chip-failed">
          <span class="chip-label">{{ tl('失败') }}</span>
          <span class="chip-value">{{ failedCount }}</span>
        </div>
        <div class="chip chip-running">
          <span class="chip-label">{{ tl('运行中') }}</span>
          <span class="chip-value">{{ runningCount }}</span>
        </div>
      </div>

      <!-- Per-run status chips -->
      <div class="run-chips">
        <div
          v-for="run in store.batchRuns"
          :key="run.id"
          :class="['run-chip', `status-${run.status}`]"
          @click="viewRunDetail(run)"
        >
          <span class="run-chip-suite">{{ getSuiteName(run.suite_id) }}</span>
          <a-tag :color="runStatusColor(run.status)" size="small">
            {{ runStatusLabel(run.status) }}
          </a-tag>
          <span v-if="run.summary" class="run-chip-summary">
            {{ run.summary.passed }}/{{ run.summary.total }}
          </span>
        </div>
      </div>
    </div>

    <!-- Run Detail Drawer -->
    <RunDetailDrawer
      v-model:visible="showRunDrawer"
      :run-id="activeRunId"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconPlayArrow } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useWebQaStore } from '../store/webQaStore';
import type { QaRun } from '../services/webQaService';
import RunDetailDrawer from './RunDetailDrawer.vue';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useWebQaStore();

const mode = ref<'select' | 'group'>('select');
const groupFilter = ref('');
const groupName = ref('');
const selectedIds = ref<number[]>([]);
const showRunDrawer = ref(false);
const activeRunId = ref<number | null>(null);

const filteredSuites = computed(() => {
  if (!groupFilter.value) return store.suites;
  return store.suites.filter((s) => s.group === groupFilter.value);
});

const isPolling = computed(() => {
  return store.batchRuns.some((r) => r.status === 'pending' || r.status === 'running');
});

const passedCount = computed(() =>
  store.batchRuns.filter((r) => r.status === 'passed' || r.status === 'completed').length,
);

const failedCount = computed(() =>
  store.batchRuns.filter((r) => r.status === 'failed' || r.status === 'error').length,
);

const runningCount = computed(() =>
  store.batchRuns.filter((r) => r.status === 'running' || r.status === 'pending').length,
);

function toggleSelect(id: number, val: boolean | (string | number | boolean)[]) {
  if (val) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id);
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
}

function getSuiteName(suiteId: number): string {
  return store.suites.find((s) => s.id === suiteId)?.name || `#${suiteId}`;
}

function runStatusColor(s: string): string {
  switch (s) {
    case 'passed':
    case 'completed': return 'green';
    case 'failed':
    case 'error': return 'red';
    case 'running': return 'arcoblue';
    case 'pending': return 'orange';
    case 'skipped': return 'gray';
    default: return 'gray';
  }
}

function runStatusLabel(s: string): string {
  switch (s) {
    case 'passed': return tl('通过');
    case 'completed': return tl('完成');
    case 'failed': return tl('失败');
    case 'error': return tl('错误');
    case 'running': return tl('运行中');
    case 'pending': return tl('等待中');
    case 'skipped': return tl('跳过');
    default: return s;
  }
}

function viewRunDetail(run: QaRun) {
  activeRunId.value = run.id;
  showRunDrawer.value = true;
}

async function handleBatchRun() {
  const pid = projectStore.currentProjectId;
  if (!pid || selectedIds.value.length === 0) return;
  try {
    await store.batchRun(pid, { suite_ids: selectedIds.value });
    Message.success(tl('批量执行已启动'));
  } catch (e: any) {
    Message.error(e.message || tl('批量执行失败'));
  }
}

async function handleGroupRun() {
  const pid = projectStore.currentProjectId;
  if (!pid || !groupName.value.trim()) return;
  try {
    await store.batchRun(pid, { group: groupName.value.trim() });
    Message.success(tl('批量执行已启动'));
  } catch (e: any) {
    Message.error(e.message || tl('批量执行失败'));
  }
}

onUnmounted(() => {
  store.stopRunPolling();
});
</script>

<style scoped>
.batch-run-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.mode-section {
  padding: 10px 14px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.selected-count {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.suite-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px 0;
}

.suite-check-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 6px;
  transition: background 0.15s;
  cursor: pointer;
}

.suite-check-item:hover {
  background: var(--theme-surface-soft);
}

.suite-check-item.checked {
  background: rgba(var(--theme-accent-rgb), 0.06);
}

.suite-check-info {
  flex: 1;
}

.suite-check-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--theme-text);
}

.suite-check-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.test-count {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.action-bar {
  margin-top: 12px;
}

.group-section {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.mini-empty {
  padding: 24px;
  text-align: center;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.section-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--theme-text);
}

.results-section {
  padding-top: 8px;
}

.summary-chips {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 18px;
  border-radius: 8px;
  min-width: 72px;
}

.chip-label {
  font-size: 11px;
  color: var(--theme-text-tertiary);
  margin-bottom: 4px;
}

.chip-value {
  font-size: 18px;
  font-weight: 700;
}

.chip-total {
  background: var(--theme-surface-soft);
}

.chip-total .chip-value {
  color: var(--theme-text);
}

.chip-passed {
  background: rgba(0, 180, 42, 0.08);
}

.chip-passed .chip-value {
  color: #00b42a;
}

.chip-failed {
  background: rgba(245, 63, 63, 0.08);
}

.chip-failed .chip-value {
  color: #f53f3f;
}

.chip-running {
  background: rgba(var(--theme-accent-rgb), 0.08);
}

.chip-running .chip-value {
  color: var(--theme-accent);
}

.run-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.run-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--theme-surface);
  border: 1px solid var(--theme-border);
  cursor: pointer;
  transition: all 0.15s;
}

.run-chip:hover {
  border-color: var(--theme-accent);
}

.run-chip-suite {
  font-size: 13px;
  font-weight: 500;
  color: var(--theme-text);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-chip-summary {
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-text-secondary);
}
</style>
