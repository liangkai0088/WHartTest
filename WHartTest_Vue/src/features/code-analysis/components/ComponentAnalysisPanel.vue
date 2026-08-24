<template>
  <div class="component-analysis-panel">
    <!-- Controls -->
    <div class="controls-section">
      <a-space>
        <a-select
          v-model="selectedSnapshotId"
          :placeholder="tl('选择快照')"
          size="small"
          style="width: 160px"
          allow-clear
        >
          <a-option :value="undefined">{{ tl('最新快照') }}</a-option>
        </a-select>
        <a-input
          v-model="fileFilter"
          :placeholder="tl('文件过滤 (可选)')"
          size="small"
          style="width: 180px"
          allow-clear
        />
        <a-button
          type="primary"
          size="small"
          :loading="store.componentLoading"
          @click="handleRun"
        >
          <template #icon><icon-thunderbolt /></template>
          {{ tl('运行分析') }}
        </a-button>
      </a-space>
    </div>

    <!-- Task list -->
    <div class="task-section">
      <div class="section-header">
        <span class="section-title">{{ tl('分析任务') }}</span>
      </div>
      <div v-if="store.componentTasks.length === 0" class="mini-empty">
        <span class="empty-text">{{ tl('暂无分析任务，点击上方按钮开始') }}</span>
      </div>
      <div v-else class="task-list">
        <div
          v-for="task in store.componentTasks"
          :key="task.id"
          :class="['task-item', { active: store.currentComponentTaskId === task.id }]"
          @click="selectTask(task)"
        >
          <span class="task-name">Task #{{ task.id }}</span>
          <a-tag :color="statusColor(task.status)" size="small">
            {{ statusLabel(task.status) }}
          </a-tag>
          <span class="task-count" v-if="task.suggestion_count != null">
            {{ task.suggestion_count }} {{ tl('条建议') }}
          </span>
        </div>
      </div>
    </div>

    <!-- Warnings -->
    <div v-if="currentTask?.warnings?.length" class="warnings-section">
      <a-alert
        v-for="(w, i) in currentTask.warnings"
        :key="i"
        type="warning"
        :title="w"
        size="small"
      />
    </div>

    <!-- Element suggestions grouped by page -->
    <div v-if="store.currentComponentTaskId" class="suggestions-section">
      <div class="section-header">
        <span class="section-title">{{ tl('元素建议列表') }}</span>
        <a-space>
          <a-button
            size="small"
            type="primary"
            :disabled="selectedIds.length === 0"
            :loading="approving"
            @click="handleApprove"
          >
            {{ tl('通过选中') }} ({{ selectedIds.length }})
          </a-button>
          <a-button
            size="small"
            status="danger"
            :disabled="selectedIds.length === 0"
            :loading="rejecting"
            @click="handleReject"
          >
            {{ tl('拒绝选中') }}
          </a-button>
        </a-space>
      </div>

      <a-spin :loading="store.componentLoading">
        <div v-if="groupedSuggestions.length === 0" class="mini-empty">
          <a-empty :description="tl('暂无元素建议')" />
        </div>
        <a-collapse v-else :bordered="false" class="page-collapse">
          <a-collapse-item
            v-for="group in groupedSuggestions"
            :key="group.page"
            :header="`${group.page} (${group.items.length})`"
          >
            <a-table
              :data="group.items"
              :pagination="false"
              size="small"
              :row-key="(r: any) => r.id"
              :bordered="false"
            >
              <template #columns>
                <a-table-column :width="40">
                  <template #cell="{ record }">
                    <a-checkbox
                      :model-value="selectedIds.includes(record.id)"
                      @change="(val: boolean) => toggleSelect(record.id, val)"
                    />
                  </template>
                </a-table-column>
                <a-table-column :title="tl('元素名称')" :width="160">
                  <template #cell="{ record }">
                    {{ record.payload?.element_name }}
                  </template>
                </a-table-column>
                <a-table-column :title="tl('文件路径')" :width="200">
                  <template #cell="{ record }">
                    <span class="file-path-cell">{{ record.payload?.file_path }}</span>
                  </template>
                </a-table-column>
                <a-table-column :title="tl('主定位')">
                  <template #cell="{ record }">
                    <template v-if="record.payload?.locator?.primary">
                      <a-tag size="small" color="arcoblue">
                        {{ record.payload.locator.primary.type }}
                      </a-tag>
                      <span class="locator-value">{{ record.payload.locator.primary.value }}</span>
                    </template>
                    <span v-else>-</span>
                  </template>
                </a-table-column>
                <a-table-column :title="tl('备用定位')">
                  <template #cell="{ record }">
                    <template v-if="record.payload?.locator?.backups?.length">
                      <div
                        v-for="(b, i) in record.payload.locator.backups"
                        :key="i"
                        class="backup-locator"
                      >
                        <a-tag size="small">{{ b.type }}</a-tag>
                        <span class="locator-value">{{ b.value }}</span>
                      </div>
                    </template>
                    <span v-else class="no-backup">-</span>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </a-collapse-item>
        </a-collapse>
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconThunderbolt } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { ComponentAnalysisTask } from '../services/codeAnalysisService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const selectedSnapshotId = ref<number | undefined>(undefined);
const fileFilter = ref('');
const selectedIds = ref<number[]>([]);
const approving = ref(false);
const rejecting = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const currentTask = computed(() => store.currentComponentTask);

const groupedSuggestions = computed(() => {
  const map = new Map<string, typeof store.elementSuggestions>();
  for (const sug of store.elementSuggestions) {
    const page = sug.payload?.page_name || '(unknown)';
    if (!map.has(page)) map.set(page, []);
    map.get(page)!.push(sug);
  }
  return Array.from(map.entries()).map(([page, items]) => ({ page, items }));
});

function statusColor(s: string): string {
  switch (s) {
    case 'completed': return 'green';
    case 'running':
    case 'pending': return 'orange';
    case 'failed': return 'red';
    default: return 'gray';
  }
}

function statusLabel(s: string): string {
  switch (s) {
    case 'completed': return tl('已完成');
    case 'running': return tl('运行中');
    case 'pending': return tl('等待中');
    case 'failed': return tl('失败');
    default: return s;
  }
}

function toggleSelect(id: number, val: boolean | (string | number | boolean)[]) {
  if (val) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id);
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
}

async function selectTask(task: ComponentAnalysisTask) {
  store.currentComponentTaskId = task.id;
  selectedIds.value = [];
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  await store.loadElementSuggestions(pid, task.id, 'pending');
  startPolling(task.id);
}

function startPolling(taskId: number) {
  stopPolling();
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  pollTimer = setInterval(async () => {
    const task = await store.refreshComponentTask(pid, taskId);
    if (task && task.status !== 'pending' && task.status !== 'running') {
      stopPolling();
      await store.loadElementSuggestions(pid, taskId, 'pending');
    }
  }, 3000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function handleRun() {
  const pid = projectStore.currentProjectId;
  if (!pid) {
    Message.warning(tl('请先选择项目'));
    return;
  }
  try {
    const params: { snapshot_id?: number; file_filter?: string } = {};
    if (selectedSnapshotId.value) params.snapshot_id = selectedSnapshotId.value;
    if (fileFilter.value.trim()) params.file_filter = fileFilter.value.trim();
    const task = await store.runComponentAnalysis(pid, params);
    Message.success(tl('分析任务已创建'));
    startPolling(task.id);
  } catch (e: any) {
    Message.error(e.message || tl('分析失败'));
  }
}

async function handleApprove() {
  const pid = projectStore.currentProjectId;
  const tid = store.currentComponentTaskId;
  if (!pid || !tid) return;
  approving.value = true;
  try {
    const results = await store.approveElementSuggestions(pid, tid, selectedIds.value);
    const okCount = results.filter((r) => r.success).length;
    Message.success(`${tl('通过')}: ${okCount}`);
    selectedIds.value = [];
  } catch (e: any) {
    Message.error(e.message || tl('操作失败'));
  } finally {
    approving.value = false;
  }
}

async function handleReject() {
  const pid = projectStore.currentProjectId;
  const tid = store.currentComponentTaskId;
  if (!pid || !tid) return;
  rejecting.value = true;
  try {
    await store.rejectElementSuggestions(pid, tid, selectedIds.value);
    Message.success(tl('已拒绝'));
    selectedIds.value = [];
  } catch (e: any) {
    Message.error(e.message || tl('操作失败'));
  } finally {
    rejecting.value = false;
  }
}

watch(() => projectStore.currentProjectId, () => {
  stopPolling();
  selectedIds.value = [];
});

onUnmounted(() => {
  stopPolling();
});
</script>

<style scoped>
.component-analysis-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.controls-section {
  padding: 12px 16px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
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

.mini-empty {
  padding: 24px;
  text-align: center;
}

.empty-text {
  font-size: 13px;
  color: var(--theme-text-tertiary);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 140px;
  overflow-y: auto;
}

.task-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.task-item:hover {
  background: var(--theme-surface-soft);
}

.task-item.active {
  background: rgba(var(--theme-accent-rgb), 0.08);
}

.task-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--theme-text);
  flex: 1;
}

.task-count {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.warnings-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggestions-section {
  flex: 1;
  min-height: 0;
}

.page-collapse {
  margin-bottom: 8px;
}

.file-path-cell {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.locator-value {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text);
  margin-left: 4px;
}

.backup-locator {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-bottom: 2px;
}

.no-backup {
  color: var(--theme-text-tertiary);
  font-size: 12px;
}
</style>
