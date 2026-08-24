<template>
  <div class="prd-generate-panel">
    <div class="panel-description">
      <icon-robot class="desc-icon" />
      <span>{{ tl('从 PRD 需求文档自动生成 YAML 测试用例，支持选择已有文档或直接粘贴文本。') }}</span>
    </div>

    <!-- Input section -->
    <div class="input-section">
      <a-radio-group v-model="inputMode" type="button" size="small" style="margin-bottom: 12px">
        <a-radio value="doc">
          <template #default>{{ tl('选择需求文档') }}</template>
        </a-radio>
        <a-radio value="text">
          <template #default>{{ tl('粘贴文本') }}</template>
        </a-radio>
      </a-radio-group>

      <!-- Doc select mode -->
      <div v-if="inputMode === 'doc'" class="doc-mode">
        <a-select
          v-model="selectedDocId"
          :placeholder="tl('选择需求文档')"
          style="width: 320px"
          allow-search
          :loading="docsLoading"
        >
          <a-option v-for="doc in documents" :key="doc.id" :value="doc.id" :label="doc.title" />
        </a-select>
        <div v-if="documents.length === 0 && !docsLoading" class="doc-hint">
          {{ tl('暂无需求文档，请先在需求管理中上传。') }}
        </div>
      </div>

      <!-- Text mode -->
      <div v-else class="text-mode">
        <a-textarea
          v-model="inputText"
          :placeholder="tl('粘贴 PRD 内容或需求描述...')"
          :auto-size="{ minRows: 6, maxRows: 14 }"
        />
      </div>

      <div class="action-bar">
        <a-button
          type="primary"
          :loading="store.prdGenerating"
          :disabled="!canGenerate"
          @click="handleGenerate"
        >
          <template #icon><icon-thunderbolt /></template>
          {{ tl('生成') }}
        </a-button>
        <span v-if="store.prdGenerating" class="gen-hint">
          {{ tl('生成中…') }} <span class="timeout-hint">{{ tl('最长 90 秒') }}</span>
        </span>
      </div>
    </div>

    <!-- Status & preview -->
    <div v-if="generatedSuite" class="preview-section">
      <div class="section-header">
        <span class="section-title">{{ tl('生成结果') }}: {{ generatedSuite.name }}</span>
        <a-space>
          <a-button size="small" @click="openEditor">
            {{ tl('编辑保存') }}
          </a-button>
          <a-button type="primary" size="small" @click="handleRunGenerated" :loading="running">
            {{ tl('直接运行') }}
          </a-button>
        </a-space>
      </div>
      <div class="yaml-preview-wrap">
        <MonacoEditor
          :value="generatedSuite.yaml_content || ''"
          language="yaml"
          :theme="editorTheme"
          :options="previewEditorOptions"
          class="yaml-preview"
        />
      </div>
    </div>

    <!-- YAML Editor Modal (edit before save) -->
    <a-modal
      v-model:visible="showEditorModal"
      :title="tl('编辑生成的 YAML')"
      :ok-loading="saving"
      @ok="handleSaveEdited"
      :width="720"
      :body-style="{ padding: '0' }"
    >
      <div class="yaml-editor-wrap">
        <MonacoEditor
          v-model:value="editedYaml"
          language="yaml"
          :theme="editorTheme"
          :options="editorOptions"
          class="yaml-editor"
        />
      </div>
    </a-modal>

    <!-- Run Detail Drawer -->
    <RunDetailDrawer
      v-model:visible="showRunDrawer"
      :run-id="activeRunId"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconThunderbolt, IconRobot } from '@arco-design/web-vue/es/icon';
import MonacoEditor from '@guolao/vue-monaco-editor';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useThemeStore } from '@/store/themeStore';
import { RequirementDocumentService } from '@/features/requirements/services/requirementService';
import { useWebQaStore } from '../store/webQaStore';
import type { QaSuite } from '../services/webQaService';
import RunDetailDrawer from './RunDetailDrawer.vue';

interface RequirementDoc {
  id: number;
  title: string;
}

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const themeStore = useThemeStore();
const store = useWebQaStore();

const inputMode = ref<'doc' | 'text'>('doc');
const selectedDocId = ref<number | undefined>(undefined);
const inputText = ref('');
const documents = ref<RequirementDoc[]>([]);
const docsLoading = ref(false);
const generatedSuite = ref<QaSuite | null>(null);
const showEditorModal = ref(false);
const editedYaml = ref('');
const saving = ref(false);
const running = ref(false);
const showRunDrawer = ref(false);
const activeRunId = ref<number | null>(null);

const editorTheme = computed(() => (themeStore.isBlack ? 'vs-dark' : 'vs'));
const editorOptions = {
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  fontSize: 13,
  tabSize: 2,
  renderLineHighlight: 'all' as const,
  roundedSelection: false,
  lineNumbers: 'on' as const,
  wordWrap: 'on' as const,
};
const previewEditorOptions = {
  ...editorOptions,
  readOnly: true,
};

const canGenerate = computed(() => {
  if (inputMode.value === 'doc') return !!selectedDocId.value;
  return inputText.value.trim().length > 0;
});

async function loadDocuments() {
  docsLoading.value = true;
  try {
    const res = await RequirementDocumentService.getDocumentList({ project: String(projectStore.currentProjectId) });
    if (res.data) {
      const data = res.data as any;
      const list = Array.isArray(data) ? data : (data.results || []);
      documents.value = list.map((d: any) => ({ id: d.id, title: d.title }));
    }
  } catch (e) {
    console.error('loadDocuments failed', e);
    documents.value = [];
  } finally {
    docsLoading.value = false;
  }
}

async function handleGenerate() {
  const pid = projectStore.currentProjectId;
  if (!pid) {
    Message.warning(tl('请先选择项目'));
    return;
  }
  generatedSuite.value = null;
  try {
    const data: { requirement_document_id?: number; text?: string } = {};
    if (inputMode.value === 'doc') {
      data.requirement_document_id = selectedDocId.value;
    } else {
      data.text = inputText.value.trim();
    }
    await store.prdGenerate(pid, data, (suiteId) => {
      // onComplete callback
      const suite = store.suites.find((s) => s.id === suiteId);
      if (suite) {
        generatedSuite.value = suite;
        Message.success(tl('测试用例生成完成'));
      }
    });
    Message.info(tl('正在生成测试用例，请稍候…'));
  } catch (e: any) {
    Message.error(e.message || tl('生成失败'));
  }
}

function openEditor() {
  if (!generatedSuite.value) return;
  editedYaml.value = generatedSuite.value.yaml_content || '';
  showEditorModal.value = true;
}

async function handleSaveEdited() {
  if (!generatedSuite.value) return;
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  saving.value = true;
  try {
    await store.updateSuiteYaml(pid, generatedSuite.value.id, editedYaml.value);
    generatedSuite.value = { ...generatedSuite.value, yaml_content: editedYaml.value };
    Message.success(tl('YAML 已保存'));
    showEditorModal.value = false;
  } catch (e: any) {
    Message.error(e.message || tl('保存失败'));
  } finally {
    saving.value = false;
  }
}

async function handleRunGenerated() {
  if (!generatedSuite.value) return;
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  running.value = true;
  try {
    const result = await store.runSuite(pid, generatedSuite.value.id);
    Message.success(tl('运行已启动'));
    activeRunId.value = result.run_id;
    showRunDrawer.value = true;
  } catch (e: any) {
    Message.error(e.message || tl('运行失败'));
  } finally {
    running.value = false;
  }
}

onMounted(() => {
  loadDocuments();
});
</script>

<style scoped>
.prd-generate-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-description {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: rgba(var(--theme-accent-rgb), 0.06);
  border-radius: 8px;
  font-size: 13px;
  color: var(--theme-text-secondary);
}

.desc-icon {
  font-size: 18px;
  color: var(--theme-accent);
}

.input-section {
  padding: 14px 16px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.doc-mode,
.text-mode {
  margin-bottom: 12px;
}

.doc-hint {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-top: 6px;
}

.action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.gen-hint {
  font-size: 13px;
  color: var(--theme-accent);
  font-weight: 500;
}

.timeout-hint {
  font-size: 11px;
  color: var(--theme-text-tertiary);
}

.preview-section {
  padding-top: 4px;
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

.yaml-preview-wrap {
  height: 320px;
  border: 1px solid var(--theme-border);
  border-radius: 6px;
  overflow: hidden;
}

.yaml-preview {
  height: 100%;
}

.yaml-editor-wrap {
  height: 420px;
}

.yaml-editor {
  height: 100%;
}
</style>
