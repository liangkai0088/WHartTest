<template>
  <div class="eta-bar">
    <div class="eta-header">
      <span class="eta-label">{{ tl('预计完成') }}</span>
      <div class="eta-meta">
        <span class="eta-remaining">{{ remainingText }}</span>
        <span :class="['eta-confidence', `confidence-${confidence}`]">{{ confidenceText }}</span>
      </div>
    </div>
    <div class="eta-track">
      <div class="eta-fill" :style="{ width: progressPercent + '%' }" />
    </div>
    <div class="eta-footer">
      <span class="eta-progress">{{ progressPercent }}%</span>
      <span class="eta-eta-text">{{ etaText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAppI18n } from '@/composables/useAppI18n'

const { tl } = useAppI18n()

const props = withDefaults(defineProps<{
  progress: number
  remainingSeconds: number
  etaSeconds: number
  confidence: 'high' | 'medium' | 'low'
}>(), {
  progress: 0,
  remainingSeconds: 0,
  etaSeconds: 0,
  confidence: 'medium',
})

const progressPercent = computed(() => Math.round(props.progress * 100))

const remainingText = computed(() => {
  return formatDuration(props.remainingSeconds)
})

const etaText = computed(() => {
  if (props.etaSeconds <= 0) return ''
  const mins = Math.floor(props.etaSeconds / 60)
  const secs = Math.round(props.etaSeconds % 60)
  return tl('总预计') + ' ' + mins + ':' + String(secs).padStart(2, '0')
})

const confidenceText = computed(() => {
  const map: Record<string, string> = {
    high: tl('高置信'),
    medium: tl('中置信'),
    low: tl('低置信'),
  }
  return map[props.confidence] || props.confidence
})

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '00:00'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
</script>

<style scoped>
.eta-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.eta-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.eta-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--theme-text-secondary);
}

.eta-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.eta-remaining {
  font-size: 14px;
  font-weight: 600;
  color: var(--theme-text);
  font-variant-numeric: tabular-nums;
}

.eta-confidence {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  font-weight: 500;
}

.confidence-high {
  background: rgba(82, 196, 26, 0.12);
  color: #52c41a;
}

.confidence-medium {
  background: rgba(250, 173, 20, 0.12);
  color: #d48806;
}

.confidence-low {
  background: rgba(255, 77, 79, 0.12);
  color: #ff4d4f;
}

.eta-track {
  height: 6px;
  background: var(--theme-surface-soft);
  border-radius: 3px;
  overflow: hidden;
}

.eta-fill {
  height: 100%;
  background: var(--theme-accent);
  border-radius: 3px;
  transition: width 0.4s ease;
}

.eta-footer {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.eta-progress {
  font-weight: 600;
  color: var(--theme-accent);
}

.eta-eta-text {
  font-variant-numeric: tabular-nums;
}
</style>
