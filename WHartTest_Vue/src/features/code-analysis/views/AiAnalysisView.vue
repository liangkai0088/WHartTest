<template>
  <div class="ai-analysis-view">
    <!-- No project selected -->
    <div v-if="!currentProjectId" class="no-project">
      <a-empty :description="tl('请在顶部选择一个项目')">
        <template #image>
          <icon-code-square style="font-size: 48px; color: var(--theme-empty-icon, #c2c7d0);" />
        </template>
      </a-empty>
    </div>

    <template v-else>
      <!-- Header -->
      <div class="view-header">
        <div class="header-left">
          <icon-code-square class="header-icon" />
          <h2 class="view-title">{{ tl('AI 源码分析') }}</h2>
        </div>
      </div>

      <!-- Tabs -->
      <a-tabs v-model:active-key="activeTab" class="analysis-tabs" type="line">
        <a-tab-pane key="projects" :title="tl('代码项目')">
          <CodeProjectPanel />
          <!-- File browser shown when project selected -->
          <div v-if="store.selectedProjectId" class="browser-section">
            <div class="section-divider">
              <span class="divider-label">{{ tl('文件浏览') }}</span>
            </div>
            <CodeFileBrowser />
          </div>
        </a-tab-pane>

        <a-tab-pane key="spec" :title="tl('OpenAPI 分析')">
          <SpecAnalysisPanel />
        </a-tab-pane>

        <a-tab-pane key="component" :title="tl('组件分析')">
          <ComponentAnalysisPanel />
        </a-tab-pane>

        <a-tab-pane key="impact" :title="tl('变更影响')">
          <ChangeImpactPanel />
          <div class="section-divider" style="margin-top: 20px;">
            <span class="divider-label">{{ tl('用例链接管理') }}</span>
          </div>
          <LinkManagementPanel />
        </a-tab-pane>
      </a-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue';
import { IconCodeSquare } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import CodeProjectPanel from '../components/CodeProjectPanel.vue';
import CodeFileBrowser from '../components/CodeFileBrowser.vue';
import SpecAnalysisPanel from '../components/SpecAnalysisPanel.vue';
import ComponentAnalysisPanel from '../components/ComponentAnalysisPanel.vue';
import ChangeImpactPanel from '../components/ChangeImpactPanel.vue';
import LinkManagementPanel from '../components/LinkManagementPanel.vue';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const activeTab = ref('projects');
const currentProjectId = computed(() => projectStore.currentProjectId);

// Load projects when project changes
watch(currentProjectId, async (pid) => {
  if (pid) {
    await store.loadProjects(pid);
  }
}, { immediate: true });

onMounted(async () => {
  if (currentProjectId.value) {
    await store.loadProjects(currentProjectId.value);
  }
});
</script>

<style scoped>
.ai-analysis-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  background: var(--theme-page-bg);
  overflow: hidden;
}

.no-project {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  font-size: 24px;
  color: var(--theme-accent);
}

.view-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--theme-text);
  margin: 0;
}

.analysis-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

:deep(.arco-tabs-content) {
  flex: 1;
  min-height: 0;
  padding-top: 12px;
  overflow-y: auto;
}

:deep(.arco-tabs-content-inner) {
  height: 100%;
}

:deep(.arco-tabs-pane) {
  height: 100%;
}

.browser-section {
  margin-top: 16px;
  height: 420px;
}

.section-divider {
  margin-bottom: 10px;
}

.divider-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--theme-text-secondary);
}
</style>
