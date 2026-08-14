<template>
  <div class="exec-dashboard-view">
    <!-- 无项目选择 -->
    <div v-if="!currentProjectId" class="no-project">
      <a-empty :description="tl('请在顶部选择一个项目')">
        <template #image>
          <icon-bar-chart style="font-size: 48px; color: var(--theme-text-tertiary);" />
        </template>
      </a-empty>
    </div>

    <template v-else>
      <a-spin :loading="store.loading" :tip="tl('加载中...')" class="view-spin">
        <!-- 顶部 Header -->
        <div class="view-header">
          <div class="header-left">
            <h2 class="view-title">{{ tl('AI 执行看板') }}</h2>
            <a-tag v-if="wsConnected" color="arcoblue" size="small" class="ws-tag">
              <icon-wifi class="ws-icon" /> {{ tl('实时连接') }}
            </a-tag>
            <a-tag v-else color="orangered" size="small" class="ws-tag">
              <icon-wifi class="ws-icon ws-disconnected" /> {{ tl('未连接') }}
            </a-tag>
          </div>

          <div class="header-right" v-if="hasActiveRun">
            <span class="suite-name">{{ store.run.suiteName }}</span>
            <span :class="['run-status', `run-${store.run.status}`]">
              {{ runStatusLabel(store.run.status) }}
            </span>
            <span class="executor" v-if="store.run.executor">
              <icon-user class="executor-icon" /> {{ store.run.executor }}
            </span>
            <span class="elapsed">
              <icon-clock-circle class="elapsed-icon" /> {{ formatDuration(store.run.elapsed) }}
            </span>
          </div>
        </div>

        <!-- 无运行态 -->
        <div v-if="!hasActiveRun && !store.run.runId" class="no-run-state">
          <a-empty :description="tl('当前没有正在运行的任务')" />
          <div class="no-run-hint">{{ tl('下方可查看历史执行记录并回放') }}</div>
        </div>

        <!-- 有运行态时显示内容 -->
        <template v-if="store.run.runId">
          <!-- 统计行 -->
          <div class="stats-row">
            <div class="stats-card pie-card">
              <PassRatePie
                :passed="store.run.passed"
                :failed="store.run.failed"
                :skipped="store.run.skipped"
                :errored="store.run.error"
                :total="store.run.total"
                :size="110"
              />
              <div class="pie-legend">
                <div class="legend-row"><span class="dot dot-pass" />{{ tl('通过') }} <strong>{{ store.run.passed }}</strong></div>
                <div class="legend-row"><span class="dot dot-fail" />{{ tl('失败') }} <strong>{{ store.run.failed }}</strong></div>
                <div class="legend-row"><span class="dot dot-error" />{{ tl('错误') }} <strong>{{ store.run.error }}</strong></div>
                <div class="legend-row"><span class="dot dot-skip" />{{ tl('跳过') }} <strong>{{ store.run.skipped }}</strong></div>
              </div>
            </div>

            <div class="stats-card numbers-card">
              <div class="stat-grid">
                <div class="stat-cell">
                  <span class="stat-num">{{ store.run.total }}</span>
                  <span class="stat-label">{{ tl('总用例') }}</span>
                </div>
                <div class="stat-cell accent">
                  <span class="stat-num">{{ store.run.running }}</span>
                  <span class="stat-label">{{ tl('运行中') }}</span>
                </div>
                <div class="stat-cell muted">
                  <span class="stat-num">{{ store.run.pending }}</span>
                  <span class="stat-label">{{ tl('等待中') }}</span>
                </div>
                <div class="stat-cell pass">
                  <span class="stat-num">{{ store.run.passRate.toFixed(1) }}%</span>
                  <span class="stat-label">{{ tl('通过率') }}</span>
                </div>
              </div>
            </div>

            <div class="stats-card eta-card" v-if="store.run.eta">
              <EtaBar
                :progress="store.run.eta.progress"
                :remaining-seconds="store.run.eta.remaining_seconds"
                :eta-seconds="store.run.eta.eta_seconds"
                :confidence="store.run.eta.confidence"
              />
            </div>
          </div>

          <!-- 泳道图 -->
          <div class="section-swimlane">
            <div class="section-header">
              <span class="section-title">{{ tl('执行泳道图') }}</span>
              <span class="section-sub">{{ nodesList.length }} {{ tl('个用例') }}</span>
            </div>
            <SwimlaneChart
              :nodes="nodesList"
              :started-at="store.run.startedAt"
              :elapsed="store.run.elapsed"
            />
          </div>

          <!-- 失败面板 -->
          <FailedCasePanel :nodes="nodesList" class="section-failed" />
        </template>

        <!-- 运行列表（始终显示） -->
        <div class="section-runs">
          <RunListPanel :runs="runsList" :loading="runsLoading" />
        </div>
      </a-spin>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useProjectStore } from '@/store/projectStore'
import { useAppI18n } from '@/composables/useAppI18n'
import { useExecutionDashboardStore } from '../store/executionDashboardStore'
import { getRunsList } from '../services/executionDashboardApi'
import type { TestExecution } from '@/services/testExecutionService'
import PassRatePie from '../components/PassRatePie.vue'
import SwimlaneChart from '../components/SwimlaneChart.vue'
import FailedCasePanel from '../components/FailedCasePanel.vue'
import EtaBar from '../components/EtaBar.vue'
import RunListPanel from '../components/RunListPanel.vue'
import {
  IconBarChart, IconWifi, IconUser, IconClockCircle
} from '@arco-design/web-vue/es/icon'

const { tl } = useAppI18n()
const projectStore = useProjectStore()
const store = useExecutionDashboardStore()

const currentProjectId = computed(() => projectStore.currentProjectId)
const wsConnected = computed(() => store.connected)
const hasActiveRun = computed(() => store.run.status === 'running')

const nodesList = computed(() => Array.from(store.nodes.values()))

const runsList = ref<TestExecution[]>([])
const runsLoading = ref(false)

function runStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: tl('待执行'),
    running: tl('执行中'),
    completed: tl('已完成'),
    failed: tl('已失败'),
    cancelled: tl('已取消'),
  }
  return map[status] || status
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return Math.round(seconds) + 's'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

async function fetchRuns() {
  if (!currentProjectId.value) return
  runsLoading.value = true
  try {
    const res = await getRunsList(currentProjectId.value, { ordering: '-created_at' })
    if (res.success && res.data) {
      runsList.value = res.data
    }
  } catch (e) {
    console.error('[ExecDash] fetchRuns failed:', e)
  } finally {
    runsLoading.value = false
  }
}

async function initDashboard() {
  if (!currentProjectId.value) return

  // 连接 WS
  await store.connectProject(currentProjectId.value)

  // 拉取运行列表
  await fetchRuns()

  // 尝试加载最新运行的快照（如果运行列表有 running 的）
  const running = runsList.value.find(r => r.status === 'running')
  if (running) {
    await store.loadSnapshot(running.id)
  } else if (runsList.value.length > 0) {
    // 没有运行中的，加载最新一个快照看看
    await store.loadSnapshot(runsList.value[0].id)
  }
}

watch(currentProjectId, () => {
  store.disconnect()
  if (currentProjectId.value) {
    initDashboard()
  }
})

onMounted(() => {
  if (currentProjectId.value) {
    initDashboard()
  }
})

onBeforeUnmount(() => {
  store.disconnect()
})
</script>

<style scoped>
.exec-dashboard-view {
  height: 100%;
  background-color: var(--theme-page-bg);
  padding: 10px;
  box-sizing: border-box;
  overflow-y: auto;
}

.no-project {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}

.view-spin {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

:deep(.arco-spin-children) {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* Header */
.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 16px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.view-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--theme-text);
  margin: 0;
}

.ws-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.ws-icon {
  font-size: 12px;
}

.ws-disconnected {
  opacity: 0.6;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 13px;
  color: var(--theme-text-secondary);
}

.suite-name {
  font-weight: 600;
  color: var(--theme-text);
}

.run-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 8px;
  font-weight: 500;
}

.run-running {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.run-completed {
  background: rgba(82, 196, 26, 0.1);
  color: #52c41a;
}

.run-failed {
  background: rgba(255, 77, 79, 0.1);
  color: #ff4d4f;
}

.run-pending {
  background: rgba(134, 144, 156, 0.1);
  color: #86909c;
}

.run-cancelled {
  background: rgba(250, 173, 20, 0.1);
  color: #d48806;
}

.executor {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.executor-icon {
  font-size: 13px;
}

.elapsed {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-variant-numeric: tabular-nums;
}

.elapsed-icon {
  font-size: 13px;
}

/* No run */
.no-run-state {
  text-align: center;
  padding: 30px 0 10px;
}

.no-run-hint {
  font-size: 13px;
  color: var(--theme-text-tertiary);
  margin-top: 8px;
}

/* Stats row */
.stats-row {
  display: grid;
  grid-template-columns: 260px 1fr 1fr;
  gap: 10px;
}

.stats-card {
  background: #ffffff;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.pie-card {
  display: flex;
  align-items: center;
  gap: 16px;
}

.pie-legend {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.legend-row strong {
  margin-left: auto;
  color: var(--theme-text);
  font-variant-numeric: tabular-nums;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-pass { background: #52c41a; }
.dot-fail { background: #ff4d4f; }
.dot-error { background: #b91c1c; }
.dot-skip { background: #faad14; }

.numbers-card {
  display: flex;
  align-items: center;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  width: 100%;
}

.stat-cell {
  text-align: center;
  padding: 6px;
  border-radius: 6px;
  background: var(--theme-surface-soft);
}

.stat-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: var(--theme-text);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.stat-cell.pass .stat-num { color: #52c41a; }
.stat-cell.accent .stat-num { color: var(--theme-accent); }
.stat-cell.muted .stat-num { color: var(--theme-text-tertiary); }

.eta-card {
  display: flex;
  align-items: center;
}

.eta-card > :deep(*) {
  width: 100%;
}

/* Swimlane */
.section-swimlane {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 4px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--theme-text);
}

.section-sub {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.section-failed {
  margin-top: 0;
}

.section-runs {
  margin-top: 0;
}

/* Responsive */
@media (max-width: 1200px) {
  .stats-row {
    grid-template-columns: 1fr 1fr;
  }

  .pie-card {
    grid-column: 1 / -1;
  }
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: 1fr;
  }

  .view-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
