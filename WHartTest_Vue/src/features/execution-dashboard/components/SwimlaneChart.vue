<template>
  <div class="swimlane-chart" ref="containerRef">
    <!-- 空态 -->
    <a-empty v-if="nodeList.length === 0" :description="tl('暂无执行数据')" class="swimlane-empty">
      <template #image>
        <icon-bar-chart style="font-size: 40px; color: var(--theme-text-tertiary);" />
      </template>
    </a-empty>

    <template v-else>
      <!-- 时间轴头部 -->
      <div class="swimlane-header">
        <div class="name-col-header">{{ tl('用例名称') }}</div>
        <div class="timeline-col-header" ref="timelineHeaderRef">
          <svg :width="timelineWidth" :height="28" class="axis-svg">
            <g v-for="tick in timeTicks" :key="tick.label">
              <line :x1="tick.x" :x2="tick.x" y1="18" y2="28" class="tick-line" />
              <text :x="tick.x" y="14" class="tick-label">{{ tick.label }}</text>
            </g>
          </svg>
        </div>
      </div>

      <!-- 泳道体 -->
      <div class="swimlane-body" ref="bodyRef">
        <div
          v-for="node in nodeList"
          :key="node.id"
          class="swimlane-row"
        >
          <!-- 名称列 -->
          <div class="name-col" :title="node.name">
            <span :class="['row-status-dot', `dot-${node.status}`]" />
            <span class="row-name">{{ node.name }}</span>
          </div>

          <!-- 时间线列 -->
          <div class="timeline-col">
            <svg :width="timelineWidth" :height="laneHeight" class="lane-svg">
              <!-- 网格参考线 -->
              <line
                v-for="tick in timeTicks"
                :key="'grid-' + tick.label"
                :x1="tick.x" :x2="tick.x"
                y1="0" :y2="laneHeight"
                class="grid-line"
              />

              <!-- 执行条 -->
              <g v-if="getNodeBar(node)" :transform="`translate(0, ${lanePad})`">
                <rect
                  :x="getNodeBar(node)!.x"
                  :y="0"
                  :width="getNodeBar(node)!.width"
                  :height="barHeight"
                  :rx="3"
                  :class="['bar', `bar-${node.status}`, { 'bar-pulse': node.status === 'running' }]"
                />
                <text
                  v-if="getNodeBar(node)!.width > 30"
                  :x="getNodeBar(node)!.x + 6"
                  :y="barHeight / 2 + 4"
                  class="bar-text"
                >{{ node.execution_time != null ? node.execution_time.toFixed(1) + 's' : '' }}</text>
              </g>

              <!-- 无开始时间的状态芯片 -->
              <g v-if="!node.started_at && node.status !== 'pending'" :transform="`translate(0, ${lanePad})`">
                <rect
                  x="4"
                  y="0"
                  :width="barHeight"
                  :height="barHeight"
                  :rx="3"
                  :class="['bar', `bar-${node.status}`]"
                />
              </g>

              <!-- pending 灰色占位 -->
              <g v-if="node.status === 'pending'" :transform="`translate(0, ${lanePad})`">
                <rect
                  x="4"
                  y="0"
                  :width="12"
                  :height="barHeight"
                  rx="3"
                  class="bar bar-pending"
                />
              </g>
            </svg>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useAppI18n } from '@/composables/useAppI18n'
import type { NodeState, NodeStatus } from '../types'

const { tl } = useAppI18n()

const props = defineProps<{
  nodes: NodeState[]
  startedAt?: string
  elapsed?: number
}>()

const laneHeight = 32
const barHeight = 22
const lanePad = (laneHeight - barHeight) / 2
const nameColWidth = 220

const containerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const timelineHeaderRef = ref<HTMLElement | null>(null)
const timelineWidth = ref(600)

const nodeList = computed(() => {
  // 按开始时间排序，无开始时间的放后面
  return [...props.nodes].sort((a, b) => {
    if (a.started_at && b.started_at) {
      return new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
    }
    if (a.started_at) return -1
    if (b.started_at) return 1
    return 0
  })
})

/** 计算时间轴范围 */
const timeRange = computed(() => {
  const startMs = props.startedAt ? new Date(props.startedAt).getTime() : null

  let minTime = Infinity
  let maxTime = -Infinity

  for (const node of props.nodes) {
    if (node.started_at) {
      const s = new Date(node.started_at).getTime()
      minTime = Math.min(minTime, s)
      const e = node.completed_at
        ? new Date(node.completed_at).getTime()
        : (node.execution_time != null ? s + node.execution_time * 1000 : s + 1000)
      maxTime = Math.max(maxTime, e)
    }
  }

  // 如果有 elapsed，用 startedAt + elapsed 作为 maxTime
  if (startMs && props.elapsed) {
    maxTime = Math.max(maxTime, startMs + props.elapsed * 1000)
  }

  // 正在运行：用当前时间作为上限
  if (maxTime === -Infinity && startMs) {
    maxTime = Date.now()
  }

  if (minTime === Infinity || maxTime === -Infinity) {
    return { start: Date.now(), end: Date.now() + 60000, duration: 60000 }
  }

  // 至少10秒跨度
  const duration = Math.max(maxTime - minTime, 10000)
  return { start: minTime, end: minTime + duration, duration }
})

/** 时间刻度 */
const timeTicks = computed(() => {
  const { start, end, duration } = timeRange.value
  const ticks: Array<{ x: number; label: string }> = []
  const w = timelineWidth.value

  // 智能选择间隔
  const niceIntervals = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600]
  const durationSec = duration / 1000
  let interval = 1
  for (const ni of niceIntervals) {
    if (durationSec / ni <= 10) {
      interval = ni
      break
    }
  }

  const startSec = Math.floor(start / 1000 / interval) * interval
  for (let t = startSec; t <= end / 1000 + interval; t += interval) {
    const ms = t * 1000
    if (ms < start - interval * 500 || ms > end + interval * 500) continue
    const x = ((ms - start) / duration) * w
    const elapsed = t - Math.floor(start / 1000)
    const label = formatTimeLabel(elapsed)
    ticks.push({ x, label })
  }

  return ticks
})

function formatTimeLabel(seconds: number): string {
  if (seconds < 0) seconds = 0
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

interface BarInfo { x: number; width: number }

function getNodeBar(node: NodeState): BarInfo | null {
  if (!node.started_at) return null

  const { start, duration } = timeRange.value
  const w = timelineWidth.value
  const s = new Date(node.started_at).getTime()
  let e: number

  if (node.completed_at) {
    e = new Date(node.completed_at).getTime()
  } else if (node.execution_time != null) {
    e = s + node.execution_time * 1000
  } else {
    // running — extend to now
    e = Date.now()
  }

  const x = ((s - start) / duration) * w
  const barW = Math.max(4, ((e - s) / duration) * w)

  return { x: Math.max(0, x), width: barW }
}

/** 响应窗口大小 */
function updateWidth() {
  if (containerRef.value) {
    const containerW = containerRef.value.clientWidth
    timelineWidth.value = Math.max(300, containerW - nameColWidth - 2)
  }
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  updateWidth()
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(updateWidth)
    resizeObserver.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
})

watch(() => props.nodes.length, updateWidth)
</script>

<style scoped>
.swimlane-chart {
  background: #ffffff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.swimlane-empty {
  padding: 40px 0;
}

.swimlane-header {
  display: flex;
  border-bottom: 1px solid var(--theme-border);
  background: var(--theme-surface-soft);
}

.name-col-header {
  width: 220px;
  min-width: 220px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-text-secondary);
}

.timeline-col-header {
  flex: 1;
  overflow: hidden;
}

.axis-svg {
  display: block;
}

.tick-line {
  stroke: var(--theme-border);
  stroke-width: 1;
}

.tick-label {
  font-size: 10px;
  fill: var(--theme-text-tertiary);
  text-anchor: middle;
  font-variant-numeric: tabular-nums;
}

.swimlane-body {
  max-height: 500px;
  overflow-y: auto;
  overflow-x: hidden;
}

.swimlane-row {
  display: flex;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  transition: background 0.15s;
}

.swimlane-row:hover {
  background: rgba(var(--theme-accent-rgb), 0.03);
}

.swimlane-row:last-child {
  border-bottom: none;
}

.name-col {
  width: 220px;
  min-width: 220px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--theme-text);
  overflow: hidden;
  white-space: nowrap;
}

.row-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dot-pass { background: #52c41a; }
.dot-fail { background: #ff4d4f; }
.dot-error { background: #b91c1c; }
.dot-skip { background: #faad14; }
.dot-running { background: #3b82f6; animation: dot-pulse 1.5s ease-in-out infinite; }
.dot-pending { background: #86909c; }

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.row-name {
  overflow: hidden;
  text-overflow: ellipsis;
}

.timeline-col {
  flex: 1;
  min-width: 0;
}

.lane-svg {
  display: block;
}

.grid-line {
  stroke: var(--theme-border);
  stroke-width: 0.5;
  stroke-dasharray: 2 4;
  opacity: 0.5;
}

.bar {
  transition: width 0.3s ease;
}

.bar-pass { fill: #52c41a; }
.bar-fail { fill: #ff4d4f; }
.bar-error { fill: #b91c1c; }
.bar-skip { fill: #faad14; }
.bar-running { fill: #3b82f6; }
.bar-pending { fill: #86909c; opacity: 0.4; }

.bar-pulse {
  animation: bar-pulse 1.8s ease-in-out infinite;
}

@keyframes bar-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

.bar-text {
  font-size: 10px;
  fill: #ffffff;
  font-weight: 500;
  pointer-events: none;
}
</style>
