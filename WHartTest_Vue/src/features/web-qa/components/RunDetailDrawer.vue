<template>
  <a-drawer
    :visible="visible"
    :title="drawerTitle"
    :width="780"
    placement="right"
    :ok-text="undefined"
    :cancel-text="tl('关闭')"
    @cancel="handleClose"
    :footer="false"
    :body-style="{ padding: '0' }"
  >
    <!-- Header -->
    <div class="drawer-header">
      <div class="header-info">
        <span class="suite-name">{{ suiteName }}</span>
        <a-tag
          :color="suiteEngine === 'midscene' ? 'arcoblue' : 'cyan'"
          size="small"
          v-if="suiteEngine"
        >
          {{ suiteEngine === 'midscene' ? tl('视觉引擎') : tl('语义引擎') }}
        </a-tag>
        <a-tag :color="runStatusColor(runDetail?.run?.status || '')" size="small" v-if="runDetail?.run">
          {{ runStatusLabel(runDetail?.run?.status || '') }}
        </a-tag>
        <span class="duration" v-if="runDetail?.run?.summary">
          {{ formatDuration(runDetail.run.summary.duration) }}
        </span>
      </div>
    </div>

    <!-- Summary stat cards -->
    <div v-if="runDetail?.run?.summary" class="summary-cards">
      <div class="stat-card">
        <span class="stat-value">{{ runDetail.run.summary.total }}</span>
        <span class="stat-label">{{ tl('总计') }}</span>
      </div>
      <div class="stat-card stat-passed">
        <span class="stat-value">{{ runDetail.run.summary.passed }}</span>
        <span class="stat-label">{{ tl('通过') }}</span>
      </div>
      <div class="stat-card stat-failed">
        <span class="stat-value">{{ runDetail.run.summary.failed }}</span>
        <span class="stat-label">{{ tl('失败') }}</span>
      </div>
      <div class="stat-card stat-skipped">
        <span class="stat-value">{{ runDetail.run.summary.skipped }}</span>
        <span class="stat-label">{{ tl('跳过') }}</span>
      </div>
      <div class="stat-card stat-warnings">
        <span class="stat-value">{{ runDetail.run.summary.warnings }}</span>
        <span class="stat-label">{{ tl('警告') }}</span>
      </div>
    </div>

    <!-- Tabs: Steps / Report -->
    <a-tabs v-model:active-key="activeTab" type="line" class="detail-tabs">
      <a-tab-pane key="steps" :title="tl('步骤详情')">
        <a-spin :loading="store.runDetailLoading">
          <div v-if="!runDetail?.steps?.length" class="tab-empty">
            <a-empty :description="tl('暂无步骤数据')" />
          </div>
          <div v-else class="steps-container">
            <div
              v-for="(group, testName) in groupedSteps"
              :key="testName"
              class="test-group"
            >
              <div class="test-group-header">
                <span class="test-group-name">{{ testName }}</span>
                <span class="test-group-count">{{ group.length }} {{ tl('步') }}</span>
              </div>
              <div class="step-rows">
                <div
                  v-for="step in group"
                  :key="step.id"
                  class="step-row"
                >
                  <div class="step-main">
                    <span class="step-index">#{{ step.step_index }}</span>
                    <span class="step-action">{{ step.action }}</span>
                    <a-tag :color="stepStatusColor(step.status)" size="small">
                      {{ stepStatusLabel(step.status) }}
                    </a-tag>
                    <span class="step-duration" v-if="step.duration_ms != null">
                      {{ step.duration_ms }}ms
                    </span>
                    <a-tooltip v-if="step.locator_meta" :content="step.locator_meta" position="top">
                      <icon-info-circle class="meta-icon" />
                    </a-tooltip>
                  </div>
                  <!-- Error expand -->
                  <div v-if="step.error" class="step-error">
                    <a-collapse :bordered="false" size="small">
                      <a-collapse-item :header="tl('错误详情')" key="err">
                        <pre class="error-text">{{ step.error }}</pre>
                      </a-collapse-item>
                    </a-collapse>
                  </div>
                  <!-- Screenshot thumbnail -->
                  <div v-if="step.screenshot_path" class="step-screenshot">
                    <img
                      :src="getScreenshotUrl(step.screenshot_path)"
                      class="screenshot-thumb"
                      @click="previewScreenshot(step.screenshot_path!)"
                      :alt="tl('截图')"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="report" :title="tl('报告')">
        <a-spin :loading="reportLoading">
          <div v-if="reportHtml" class="report-content" v-html="reportHtml" />
          <div v-else class="tab-empty">
            <a-empty :description="tl('暂无报告')" />
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>

    <!-- Screenshot preview modal -->
    <a-modal
      v-model:visible="showScreenshotModal"
      :title="tl('截图预览')"
      :footer="false"
      :width="800"
    >
      <img :src="previewUrl" class="screenshot-full" :alt="tl('截图')" />
    </a-modal>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { marked } from 'marked';
import { IconInfoCircle } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useWebQaStore } from '../store/webQaStore';
import type { QaStepResult } from '../services/webQaService';

const props = defineProps<{
  visible: boolean;
  runId: number | null;
}>();

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void;
}>();

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useWebQaStore();

const activeTab = ref('steps');
const reportLoading = ref(false);
const reportHtml = ref('');
const showScreenshotModal = ref(false);
const previewUrl = ref('');

const runDetail = computed(() => store.currentRunDetail);

const suiteName = computed(() => {
  if (!runDetail.value) return '';
  const suite = store.suites.find((s) => s.id === runDetail.value!.run.suite_id);
  return suite?.name || `Suite #${runDetail.value.run.suite_id}`;
});

const suiteEngine = computed(() => {
  if (!runDetail.value) return null;
  const suite = store.suites.find((s) => s.id === runDetail.value!.run.suite_id);
  return suite?.engine || null;
});

const drawerTitle = computed(() => {
  return `${tl('运行详情')} - ${suiteName.value}`;
});

const groupedSteps = computed(() => {
  if (!runDetail.value?.steps) return {};
  const groups: Record<string, QaStepResult[]> = {};
  for (const step of runDetail.value.steps) {
    const name = step.test_name || `Test ${step.test_index}`;
    if (!groups[name]) groups[name] = [];
    groups[name].push(step);
  }
  return groups;
});

function runStatusColor(s: string): string {
  switch (s) {
    case 'passed':
    case 'completed': return 'green';
    case 'failed':
    case 'error': return 'red';
    case 'running': return 'arcoblue';
    case 'pending': return 'orange';
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
    default: return s;
  }
}

function stepStatusColor(s: string): string {
  switch (s) {
    case 'passed': return 'green';
    case 'failed': return 'red';
    case 'skipped': return 'orangered';
    case 'error': return 'red';
    default: return 'gray';
  }
}

function stepStatusLabel(s: string): string {
  switch (s) {
    case 'passed': return tl('通过');
    case 'failed': return tl('失败');
    case 'skipped': return tl('跳过');
    case 'error': return tl('错误');
    default: return s;
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60000);
  const s = Math.round((ms % 60000) / 1000);
  return `${m}m ${s}s`;
}

function getScreenshotUrl(path: string): string {
  // Assume it's a relative path from the API
  if (path.startsWith('http')) return path;
  return `/api${path.startsWith('/') ? '' : '/'}${path}`;
}

function previewScreenshot(path: string) {
  previewUrl.value = getScreenshotUrl(path);
  showScreenshotModal.value = true;
}

function handleClose() {
  emit('update:visible', false);
}

watch(
  () => [props.visible, props.runId] as const,
  async ([vis, rid]) => {
    if (vis && rid) {
      const pid = projectStore.currentProjectId;
      if (!pid) return;
      activeTab.value = 'steps';
      reportHtml.value = '';
      await store.loadRunDetail(pid, rid);
    }
  },
);

watch(activeTab, async (tab) => {
  if (tab === 'report' && !reportHtml.value && props.runId) {
    const pid = projectStore.currentProjectId;
    if (!pid) return;
    reportLoading.value = true;
    try {
      // First check if runDetail has report_md
      if (runDetail.value?.run?.report_md) {
        reportHtml.value = marked(runDetail.value.run.report_md, { async: false }) as string;
      } else {
        const md = await store.loadRunReport(pid, props.runId);
        if (store.runReportMd) {
          reportHtml.value = marked(store.runReportMd, { async: false }) as string;
        }
      }
    } catch (e) {
      console.error('report render failed', e);
    } finally {
      reportLoading.value = false;
    }
  }
});
</script>

<style scoped>
.drawer-header {
  padding: 14px 20px;
  border-bottom: 1px solid var(--theme-border);
}

.header-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.suite-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--theme-text);
}

.duration {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-left: 4px;
}

.summary-cards {
  display: flex;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--theme-border);
}

.stat-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 8px;
  border-radius: 8px;
  background: var(--theme-surface-soft);
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--theme-text);
}

.stat-label {
  font-size: 11px;
  color: var(--theme-text-tertiary);
  margin-top: 2px;
}

.stat-passed .stat-value { color: #00b42a; }
.stat-failed .stat-value { color: #f53f3f; }
.stat-skipped .stat-value { color: #ff7d00; }
.stat-warnings .stat-value { color: #faad14; }

.detail-tabs {
  padding: 0 20px;
}

:deep(.detail-tabs .arco-tabs-content) {
  padding-top: 10px;
}

.tab-empty {
  padding: 40px 0;
  text-align: center;
}

.steps-container {
  max-height: 500px;
  overflow-y: auto;
}

.test-group {
  margin-bottom: 14px;
}

.test-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--theme-surface-soft);
  border-radius: 6px;
  margin-bottom: 6px;
}

.test-group-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--theme-text);
}

.test-group-count {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.step-rows {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.step-row {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--theme-border);
  background: var(--theme-surface);
}

.step-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-index {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  font-size: 11px;
  color: var(--theme-text-tertiary);
  min-width: 24px;
}

.step-action {
  flex: 1;
  font-size: 13px;
  color: var(--theme-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.step-duration {
  font-size: 11px;
  font-family: monospace;
  color: var(--theme-text-tertiary);
}

.meta-icon {
  color: var(--theme-text-tertiary);
  cursor: help;
  font-size: 14px;
}

.step-error {
  margin-top: 6px;
}

.error-text {
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 12px;
  color: #f53f3f;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.step-screenshot {
  margin-top: 8px;
}

.screenshot-thumb {
  max-width: 200px;
  max-height: 120px;
  border-radius: 6px;
  border: 1px solid var(--theme-border);
  cursor: pointer;
  transition: opacity 0.15s;
}

.screenshot-thumb:hover {
  opacity: 0.85;
}

.screenshot-full {
  width: 100%;
  border-radius: 6px;
}

.report-content {
  padding: 12px 0;
  line-height: 1.7;
  font-size: 14px;
  color: var(--theme-text);
}

.report-content :deep(h1),
.report-content :deep(h2),
.report-content :deep(h3) {
  color: var(--theme-text);
  margin-top: 16px;
  margin-bottom: 8px;
}

.report-content :deep(code) {
  background: var(--theme-surface-soft);
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'SF Mono', Monaco, monospace;
}

.report-content :deep(pre) {
  background: var(--theme-surface-soft);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}

.report-content :deep(pre code) {
  background: none;
  padding: 0;
}

.report-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
}

.report-content :deep(th),
.report-content :deep(td) {
  border: 1px solid var(--theme-border);
  padding: 6px 10px;
  font-size: 13px;
}

.report-content :deep(th) {
  background: var(--theme-surface-soft);
  font-weight: 600;
}
</style>
