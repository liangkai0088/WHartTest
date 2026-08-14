<template>
  <div class="run-list-panel">
    <div class="panel-header">
      <span class="panel-title">
        <icon-history class="title-icon" />
        {{ tl('执行记录') }}
      </span>
    </div>
    <div class="panel-body">
      <a-table
        :data="runs"
        :loading="loading"
        :pagination="false"
        :scroll="{ y: 260 }"
        size="small"
        :bordered="false"
        :stripe="true"
        row-key="id"
      >
        <template #columns>
          <a-table-column :title="tl('套件名称')" data-index="suite_detail">
            <template #cell="{ record }">
              {{ record.suite_detail?.name || `#${record.suite}` }}
            </template>
          </a-table-column>
          <a-table-column :title="tl('状态')" :width="90">
            <template #cell="{ record }">
              <span :class="['run-status-badge', `run-${record.status}`]">
                {{ runStatusLabel(record.status) }}
              </span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('通过率')" :width="80" align="center">
            <template #cell="{ record }">
              <span class="rate-text">{{ Math.round(record.pass_rate * 100) / 100 }}%</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('耗时')" :width="80" align="center">
            <template #cell="{ record }">
              {{ record.duration ? formatDuration(record.duration) : '—' }}
            </template>
          </a-table-column>
          <a-table-column :title="tl('操作')" :width="80" align="center">
            <template #cell="{ record }">
              <a-button type="text" size="mini" @click="goReplay(record.id)">
                <template #icon><icon-play-arrow /></template>
                {{ tl('回放') }}
              </a-button>
            </template>
          </a-table-column>
        </template>
      </a-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAppI18n } from '@/composables/useAppI18n'
import type { TestExecution } from '@/services/testExecutionService'

const { tl } = useAppI18n()
const router = useRouter()

defineProps<{
  runs: TestExecution[]
  loading: boolean
}>()

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

function goReplay(runId: number) {
  router.push({ name: 'ExecutionReplay', params: { runId: String(runId) } })
}
</script>

<style scoped>
.run-list-panel {
  background: #ffffff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 4px 0 10px rgba(0, 0, 0, 0.2), 0 4px 10px rgba(0, 0, 0, 0.2), 0 0 10px rgba(0, 0, 0, 0.15);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--theme-border);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--theme-text);
}

.title-icon {
  font-size: 16px;
  color: var(--theme-accent);
}

.panel-body {
  padding: 4px 8px;
}

.run-status-badge {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 8px;
  font-weight: 500;
}

.run-pending { background: rgba(134, 144, 156, 0.1); color: #86909c; }
.run-running { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }
.run-completed { background: rgba(82, 196, 26, 0.1); color: #52c41a; }
.run-failed { background: rgba(255, 77, 79, 0.1); color: #ff4d4f; }
.run-cancelled { background: rgba(250, 173, 20, 0.1); color: #d48806; }

.rate-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--theme-text);
  font-variant-numeric: tabular-nums;
}
</style>
