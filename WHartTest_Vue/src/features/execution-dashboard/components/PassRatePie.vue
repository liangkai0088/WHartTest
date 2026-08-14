<template>
  <div class="pass-rate-pie">
    <svg :viewBox="`0 0 ${size} ${size}`" class="pie-svg">
      <!-- 背景环 -->
      <circle
        :cx="center"
        :cy="center"
        :r="radius"
        class="pie-bg"
      />
      <!-- 各状态弧 -->
      <circle
        v-for="(seg, i) in segments"
        :key="i"
        :cx="center"
        :cy="center"
        :r="radius"
        class="pie-arc"
        :stroke="seg.color"
        :stroke-dasharray="`${seg.dash} ${circumference}`"
        :stroke-dashoffset="seg.offset"
      />
      <!-- 中心文字 -->
    </svg>
    <div class="pie-center">
      <span class="pie-value">{{ displayRate }}</span>
      <span class="pie-unit">%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  passed: number
  failed: number
  skipped: number
  errored: number
  total?: number
  size?: number
}>(), {
  total: 0,
  size: 120,
})

const STROKE = 10
const center = computed(() => props.size / 2)
const radius = computed(() => (props.size - STROKE) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)

const totalCount = computed(() => {
  if (props.total > 0) return props.total
  return props.passed + props.failed + props.skipped + props.errored
})

const displayRate = computed(() => {
  const t = totalCount.value
  if (t === 0) return 0
  return Math.round((props.passed / t) * 100)
})

const segments = computed(() => {
  const t = totalCount.value
  if (t === 0) return []

  const c = circumference.value
  const items = [
    { count: props.passed, color: '#52c41a' },
    { count: props.failed, color: '#ff4d4f' },
    { count: props.errored, color: '#b91c1c' },
    { count: props.skipped, color: '#faad14' },
  ].filter(i => i.count > 0)

  let accumulated = 0
  return items.map(item => {
    const ratio = item.count / t
    const dash = ratio * c
    // SVG circle starts at 3 o'clock; rotate via offset to start at 12
    const offset = c * 0.25 - accumulated
    accumulated += dash
    return { dash, offset, color: item.color }
  })
})
</script>

<style scoped>
.pass-rate-pie {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.pie-svg {
  width: 100%;
  height: 100%;
  transform: scaleX(-1);
}

.pie-bg {
  fill: none;
  stroke: var(--theme-surface-soft);
  stroke-width: 10;
}

.pie-arc {
  fill: none;
  stroke-width: 10;
  stroke-linecap: butt;
  transition: stroke-dasharray 0.5s ease, stroke-dashoffset 0.5s ease;
}

.pie-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  pointer-events: none;
}

.pie-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--theme-text);
  line-height: 1;
}

.pie-unit {
  font-size: 13px;
  color: var(--theme-text-tertiary);
}
</style>
