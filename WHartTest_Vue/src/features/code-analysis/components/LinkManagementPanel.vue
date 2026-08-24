<template>
  <div class="link-management-panel">
    <!-- Actions -->
    <div class="actions-row">
      <span class="section-title">{{ tl('用例链接管理') }}</span>
      <a-space>
        <a-button size="small" @click="reloadLinks">
          <template #icon><icon-refresh /></template>
        </a-button>
        <a-button
          type="primary"
          size="small"
          :disabled="!store.selectedProjectId"
          @click="showAddModal = true"
        >
          <template #icon><icon-plus /></template>
          {{ tl('添加链接') }}
        </a-button>
      </a-space>
    </div>

    <!-- Links table -->
    <a-spin :loading="store.linksLoading">
      <div v-if="store.links.length === 0 && !store.linksLoading" class="empty-state">
        <a-empty :description="tl('暂无用例链接')" />
      </div>
      <a-table
        v-else
        :data="store.links"
        :pagination="false"
        size="small"
        :row-key="(r: any) => r.id"
        :bordered="false"
        :scroll="{ y: 320 }"
      >
        <template #columns>
          <a-table-column :title="tl('用例名称')" :width="180">
            <template #cell="{ record }">
              <span class="case-name">{{ record.testcase_name }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('类型')" :width="70">
            <template #cell="{ record }">
              <a-tag :color="typeColor(record.testcase_type)" size="small">
                {{ typeLabel(record.testcase_type) }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('关联文件')" :width="200">
            <template #cell="{ record }">
              <span class="mono-path">{{ record.code_file_path || '-' }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('符号')" :width="120">
            <template #cell="{ record }">
              <span class="mono-path">{{ record.symbol || '-' }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('定位引用')" :width="120">
            <template #cell="{ record }">
              <span class="mono-path">{{ record.locator_ref || '-' }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('状态')" :width="80">
            <template #cell="{ record }">
              <a-tag :color="record.status === 'linked' ? 'green' : 'orange'" size="small">
                {{ record.status === 'linked' ? tl('已关联') : tl('已过期') }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('操作')" :width="60">
            <template #cell="{ record }">
              <a-popconfirm :content="tl('确定删除此链接？')" @ok="handleDelete(record)">
                <a-button type="text" status="danger" size="small">
                  {{ tl('删除') }}
                </a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </a-spin>

    <!-- Add link modal -->
    <a-modal
      v-model:visible="showAddModal"
      :title="tl('添加用例链接')"
      :ok-text="tl('创建')"
      :cancel-text="tl('取消')"
      :ok-loading="creatingLink"
      @ok="handleCreateLink"
    >
      <a-form layout="vertical">
        <a-form-item :label="tl('用例类型')" required>
          <a-select v-model="form.testcase_type" :placeholder="tl('选择类型')">
            <a-option value="functional">{{ tl('功能') }}</a-option>
            <a-option value="api">API</a-option>
            <a-option value="ui">UI</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('用例 ID')" required>
          <a-input-number v-model="form.testcase_id" :placeholder="tl('输入用例 ID')" :min="1" style="width: 100%" />
        </a-form-item>
        <a-form-item :label="tl('关联代码文件')">
          <a-select
            v-model="form.code_file_id"
            :placeholder="tl('选择文件 (可选)')"
            allow-clear
            :loading="store.filesLoading"
          >
            <a-option
              v-for="f in store.codeFiles"
              :key="f.id"
              :value="f.id"
              :label="f.path"
            />
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('符号路径')">
          <a-input v-model="form.symbol" :placeholder="tl('如 ClassName.method (可选)')" />
        </a-form-item>
        <a-form-item :label="tl('定位引用')">
          <a-input v-model="form.locator_ref" :placeholder="tl('如 CSS selector (可选)')" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconPlus, IconRefresh } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { TestCodeLink } from '../services/codeAnalysisService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const showAddModal = ref(false);
const creatingLink = ref(false);
const form = reactive({
  testcase_type: 'functional' as string,
  testcase_id: null as number | null,
  code_file_id: undefined as number | undefined,
  symbol: '',
  locator_ref: '',
});

function typeColor(t: string): string {
  switch (t) {
    case 'api': return 'arcoblue';
    case 'ui': return 'purple';
    case 'functional': return 'green';
    default: return 'gray';
  }
}

function typeLabel(t: string): string {
  switch (t) {
    case 'api': return 'API';
    case 'ui': return 'UI';
    case 'functional': return tl('功能');
    default: return t;
  }
}

async function reloadLinks() {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  await store.loadLinks(pid, cpId);
}

async function handleDelete(record: TestCodeLink) {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  try {
    await store.deleteLink(pid, cpId, record.id);
    Message.success(tl('删除成功'));
  } catch (e: any) {
    Message.error(e.message || tl('删除失败'));
  }
}

async function handleCreateLink() {
  if (!form.testcase_type) {
    Message.warning(tl('请选择用例类型'));
    return;
  }
  if (!form.testcase_id || form.testcase_id < 1) {
    Message.warning(tl('请输入有效的用例 ID'));
    return;
  }
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;

  creatingLink.value = true;
  try {
    const data: {
      testcase_type: string;
      testcase_id: number;
      code_file_id?: number;
      symbol?: string;
      locator_ref?: string;
    } = {
      testcase_type: form.testcase_type,
      testcase_id: form.testcase_id,
    };
    if (form.code_file_id) data.code_file_id = form.code_file_id;
    if (form.symbol.trim()) data.symbol = form.symbol.trim();
    if (form.locator_ref.trim()) data.locator_ref = form.locator_ref.trim();

    await store.createLink(pid, cpId, data);
    Message.success(tl('创建成功'));
    showAddModal.value = false;
    resetForm();
  } catch (e: any) {
    Message.error(e.message || tl('创建失败'));
  } finally {
    creatingLink.value = false;
  }
}

function resetForm() {
  form.testcase_type = 'functional';
  form.testcase_id = null;
  form.code_file_id = undefined;
  form.symbol = '';
  form.locator_ref = '';
}

// Auto-load links + files when selected project changes
watch(
  () => store.selectedProjectId,
  async (cpId) => {
    const pid = projectStore.currentProjectId;
    if (pid && cpId) {
      await Promise.all([
        store.loadLinks(pid, cpId),
        store.loadFiles(pid, cpId),
      ]);
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.link-management-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.actions-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--theme-text);
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.case-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--theme-text);
}

.mono-path {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text-secondary);
}
</style>
