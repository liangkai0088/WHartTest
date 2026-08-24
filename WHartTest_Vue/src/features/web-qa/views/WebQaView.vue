<template>
  <div class="web-qa-view">
    <!-- No project selected -->
    <div v-if="!currentProjectId" class="no-project">
      <a-empty :description="tl('请在顶部选择一个项目')">
        <template #image>
          <icon-experiment style="font-size: 48px; color: var(--theme-empty-icon, #c2c7d0);" />
        </template>
      </a-empty>
    </div>

    <template v-else>
      <!-- Header -->
      <div class="view-header">
        <div class="header-left">
          <icon-experiment class="header-icon" />
          <h2 class="view-title">{{ tl('Web QA') }}</h2>
        </div>
      </div>

      <!-- Tabs -->
      <a-tabs v-model:active-key="activeTab" class="qa-tabs" type="line">
        <a-tab-pane key="suites" :title="tl('测试套件')">
          <SuitePanel />
        </a-tab-pane>

        <a-tab-pane key="batch" :title="tl('批量执行')">
          <BatchRunPanel />
        </a-tab-pane>

        <a-tab-pane key="prd" :title="tl('PRD 生成')">
          <PrdGeneratePanel />
        </a-tab-pane>

        <a-tab-pane key="cache" :title="tl('定位缓存')">
          <LocatorCachePanel />
        </a-tab-pane>
      </a-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { IconExperiment } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useWebQaStore } from '../store/webQaStore';
import SuitePanel from '../components/SuitePanel.vue';
import BatchRunPanel from '../components/BatchRunPanel.vue';
import PrdGeneratePanel from '../components/PrdGeneratePanel.vue';
import LocatorCachePanel from '../components/LocatorCachePanel.vue';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useWebQaStore();

const activeTab = ref('suites');
const currentProjectId = computed(() => projectStore.currentProjectId);

onUnmounted(() => {
  store.cleanup();
});
</script>

<style scoped>
.web-qa-view {
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

.qa-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

:deep(.qa-tabs .arco-tabs-content) {
  flex: 1;
  min-height: 0;
  padding-top: 12px;
  overflow-y: auto;
}

:deep(.qa-tabs .arco-tabs-content-inner) {
  height: 100%;
}

:deep(.qa-tabs .arco-tabs-pane) {
  height: 100%;
}
</style>
