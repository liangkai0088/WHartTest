<template>
  <div class="playback-controls">
    <div class="controls-main">
      <!-- 播放/暂停 -->
      <a-button
        :type="playing ? 'outline' : 'primary'"
        size="small"
        shape="circle"
        @click="togglePlay"
        class="play-btn"
      >
        <template #icon>
          <icon-pause v-if="playing" />
          <icon-play-arrow v-else />
        </template>
      </a-button>

      <!-- 时间显示 -->
      <span class="time-display">
        {{ formatTime(currentIndex) }} / {{ formatTime(totalEvents) }}
      </span>

      <!-- 进度条 -->
      <div class="progress-wrapper" @click="seekFromClick">
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }" />
          <div class="progress-thumb" :style="{ left: progressPercent + '%' }" />
        </div>
      </div>
    </div>

    <!-- 速度控制 -->
    <div class="speed-group">
      <span class="speed-label">{{ tl('速度') }}</span>
      <a-radio-group
        :model-value="speed"
        type="button"
        size="mini"
        @change="onSpeedChange"
        class="speed-radio"
      >
        <a-radio :value="0.5">0.5×</a-radio>
        <a-radio :value="1">1×</a-radio>
        <a-radio :value="2">2×</a-radio>
        <a-radio :value="4">4×</a-radio>
      </a-radio-group>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAppI18n } from '@/composables/useAppI18n'

const { tl } = useAppI18n()

const props = defineProps<{
  playing: boolean
  currentIndex: number
  totalEvents: number
  speed: number
}>()

const emit = defineEmits<{
  (e: 'toggle-play'): void
  (e: 'seek', index: number): void
  (e: 'speed-change', speed: number): void
}>()

const progressPercent = computed(() => {
  if (props.totalEvents <= 0) return 0
  return Math.min(100, (props.currentIndex / props.totalEvents) * 100)
})

function formatTime(index: number): string {
  return `${index}`
}

function togglePlay() {
  emit('toggle-play')
}

function seekFromClick(e: MouseEvent) {
  const target = e.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  const index = Math.round(ratio * props.totalEvents)
  emit('seek', index)
}

function onSpeedChange(val: number | string | boolean) {
  emit('speed-change', Number(val))
}
</script>

<style scoped>
.playback-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 20px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.controls-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.play-btn {
  flex-shrink: 0;
}

.time-display {
  font-size: 13px;
  color: var(--theme-text);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  flex-shrink: 0;
}

.progress-wrapper {
  flex: 1;
  min-width: 80px;
  cursor: pointer;
  padding: 8px 0;
}

.progress-track {
  position: relative;
  height: 4px;
  background: var(--theme-surface-soft);
  border-radius: 2px;
}

.progress-fill {
  height: 100%;
  background: var(--theme-accent);
  border-radius: 2px;
  transition: width 0.1s linear;
}

.progress-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: var(--theme-accent);
  border: 2px solid #ffffff;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
  transition: left 0.1s linear;
}

.speed-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.speed-label {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.speed-radio {
  background: var(--theme-surface-soft) !important;
  border-radius: 6px;
  padding: 1px;
}
</style>
