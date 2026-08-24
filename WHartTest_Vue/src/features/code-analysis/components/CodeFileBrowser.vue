<template>
  <div class="code-file-browser">
    <!-- Left panel: file list -->
    <div class="file-list-panel">
      <div class="list-toolbar">
        <a-input-search
          v-model="searchQuery"
          :placeholder="tl('搜索文件...')"
          size="small"
          allow-clear
          @search="handleSearch"
          @clear="handleSearch"
        />
      </div>
      <a-spin :loading="store.filesLoading" class="list-spin">
        <div v-if="store.codeFiles.length === 0 && !store.filesLoading" class="list-empty">
          <a-empty :description="tl('暂无文件')" />
        </div>
        <div v-else class="file-list">
          <div
            v-for="file in filteredFiles"
            :key="file.id"
            :class="['file-item', { active: selectedFileId === file.id }]"
            @click="selectFile(file)"
          >
            <icon-file class="file-icon" />
            <div class="file-info">
              <span class="file-path" :title="file.path">{{ basename(file.path) }}</span>
              <span class="file-meta">
                <span class="lang-tag">{{ file.language || 'text' }}</span>
                <span class="file-size">{{ formatSize(file.size) }}</span>
              </span>
            </div>
          </div>
        </div>
      </a-spin>
    </div>

    <!-- Right panel: file content -->
    <div class="file-content-panel">
      <template v-if="selectedFileId && fileContent !== null">
        <div class="content-header">
          <span class="content-path">{{ currentFilePath }}</span>
          <a-tag size="small">{{ currentLanguage }}</a-tag>
        </div>
        <div class="editor-wrap">
          <MonacoEditor
            :value="fileContent"
            :language="monacoLanguage"
            :theme="editorTheme"
            :options="editorOptions"
            class="code-editor"
          />
        </div>
      </template>
      <template v-else-if="contentLoading">
        <div class="content-loading">
          <a-spin :tip="tl('加载文件内容...')" />
        </div>
      </template>
      <template v-else>
        <div class="content-placeholder">
          <a-empty :description="tl('选择左侧文件查看内容')" />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import MonacoEditor from '@guolao/vue-monaco-editor';
import { IconFile } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useThemeStore } from '@/store/themeStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { CodeFile } from '../services/codeAnalysisService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const themeStore = useThemeStore();
const store = useCodeAnalysisStore();

const searchQuery = ref('');
const selectedFileId = ref<number | null>(null);
const fileContent = ref<string | null>(null);
const currentFilePath = ref('');
const currentLanguage = ref('');
const contentLoading = ref(false);

const editorTheme = computed(() => (themeStore.isBlack ? 'vs-dark' : 'vs'));
const editorOptions = {
  minimap: { enabled: true },
  readOnly: true,
  scrollBeyondLastLine: false,
  fontSize: 13,
  tabSize: 4,
  renderLineHighlight: 'all' as const,
  roundedSelection: false,
  lineNumbers: 'on' as const,
  wordWrap: 'on' as const,
};

const monacoLanguage = computed(() => {
  const lang = currentLanguage.value.toLowerCase();
  const map: Record<string, string> = {
    javascript: 'javascript',
    typescript: 'typescript',
    python: 'python',
    java: 'java',
    go: 'go',
    rust: 'rust',
    cpp: 'cpp',
    c: 'c',
    css: 'css',
    html: 'html',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    xml: 'xml',
    sql: 'sql',
    shell: 'shell',
    bash: 'shell',
    markdown: 'markdown',
    vue: 'html',
    tsx: 'typescript',
    jsx: 'javascript',
  };
  return map[lang] || 'plaintext';
});

const filteredFiles = computed(() => {
  if (!searchQuery.value) return store.codeFiles;
  const q = searchQuery.value.toLowerCase();
  return store.codeFiles.filter((f) => f.path.toLowerCase().includes(q));
});

function basename(p: string): string {
  return p.split('/').pop() || p;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function handleSearch() {
  // filter is computed, no action needed
}

async function selectFile(file: CodeFile) {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;

  selectedFileId.value = file.id;
  currentFilePath.value = file.path;
  currentLanguage.value = file.language;
  contentLoading.value = true;
  fileContent.value = null;

  try {
    const res = await store.loadFileContent(pid, cpId, file.id);
    fileContent.value = res.content;
  } catch (e) {
    fileContent.value = `// Failed to load: ${file.path}`;
  } finally {
    contentLoading.value = false;
  }
}

// When selected project changes, reset
watch(() => store.selectedProjectId, () => {
  selectedFileId.value = null;
  fileContent.value = null;
});
</script>

<style scoped>
.code-file-browser {
  display: flex;
  height: 100%;
  gap: 0;
  border: 1px solid var(--theme-border);
  border-radius: 8px;
  overflow: hidden;
}

.file-list-panel {
  width: 260px;
  min-width: 200px;
  border-right: 1px solid var(--theme-border);
  display: flex;
  flex-direction: column;
  background: var(--theme-surface-soft);
}

.list-toolbar {
  padding: 8px;
  border-bottom: 1px solid var(--theme-border);
}

.list-spin {
  flex: 1;
  overflow-y: auto;
}

.list-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
}

.file-list {
  display: flex;
  flex-direction: column;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid var(--theme-border);
}

.file-item:hover {
  background: rgba(var(--theme-accent-rgb), 0.06);
}

.file-item.active {
  background: rgba(var(--theme-accent-rgb), 0.1);
}

.file-icon {
  font-size: 16px;
  color: var(--theme-text-tertiary);
  flex-shrink: 0;
}

.file-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.file-path {
  font-size: 13px;
  color: var(--theme-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 2px;
}

.lang-tag {
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--theme-accent);
  color: #fff;
  text-transform: uppercase;
  line-height: 16px;
}

.file-size {
  font-size: 11px;
  color: var(--theme-text-tertiary);
}

.file-content-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--theme-card-bg, #fff);
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--theme-border);
}

.content-path {
  font-size: 13px;
  color: var(--theme-text-secondary);
  font-family: monospace;
}

.editor-wrap {
  flex: 1;
  min-height: 0;
}

.code-editor {
  width: 100%;
  height: 100%;
}

.content-loading,
.content-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
