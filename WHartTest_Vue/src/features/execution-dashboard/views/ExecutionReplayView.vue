<template>
  <div class="exec-replay-view">
    <a-spin :loading="loading" :tip="tl('加载回放数据...')" class="replay-spin">
      <template v-if="!loading && events.length > 0">
        <!-- Header -->
        <div class="replay-header">
          <a-button type="text" size="small" @click="goBack">
            <template #icon><icon-left /></template>
            {{ tl('返回看板') }}
          </a-button>
          <h2 class="replay-title">{{ tl('执行回放') }} #{{ runId }}</h2>
          <span v-if="replayState.run.suiteName" class="suite-tag">{{ replayState.run.suiteName }}</span>
        </div>

        <!-- 控制条 -->
        <PlaybackControls
          :playing="playing"
          :current-index="currentIndex"
          :total-events="events.length"
          :speed="speed"
          @toggle-play="togglePlay"
          @seek="seekTo"
          @speed-change="onSpeedChange"
        />

        <!-- 统计 -->
        <div class="replay-stats-row">
          <div class="replay-card pie-card">
            <PassRatePie
              :passed="replayState.run.passed"
              :failed="replayState.run.failed"
              :skipped="replayState.run.skipped"
              :errored="replayState.run.error"
              :total="replayState.run.total"
              :size="100"
            />
            <div class="pie-legend">
              <div class="legend-row"><span class="dot dot-pass" />{{ tl('通过') }} <strong>{{ replayState.run.passed }}</strong></div>
              <div class="legend-row"><span class="dot dot-fail" />{{ tl('失败') }} <strong>{{ replayState.run.failed }}</strong></div>
              <div class="legend-row"><span class="dot dot-error" />{{ tl('错误') }} <strong>{{ replayState.run.error }}</strong></div>
              <div class="legend-row"><span class="dot dot-skip" />{{ tl('跳过') }} <strong>{{ replayState.run.skipped }}</strong></div>
            </div>
          </div>

          <div class="replay-card numbers-card">
            <div class="stat-grid">
              <div class="stat-cell">
                <span class="stat-num">{{ replayState.run.total }}</span>
                <span class="stat-label">{{ tl('总用例') }}</span>
              </div>
              <div class="stat-cell accent">
                <span class="stat-num">{{ replayState.run.running }}</span>
                <span class="stat-label">{{ tl('运行中') }}</span>
              </div>
              <div class="stat-cell muted">
                <span class="stat-num">{{ replayState.run.pending }}</span>
                <span class="stat-label">{{ tl('等待中') }}</span>
              </div>
              <div class="stat-cell pass">
                <span class="stat-num">{{ replayState.run.passRate.toFixed(1) }}%</span>
                <span class="stat-label">{{ tl('通过率') }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 泳道图 -->
        <div class="replay-section">
          <div class="section-header">
            <span class="section-title">{{ tl('执行泳道图') }}</span>
            <span class="section-sub">{{ replayNodes.length }} {{ tl('个用例') }}</span>
          </div>
          <SwimlaneChart
            :nodes="replayNodes"
            :started-at="replayState.run.startedAt"
            :elapsed="replayState.run.elapsed"
          />
        </div>

        <!-- 失败面板 -->
        <FailedCasePanel :nodes="replayNodes" class="replay-failed" />
      </template>

      <a-empty v-else-if="!loading" :description="tl('暂无回放数据')" />
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onBeforeUnmount, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppI18n } from '@/composables/useAppI18n'
import { getAllRunEvents, getRunSnapshot } from '../services/executionDashboardApi'
import type { EventRecord, RunState, NodeState, NodeStatus } from '../types'
import PassRatePie from '../components/PassRatePie.vue'
import SwimlaneChart from '../components/SwimlaneChart.vue'
import FailedCasePanel from '../components/FailedCasePanel.vue'
import PlaybackControls from '../components/PlaybackControls.vue'
import { IconLeft } from '@arco-design/web-vue/es/icon'

const { tl } = useAppI18n()
const route = useRoute()
const router = useRouter()

const runId = computed(() => Number(route.params.runId))

const loading = ref(true)
const events = ref<EventRecord[]>([])

// ─── Replay state ───
const currentIndex = ref(0)
const playing = ref(false)
const speed = ref(1)
let playTimer: ReturnType<typeof setTimeout> | null = null

function emptyRunState(): RunState {
  return {
    runId: null,
    suiteName: '',
    executor: '',
    status: '',
    startedAt: undefined,
    total: 0,
    passed: 0,
    failed: 0,
    skipped: 0,
    error: 0,
    running: 0,
    pending: 0,
    passRate: 0,
    elapsed: 0,
    eta: null,
  }
}

// 完整 reducer: 把 events[0..idx] 折叠成 RunState + nodes
function reduceUpTo(idx: number): { run: RunState; nodes: Map<number, NodeState> } {
  const run = emptyRunState()
  const nodes = new Map<number, NodeState>()

  for (let i = 0; i <= idx && i < events.value.length; i++) {
    const ev = events.value[i]
    const p = ev.payload as Record<string, unknown>

    switch (ev.event_type) {
      case 'run_started': {
        run.runId = Number(p.run_id)
        run.suiteName = String(p.suite_name || '')
        run.executor = String(p.executor || '')
        run.status = 'running'
        run.total = Number(p.total || 0)
        run.pending = run.total
        break
      }
      case 'node_status_changed': {
        const nodeId = Number(p.node_id)
        const existing = nodes.get(nodeId)
        const status = String(p.status) as NodeStatus
        nodes.set(nodeId, {
          id: nodeId,
          testcase_id: Number(p.testcase_id),
          name: String(p.name || existing?.name || ''),
          status,
          execution_time: p.execution_time != null ? Number(p.execution_time) : existing?.execution_time,
          error_message: p.error_message ? String(p.error_message) : existing?.error_message,
          started_at: p.started_at ? String(p.started_at) : existing?.started_at,
          completed_at: (status !== 'running' && status !== 'pending')
            ? (ev.created_at)
            : existing?.completed_at,
        })
        break
      }
      case 'run_stats': {
        run.total = Number(p.total || run.total)
        run.passed = Number(p.passed || 0)
        run.failed = Number(p.failed || 0)
        run.skipped = Number(p.skipped || 0)
        run.error = Number(p.error || 0)
        run.running = Number(p.running || 0)
        run.pending = Number(p.pending || 0)
        run.passRate = Number(p.pass_rate || 0)
        run.elapsed = Number(p.elapsed || 0)
        break
      }
      case 'eta_update': {
        run.eta = {
          eta_seconds: Number(p.eta_seconds || 0),
          remaining_seconds: Number(p.remaining_seconds || 0),
          confidence: String(p.confidence || 'medium') as 'high' | 'medium' | 'low',
          progress: Number(p.progress || 0),
        }
        break
      }
      case 'run_finished': {
        run.status = String(p.status || 'completed')
        run.passRate = Number(p.pass_rate || 0)
        run.elapsed = Number(p.duration || 0)
        run.passed = Number(p.passed || 0)
        run.failed = Number(p.failed || 0)
        run.skipped = Number(p.skipped || 0)
        run.error = Number(p.error || 0)
        run.running = 0
        run.pending = 0
        run.eta = null
        break
      }
    }
  }

  return { run, nodes }
}

const replayState = reactive<{ run: RunState; nodes: Map<number, NodeState> }>({
  run: emptyRunState(),
  nodes: new Map(),
})

const replayNodes = computed(() => Array.from(replayState.nodes.values()))

// 当 currentIndex 变化时重新折叠
watch(currentIndex, (idx) => {
  const result = reduceUpTo(idx)
  replayState.run = result.run
  replayState.nodes = result.nodes
})

// ─── Playback engine ───
function tick() {
  if (!playing.value) return
  if (currentIndex.value >= events.value.length - 1) {
    playing.value = false
    return
  }

  // 计算到下一个事件的间隔
  const cur = events.value[currentIndex.value]
  const next = events.value[currentIndex.value + 1]
  const deltaMs = new Date(next.created_at).getTime() - new Date(cur.created_at).getTime()
  const wait = Math.max(10, Math.min(deltaMs / speed.value, 2000))

  playTimer = setTimeout(() => {
    currentIndex.value++
    tick()
  }, wait)
}

function togglePlay() {
  if (playing.value) {
    pause()
  } else {
    play()
  }
}

function play() {
  if (currentIndex.value >= events.value.length - 1) {
    currentIndex.value = 0
  }
  playing.value = true
  tick()
}

function pause() {
  playing.value = false
  if (playTimer) {
    clearTimeout(playTimer)
    playTimer = null
  }
}

function seekTo(index: number) {
  pause()
  currentIndex.value = Math.max(0, Math.min(events.value.length - 1, index))
}

function onSpeedChange(newSpeed: number) {
  speed.value = newSpeed
}

function goBack() {
  router.push({ name: 'ExecutionDashboard' })
}

// ─── 初始化 ───
async function loadReplay() {
  loading.value = true
  pause()

  try {
    // 先尝试拿快照初始化 run 元数据
    const snap = await getRunSnapshot(runId.value)
    if (snap.success && snap.data) {
      replayState.run.runId = snap.data.run.id
      replayState.run.suiteName = snap.data.run.suite_name || ''
      replayState.run.executor = snap.data.run.executor || ''
    }

    // 拉取全部事件
    const allEvents = await getAllRunEvents(runId.value)
    events.value = allEvents
    const nextIndex = allEvents.length > 0 ? allEvents.length - 1 : 0
    currentIndex.value = nextIndex
    const result = reduceUpTo(nextIndex)
    replayState.run = result.run
    replayState.nodes = result.nodes
  } catch (e) {
    console.error('[Replay] load failed:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (runId.value) {
    loadReplay()
  }
})

onBeforeUnmount(() => {
  pause()
})

watch(runId, () => {
  if (runId.value) {
    loadReplay()
  }
})
</script>

<style scoped>
.exec-replay-view {
  height: 100%;
  background-color: var(--theme-page-bg);
  padding: 10px;
  box-sizing: border-box;
  overflow-y: auto;
}

.replay-spin {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

:deep(.arco-spin-children) {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.replay-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.replay-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--theme-text);
  margin: 0;
}

.suite-tag {
  font-size: 12px;
  color: var(--theme-text-secondary);
  background: var(--theme-surface-soft);
  padding: 2px 8px;
  border-radius: 8px;
}

.replay-stats-row {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 10px;
}

.replay-card {
  background: #ffffff;
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.pie-card {
  display: flex;
  align-items: center;
  gap: 14px;
}

.pie-legend {
  display: flex;
  flex-direction: column;
  gap: 3px;
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

.replay-section {
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

.replay-failed {
  margin-top: 0;
}

@media (max-width: 900px) {
  .replay-stats-row {
    grid-template-columns: 1fr;
  }
}
</style>
