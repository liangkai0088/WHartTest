<template>
  <div class="code-project-panel">
    <!-- Actions bar -->
    <div class="panel-actions">
      <a-button type="primary" size="small" @click="showCreateModal = true">
        <template #icon><icon-plus /></template>
        {{ tl('新建项目') }}
      </a-button>
      <a-button size="small" @click="refresh">
        <template #icon><icon-refresh /></template>
      </a-button>
    </div>

    <!-- Project cards -->
    <a-spin :loading="store.loading" :tip="tl('加载中...')" class="panel-spin">
      <div v-if="store.codeProjects.length === 0 && !store.loading" class="empty-state">
        <a-empty :description="tl('暂无代码项目，请新建一个')" />
      </div>

      <div v-else class="project-grid">
        <div
          v-for="proj in store.codeProjects"
          :key="proj.id"
          :class="['project-card', { selected: store.selectedProjectId === proj.id }]"
          @click="selectProject(proj)"
        >
          <div class="card-header">
            <span class="project-name">{{ proj.name }}</span>
            <a-tag size="small" color="arcoblue">{{ proj.source_type || 'source' }}</a-tag>
          </div>
          <div class="card-meta">
            <span class="meta-item">
              <icon-file class="meta-icon" />
              {{ proj.current_snapshot_file_count ?? 0 }} {{ tl('文件') }}
            </span>
            <span class="meta-item" v-if="proj.current_snapshot_version">
              <icon-history class="meta-icon" />
              v{{ proj.current_snapshot_version }}
            </span>
            <a-badge
              v-if="store.selectedProjectId === proj.id && store.outdatedLinksCount > 0"
              :count="store.outdatedLinksCount"
              :dot-style="{ boxShadow: '0 0 0 1px var(--theme-card-bg)' }"
              class="outdated-badge"
            />
          </div>

          <!-- Card action row -->
          <div class="card-actions">
            <a-button
              size="mini"
              :loading="analyzingId === proj.id"
              @click.stop="handleAnalyze(proj)"
            >
              <template #icon><icon-swap /></template>
              {{ tl('分析变更') }}
            </a-button>
          </div>

          <!-- Upload zone -->
          <div
            :class="['upload-zone', { dragging: dragOverId === proj.id }]"
            @dragover.prevent="dragOverId = proj.id"
            @dragleave="dragOverId = null"
            @drop.prevent="handleDrop($event, proj)"
            @click.stop="triggerFileInput(proj)"
          >
            <template v-if="store.uploading && uploadingForId === proj.id">
              <a-progress :percent="store.uploadProgress / 100" :stroke-width="4" size="small" />
              <span class="upload-text">{{ tl('上传中...') }}</span>
            </template>
            <template v-else>
              <icon-upload class="upload-icon" />
              <span class="upload-text">{{ tl('拖拽或点击上传 zip 源码包') }}</span>
            </template>
          </div>
        </div>
      </div>
    </a-spin>

    <!-- Hidden file input -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".zip"
      style="display: none"
      @change="handleFileChange"
    />

    <!-- Create project modal -->
    <a-modal
      v-model:visible="showCreateModal"
      :title="tl('新建代码项目')"
      :ok-text="tl('创建')"
      :cancel-text="tl('取消')"
      @ok="handleCreate"
      :ok-loading="creating"
    >
      <a-form layout="vertical">
        <a-form-item :label="tl('项目名称')">
          <a-input v-model="newName" :placeholder="tl('请输入项目名称')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconPlus, IconRefresh, IconUpload, IconFile, IconHistory, IconSwap } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { CodeProject } from '../services/codeAnalysisService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const showCreateModal = ref(false);
const newName = ref('');
const creating = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const dragOverId = ref<number | null>(null);
const uploadingForId = ref<number | null>(null);
const uploadTargetProject = ref<CodeProject | null>(null);
const analyzingId = ref<number | null>(null);

function selectProject(proj: CodeProject) {
  store.selectedProjectId = proj.id;
}

async function refresh() {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  await store.loadProjects(pid);
}

async function handleCreate() {
  if (!newName.value.trim()) {
    Message.warning(tl('请输入项目名称'));
    return;
  }
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  creating.value = true;
  try {
    await store.createProject(pid, newName.value.trim());
    Message.success(tl('创建成功'));
    showCreateModal.value = false;
    newName.value = '';
  } catch (e: any) {
    Message.error(e.message || tl('创建失败'));
  } finally {
    creating.value = false;
  }
}

function triggerFileInput(proj: CodeProject) {
  uploadTargetProject.value = proj;
  fileInputRef.value?.click();
}

async function handleFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || !uploadTargetProject.value) return;
  await doUpload(uploadTargetProject.value, file);
  input.value = '';
}

async function handleDrop(e: DragEvent, proj: CodeProject) {
  dragOverId.value = null;
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  if (!file.name.endsWith('.zip')) {
    Message.warning(tl('请上传 .zip 格式的源码包'));
    return;
  }
  await doUpload(proj, file);
}

async function doUpload(proj: CodeProject, file: File) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  uploadingForId.value = proj.id;
  try {
    await store.uploadZip(pid, proj.id, file);
    Message.success(tl('上传成功，已自动检测代码变更'));
  } catch (e: any) {
    Message.error(e.message || tl('上传失败'));
  } finally {
    uploadingForId.value = null;
  }
}

async function handleAnalyze(proj: CodeProject) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  analyzingId.value = proj.id;
  try {
    const summary = await store.analyzeChanges(pid, proj.id);
    Message.success(
      `${tl('变更分析完成')}: +${summary.added} ~${summary.modified} -${summary.deleted}, ${summary.impacted_links} ${tl('影响链接')}`,
    );
  } catch (e: any) {
    Message.error(e.message || tl('分析失败'));
  } finally {
    analyzingId.value = null;
  }
}
</script>

<style scoped>
.code-project-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
}

.panel-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.panel-spin {
  flex: 1;
}

:deep(.arco-spin-children) {
  height: 100%;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.project-card {
  background: var(--theme-card-bg, #fff);
  border: 1px solid var(--theme-border);
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
}

.project-card:hover {
  border-color: var(--theme-accent);
  box-shadow: 0 2px 12px rgba(var(--theme-accent-rgb), 0.1);
}

.project-card.selected {
  border-color: var(--theme-accent);
  box-shadow: 0 0 0 2px rgba(var(--theme-accent-rgb), 0.15);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.project-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--theme-text);
}

.card-meta {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.meta-icon {
  font-size: 14px;
}

.upload-zone {
  border: 1px dashed var(--theme-border);
  border-radius: 6px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-zone:hover,
.upload-zone.dragging {
  border-color: var(--theme-accent);
  background: rgba(var(--theme-accent-rgb), 0.04);
}

.upload-icon {
  font-size: 24px;
  color: var(--theme-text-tertiary);
}

.upload-text {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.card-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.outdated-badge {
  margin-left: auto;
}
</style>
