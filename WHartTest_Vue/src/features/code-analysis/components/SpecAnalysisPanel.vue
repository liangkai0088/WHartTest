<template>
  <div class="spec-analysis-panel">
    <!-- Upload / URL section -->
    <div class="spec-input-section">
      <a-space>
        <a-upload
          :auto-upload="false"
          :limit="1"
          accept=".json,.yaml,.yml"
          :show-file-list="false"
          @change="handleSpecFileChange"
        >
          <template #upload-button>
            <a-button type="primary" size="small">
              <template #icon><icon-upload /></template>
              {{ tl('上传规范文件') }}
            </a-button>
          </template>
        </a-upload>
        <span class="or-divider">{{ tl('或') }}</span>
        <a-input
          v-model="specUrl"
          :placeholder="tl('输入 OpenAPI URL')"
          size="small"
          style="width: 260px"
        />
        <a-button
          type="primary"
          size="small"
          :loading="store.specLoading"
          :disabled="!specUrl"
          @click="handleRunByUrl"
        >
          {{ tl('分析') }}
        </a-button>
      </a-space>
    </div>

    <!-- Task list -->
    <div class="task-section">
      <div class="section-header">
        <span class="section-title">{{ tl('分析任务') }}</span>
      </div>
      <div v-if="store.specTasks.length === 0" class="mini-empty">
        <span class="empty-text">{{ tl('暂无分析任务') }}</span>
      </div>
      <div v-else class="task-list">
        <div
          v-for="task in store.specTasks"
          :key="task.id"
          :class="['task-item', { active: store.currentSpecTaskId === task.id }]"
          @click="selectTask(task)"
        >
          <span class="task-name">{{ task.spec_name }}</span>
          <a-tag :color="statusColor(task.status)" size="small">
            {{ statusLabel(task.status) }}
          </a-tag>
          <span class="task-count" v-if="task.suggestion_count != null">
            {{ task.suggestion_count }} {{ tl('条建议') }}
          </span>
        </div>
      </div>
    </div>

    <!-- Suggestions table -->
    <div v-if="store.currentSpecTaskId" class="suggestions-section">
      <div class="section-header">
        <span class="section-title">{{ tl('接口建议列表') }}</span>
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

      <a-spin :loading="store.specLoading">
        <a-table
          :data="store.specSuggestions"
          :pagination="false"
          size="small"
          :row-key="(r: any) => r.id"
          :bordered="false"
          :scroll="{ y: 400 }"
          row-class="suggestion-row"
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
            <a-table-column :title="tl('名称')" data-index="payload.name" :width="160">
              <template #cell="{ record }">
                {{ record.payload?.name }}
              </template>
            </a-table-column>
            <a-table-column :title="tl('方法 + 路径')" :width="200">
              <template #cell="{ record }">
                <a-tag
                  :color="methodColor(record.payload?.method)"
                  size="small"
                  class="method-tag"
                >
                  {{ record.payload?.method }}
                </a-tag>
                <span class="path-text">{{ record.payload?.path }}</span>
              </template>
            </a-table-column>
            <a-table-column :title="tl('优先级')" :width="80">
              <template #cell="{ record }">
                <a-tag :color="priorityColor(record.payload?.priority)" size="small">
                  {{ record.payload?.priority }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="tl('描述')">
              <template #cell="{ record }">
                <a-tooltip :content="record.payload?.description" position="top">
                  <span class="desc-cell">{{ truncate(record.payload?.description, 60) }}</span>
                </a-tooltip>
              </template>
            </a-table-column>
            <a-table-column :title="tl('步骤')" :width="80">
              <template #cell="{ record }">
                <a-collapse v-if="record.payload?.steps?.length" :bordered="false" size="small">
                  <a-collapse-item :header="`${record.payload.steps.length} ${tl('步')}`" key="steps">
                    <ol class="steps-list">
                      <li v-for="(s, i) in record.payload.steps" :key="i">{{ s }}</li>
                    </ol>
                  </a-collapse-item>
                </a-collapse>
                <span v-else class="no-steps">-</span>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconUpload } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { SpecAnalysisTask } from '../services/codeAnalysisService';

type FileItem = { file?: File; [key: string]: any };

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const specUrl = ref('');
const selectedIds = ref<number[]>([]);
const approving = ref(false);
const rejecting = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;

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

function methodColor(m: string): string {
  switch ((m || '').toUpperCase()) {
    case 'GET': return 'arcoblue';
    case 'POST': return 'green';
    case 'PUT': return 'orangered';
    case 'DELETE': return 'red';
    case 'PATCH': return 'purple';
    default: return 'gray';
  }
}

function priorityColor(p: string): string {
  switch ((p || '').toLowerCase()) {
    case 'high': return 'red';
    case 'medium': return 'orange';
    case 'low': return 'green';
    default: return 'gray';
  }
}

function truncate(s: string | undefined, len: number): string {
  if (!s) return '-';
  return s.length > len ? s.slice(0, len) + '...' : s;
}

function toggleSelect(id: number, val: boolean | (string | number | boolean)[]) {
  if (val) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id);
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
}

async function selectTask(task: SpecAnalysisTask) {
  store.currentSpecTaskId = task.id;
  selectedIds.value = [];
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  await store.loadSpecSuggestions(pid, task.id, 'pending');
  startPolling(task.id);
}

function startPolling(taskId: number) {
  stopPolling();
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  pollTimer = setInterval(async () => {
    const task = await store.refreshSpecTask(pid, taskId);
    if (task && task.status !== 'pending' && task.status !== 'running') {
      stopPolling();
      await store.loadSpecSuggestions(pid, taskId, 'pending');
    }
  }, 3000);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function handleSpecFileChange(fileList: FileItem[]) {
  const file = fileList[0]?.file;
  if (!file) return;
  const pid = projectStore.currentProjectId;
  if (!pid) {
    Message.warning(tl('请先选择项目'));
    return;
  }
  try {
    const task = await store.runSpecAnalysis(pid, { file });
    Message.success(tl('分析任务已创建'));
    startPolling(task.id);
  } catch (e: any) {
    Message.error(e.message || tl('分析失败'));
  }
}

async function handleRunByUrl() {
  if (!specUrl.value.trim()) return;
  const pid = projectStore.currentProjectId;
  if (!pid) {
    Message.warning(tl('请先选择项目'));
    return;
  }
  try {
    const task = await store.runSpecAnalysis(pid, { specUrl: specUrl.value.trim() });
    Message.success(tl('分析任务已创建'));
    specUrl.value = '';
    startPolling(task.id);
  } catch (e: any) {
    Message.error(e.message || tl('分析失败'));
  }
}

async function handleApprove() {
  const pid = projectStore.currentProjectId;
  const tid = store.currentSpecTaskId;
  if (!pid || !tid) return;
  approving.value = true;
  try {
    const results = await store.approveSpecSuggestions(pid, tid, selectedIds.value);
    const okCount = results.filter((r) => r.success).length;
    const failCount = results.length - okCount;
    Message.success(`${tl('通过')}: ${okCount}${failCount ? `, ${tl('失败')}: ${failCount}` : ''}`);
    selectedIds.value = [];
  } catch (e: any) {
    Message.error(e.message || tl('操作失败'));
  } finally {
    approving.value = false;
  }
}

async function handleReject() {
  const pid = projectStore.currentProjectId;
  const tid = store.currentSpecTaskId;
  if (!pid || !tid) return;
  rejecting.value = true;
  try {
    await store.rejectSpecSuggestions(pid, tid, selectedIds.value);
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
.spec-analysis-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.spec-input-section {
  padding: 12px 16px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.or-divider {
  color: var(--theme-text-tertiary);
  font-size: 13px;
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
  max-height: 160px;
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-count {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.suggestions-section {
  flex: 1;
  min-height: 0;
}

.method-tag {
  font-family: monospace;
  font-weight: 600;
  margin-right: 6px;
}

.path-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.desc-cell {
  font-size: 12px;
  color: var(--theme-text-secondary);
  cursor: help;
}

.steps-list {
  padding-left: 18px;
  margin: 0;
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.steps-list li {
  margin-bottom: 2px;
}

.no-steps {
  color: var(--theme-text-tertiary);
  font-size: 12px;
}
</style>
