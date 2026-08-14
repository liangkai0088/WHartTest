<template>
  <div class="suite-panel">
    <!-- Toolbar -->
    <div class="panel-toolbar">
      <a-space>
        <a-upload
          :auto-upload="false"
          :limit="1"
          accept=".yaml,.yml"
          :show-file-list="false"
          @change="handleImportFile"
        >
          <template #upload-button>
            <a-button size="small">
              <template #icon><icon-upload /></template>
              {{ tl('导入 YAML') }}
            </a-button>
          </template>
        </a-upload>
        <a-button type="primary" size="small" @click="showCreateModal = true">
          <template #icon><icon-plus /></template>
          {{ tl('新建套件') }}
        </a-button>
      </a-space>
      <a-select
        v-model="groupFilter"
        :placeholder="tl('按分组筛选')"
        size="small"
        style="width: 160px"
        allow-clear
      >
        <a-option v-for="g in store.groups" :key="g" :value="g" :label="g" />
      </a-select>
    </div>

    <!-- Suite table -->
    <a-spin :loading="store.suitesLoading">
      <a-table
        v-if="filteredSuites.length > 0"
        :data="filteredSuites"
        :pagination="false"
        size="small"
        :row-key="(r: any) => r.id"
        :bordered="false"
        :scroll="{ y: 480 }"
        row-class="suite-row"
      >
        <template #columns>
          <a-table-column :title="tl('名称')" data-index="name" :width="200">
            <template #cell="{ record }">
              <span class="suite-name">{{ record.name }}</span>
              <div class="suite-desc" v-if="record.description">
                {{ truncate(record.description, 50) }}
              </div>
            </template>
          </a-table-column>
          <a-table-column :title="tl('分组')" :width="100">
            <template #cell="{ record }">
              <a-tag v-if="record.group" size="small" color="gray">{{ record.group }}</a-tag>
              <span v-else class="text-muted">-</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('引擎')" :width="110">
            <template #cell="{ record }">
              <a-tag
                :color="record.engine === 'midscene' ? 'arcoblue' : 'cyan'"
                size="small"
                class="engine-tag"
              >
                {{ record.engine === 'midscene' ? tl('视觉引擎') : tl('语义引擎') }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('来源')" :width="100">
            <template #cell="{ record }">
              <a-tag v-if="record.source === 'prd_generated'" size="small" color="purple">
                {{ tl('PRD生成') }}
              </a-tag>
              <span v-else class="text-muted">-</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('状态')" :width="90">
            <template #cell="{ record }">
              <a-tag :color="suiteStatusColor(record.status)" size="small">
                {{ suiteStatusLabel(record.status) }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('用例数')" :width="70" align="center">
            <template #cell="{ record }">
              <span class="count-badge">{{ record.test_count }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('操作')" :width="240" align="right">
            <template #cell="{ record }">
              <a-space>
                <a-button
                  type="primary"
                  size="mini"
                  :loading="runningSuiteId === record.id"
                  @click="handleRun(record)"
                >
                  {{ tl('运行') }}
                </a-button>
                <a-button size="mini" @click="openYamlEditor(record)">
                  {{ tl('编辑 YAML') }}
                </a-button>
                <a-button
                  size="mini"
                  :disabled="!recordHasRun(record)"
                  @click="viewReport(record)"
                >
                  {{ tl('查看报告') }}
                </a-button>
                <a-popconfirm
                  :content="tl('确定删除此套件？')"
                  @ok="handleDelete(record)"
                  position="left"
                >
                  <a-button size="mini" status="danger">
                    {{ tl('删除') }}
                  </a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div v-else-if="!store.suitesLoading" class="empty-state">
        <a-empty>
          <template #image>
            <icon-experiment style="font-size: 42px; color: var(--theme-empty-icon);" />
          </template>
          <template #description>
            <div>{{ tl('暂无测试套件') }}</div>
            <div class="empty-hint">
              {{ tl('支持两种引擎：Midscene 视觉引擎（截图对比）和 Agent Browser 语义引擎（DOM 语义定位）') }}
            </div>
          </template>
        </a-empty>
      </div>
    </a-spin>

    <!-- Create Suite Modal -->
    <a-modal
      v-model:visible="showCreateModal"
      :title="tl('新建测试套件')"
      :ok-loading="creating"
      @ok="handleCreate"
      @cancel="resetCreateForm"
      :width="480"
    >
      <a-form :model="createForm" layout="vertical" size="small">
        <a-form-item :label="tl('名称')" required>
          <a-input v-model="createForm.name" :placeholder="tl('输入套件名称')" />
        </a-form-item>
        <a-form-item :label="tl('分组')">
          <a-input v-model="createForm.group" :placeholder="tl('可选分组')" />
        </a-form-item>
        <a-form-item :label="tl('引擎')">
          <a-select v-model="createForm.engine">
            <a-option value="midscene">{{ tl('视觉引擎 (Midscene)') }}</a-option>
            <a-option value="agent_browser">{{ tl('语义引擎 (Agent Browser)') }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('Base URL')">
          <a-input v-model="createForm.base_url" :placeholder="tl('https://example.com')" />
        </a-form-item>
        <a-form-item :label="tl('LLM 配置')">
          <a-select v-model="createForm.llm_config_id" :placeholder="tl('选择 LLM 配置')" allow-clear>
            <a-option v-for="cfg in llmConfigs" :key="cfg.id" :value="cfg.id" :label="cfg.config_name" />
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('描述')">
          <a-textarea v-model="createForm.description" :placeholder="tl('可选描述')" :auto-size="{ minRows: 2, maxRows: 4 }" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- YAML Editor Modal -->
    <a-modal
      v-model:visible="showYamlModal"
      :title="tl('编辑 YAML') + (editingSuite ? ' - ' + editingSuite.name : '')"
      :ok-loading="savingYaml"
      @ok="handleSaveYaml"
      @cancel="showYamlModal = false"
      :width="720"
      :body-style="{ padding: '0' }"
    >
      <div class="yaml-editor-toolbar">
        <a-select v-model="editingEngine" size="small" style="width: 180px">
          <a-option value="midscene">{{ tl('视觉引擎 (Midscene)') }}</a-option>
          <a-option value="agent_browser">{{ tl('语义引擎 (Agent Browser)') }}</a-option>
        </a-select>
        <a-select v-model="editingLlmId" size="small" style="width: 180px" :placeholder="tl('LLM 配置')" allow-clear>
          <a-option v-for="cfg in llmConfigs" :key="cfg.id" :value="cfg.id" :label="cfg.config_name" />
        </a-select>
      </div>
      <div class="yaml-editor-wrap">
        <MonacoEditor
          v-model:value="yamlContent"
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
import { ref, computed, onMounted, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconUpload, IconPlus, IconExperiment } from '@arco-design/web-vue/es/icon';
import MonacoEditor from '@guolao/vue-monaco-editor';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useThemeStore } from '@/store/themeStore';
import { listLlmConfigs } from '@/features/langgraph/services/llmConfigService';
import type { LlmConfig } from '@/features/langgraph/types/llmConfig';
import { useWebQaStore } from '../store/webQaStore';
import type { QaSuite, QaEngine } from '../services/webQaService';
import RunDetailDrawer from './RunDetailDrawer.vue';

type FileItem = { file?: File; [key: string]: any };

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const themeStore = useThemeStore();
const store = useWebQaStore();

const groupFilter = ref<string>('');
const showCreateModal = ref(false);
const creating = ref(false);
const showYamlModal = ref(false);
const savingYaml = ref(false);
const editingSuite = ref<QaSuite | null>(null);
const yamlContent = ref('');
const editingEngine = ref<QaEngine>('midscene');
const editingLlmId = ref<number | undefined>(undefined);
const runningSuiteId = ref<number | null>(null);
const showRunDrawer = ref(false);
const activeRunId = ref<number | null>(null);

const llmConfigs = ref<LlmConfig[]>([]);

const createForm = ref({
  name: '',
  group: '',
  engine: 'midscene' as QaEngine,
  base_url: '',
  description: '',
  llm_config_id: undefined as number | undefined,
});

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

const filteredSuites = computed(() => {
  if (!groupFilter.value) return store.suites;
  return store.suites.filter((s) => s.group === groupFilter.value);
});

function suiteStatusColor(s: string): string {
  switch (s) {
    case 'ready': return 'green';
    case 'draft': return 'gray';
    case 'generating': return 'orange';
    case 'error': return 'red';
    default: return 'gray';
  }
}

function suiteStatusLabel(s: string): string {
  switch (s) {
    case 'ready': return tl('就绪');
    case 'draft': return tl('草稿');
    case 'generating': return tl('生成中');
    case 'error': return tl('错误');
    default: return s;
  }
}

function truncate(s: string | null, len: number): string {
  if (!s) return '';
  return s.length > len ? s.slice(0, len) + '...' : s;
}

function recordHasRun(record: QaSuite): boolean {
  return record.test_count > 0;
}

function resetCreateForm() {
  createForm.value = {
    name: '',
    group: '',
    engine: 'midscene',
    base_url: '',
    description: '',
    llm_config_id: undefined,
  };
}

async function handleCreate() {
  if (!createForm.value.name.trim()) {
    Message.warning(tl('请输入套件名称'));
    return;
  }
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  creating.value = true;
  try {
    await store.createSuite(pid, {
      name: createForm.value.name.trim(),
      group: createForm.value.group || undefined,
      engine: createForm.value.engine,
      base_url: createForm.value.base_url || undefined,
      description: createForm.value.description || undefined,
      llm_config_id: createForm.value.llm_config_id,
    });
    Message.success(tl('套件创建成功'));
    showCreateModal.value = false;
    resetCreateForm();
  } catch (e: any) {
    Message.error(e.message || tl('创建失败'));
  } finally {
    creating.value = false;
  }
}

function openYamlEditor(suite: QaSuite) {
  editingSuite.value = suite;
  yamlContent.value = suite.yaml_content || '';
  editingEngine.value = suite.engine;
  editingLlmId.value = suite.llm_config_id || undefined;
  showYamlModal.value = true;
}

async function handleSaveYaml() {
  if (!editingSuite.value) return;
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  savingYaml.value = true;
  try {
    await store.updateSuiteYaml(pid, editingSuite.value.id, yamlContent.value);
    // Update engine and llm config if changed
    if (editingEngine.value !== editingSuite.value.engine || editingLlmId.value !== editingSuite.value.llm_config_id) {
      await store.updateSuite(pid, editingSuite.value.id, {
        engine: editingEngine.value,
        llm_config_id: editingLlmId.value,
      });
    }
    Message.success(tl('YAML 已保存'));
    showYamlModal.value = false;
  } catch (e: any) {
    Message.error(e.message || tl('保存失败'));
  } finally {
    savingYaml.value = false;
  }
}

async function handleImportFile(fileList: FileItem[]) {
  const file = fileList[0]?.file;
  if (!file) return;
  const pid = projectStore.currentProjectId;
  if (!pid) {
    Message.warning(tl('请先选择项目'));
    return;
  }
  try {
    await store.importSuite(pid, file);
    Message.success(tl('导入成功'));
  } catch (e: any) {
    Message.error(e.message || tl('导入失败'));
  }
}

async function handleRun(suite: QaSuite) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  runningSuiteId.value = suite.id;
  try {
    const result = await store.runSuite(pid, suite.id);
    Message.success(tl('运行已启动'));
    activeRunId.value = result.run_id;
    showRunDrawer.value = true;
  } catch (e: any) {
    Message.error(e.message || tl('运行失败'));
  } finally {
    runningSuiteId.value = null;
  }
}

function viewReport(suite: QaSuite) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  // Find latest run for this suite
  const run = store.runs.find((r) => r.suite_id === suite.id);
  if (run) {
    activeRunId.value = run.id;
    showRunDrawer.value = true;
  } else {
    Message.info(tl('暂无运行记录'));
  }
}

async function handleDelete(suite: QaSuite) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  try {
    await store.deleteSuite(pid, suite.id);
    Message.success(tl('已删除'));
  } catch (e: any) {
    Message.error(e.message || tl('删除失败'));
  }
}

async function loadLlmConfigs() {
  try {
    const res = await listLlmConfigs();
    if (res.data) llmConfigs.value = res.data;
  } catch (e) {
    console.error('loadLlmConfigs failed', e);
  }
}

const pid = computed(() => projectStore.currentProjectId);

watch(pid, async (val) => {
  if (val) {
    await store.loadSuites(val);
    await store.loadRuns(val);
  }
}, { immediate: true });

onMounted(() => {
  loadLlmConfigs();
});
</script>

<style scoped>
.suite-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.suite-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--theme-text);
}

.suite-desc {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-top: 2px;
}

.engine-tag {
  font-weight: 600;
}

.text-muted {
  color: var(--theme-text-tertiary);
  font-size: 12px;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 10px;
  background: rgba(var(--theme-accent-rgb), 0.1);
  color: var(--theme-accent);
}

.empty-state {
  padding: 60px 20px;
  text-align: center;
}

.empty-hint {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-top: 8px;
  max-width: 360px;
  line-height: 1.5;
}

.yaml-editor-toolbar {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--theme-border);
}

.yaml-editor-wrap {
  height: 420px;
}

.yaml-editor {
  height: 100%;
}
</style>
