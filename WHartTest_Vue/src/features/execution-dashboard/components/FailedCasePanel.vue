<template>
  <div class="failed-panel">
    <div class="panel-header" @click="collapsed = !collapsed">
      <span class="panel-title">
        <icon-exclamation-circle-fill class="title-icon" />
        {{ tl('失败用例') }}
        <a-badge :count="failedNodes.length" :dot="false" class="count-badge" />
      </span>
      <icon-down :class="{ 'icon-rotated': !collapsed }" class="toggle-icon" />
    </div>

    <transition name="collapse">
      <div v-show="!collapsed" class="panel-body">
        <a-empty v-if="failedNodes.length === 0" :description="tl('暂无失败用例')" class="empty-state">
          <template #image>
            <icon-check-circle style="font-size: 36px; color: #52c41a;" />
          </template>
        </a-empty>

        <div v-else class="fail-list">
          <div
            v-for="node in failedNodes"
            :key="node.id"
            class="fail-item"
          >
            <div class="fail-header" @click="toggleExpand(node.id)">
              <span :class="['status-dot', `status-${node.status}`]" />
              <span class="fail-name">{{ node.name }}</span>
              <span :class="['status-badge', `badge-${node.status}`]">
                {{ statusLabel(node.status) }}
              </span>
              <span class="fail-duration" v-if="node.execution_time != null">
                {{ node.execution_time.toFixed(1) }}s
              </span>
              <icon-down :class="{ 'icon-rotated': expanded.has(node.id) }" class="expand-icon" />
            </div>
            <transition name="collapse">
              <div v-show="expanded.has(node.id)" class="fail-detail">
                <pre class="error-msg">{{ node.error_message || tl('无错误信息') }}</pre>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { useAppI18n } from '@/composables/useAppI18n'
import type { NodeState, NodeStatus } from '../types'

const { tl } = useAppI18n()

const props = defineProps<{
  nodes: NodeState[]
}>()

const collapsed = ref(false)
const expanded = reactive(new Set<number>())

const failedNodes = computed(() =>
  props.nodes.filter(n => n.status === 'fail' || n.status === 'error')
)

function toggleExpand(id: number) {
  if (expanded.has(id)) {
    expanded.delete(id)
  } else {
    expanded.add(id)
  }
}

function statusLabel(status: NodeStatus): string {
  const map: Record<string, string> = {
    fail: tl('失败'),
    error: tl('错误'),
    pass: tl('通过'),
    skip: tl('跳过'),
    running: tl('运行中'),
    pending: tl('等待中'),
  }
  return map[status] || status
}
</script>

<style scoped>
.failed-panel {
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
  cursor: pointer;
  border-bottom: 1px solid var(--theme-border);
  user-select: none;
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
  color: #ff4d4f;
  font-size: 16px;
}

.count-badge {
  margin-left: 4px;
}

.toggle-icon {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  transition: transform 0.2s;
}

.icon-rotated {
  transform: rotate(180deg);
}

.panel-body {
  padding: 8px 12px;
  max-height: 320px;
  overflow-y: auto;
}

.empty-state {
  padding: 24px 0;
}

.fail-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.fail-item {
  border-radius: 6px;
  overflow: hidden;
}

.fail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}

.fail-header:hover {
  background: var(--theme-surface-soft);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.status-fail { background: #ff4d4f; }
.status-dot.status-error { background: #b91c1c; }

.fail-name {
  flex: 1;
  font-size: 13px;
  color: var(--theme-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.status-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  flex-shrink: 0;
}

.badge-fail {
  background: rgba(255, 77, 79, 0.1);
  color: #ff4d4f;
}

.badge-error {
  background: rgba(185, 28, 28, 0.1);
  color: #b91c1c;
}

.fail-duration {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.expand-icon {
  font-size: 10px;
  color: var(--theme-text-tertiary);
  transition: transform 0.2s;
  flex-shrink: 0;
}

.fail-detail {
  padding: 0 10px 10px 26px;
}

.error-msg {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  background: var(--theme-surface-soft);
  padding: 8px 10px;
  border-radius: 4px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  max-height: 150px;
  overflow-y: auto;
  line-height: 1.5;
}

/* collapse transition */
.collapse-enter-active,
.collapse-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.collapse-enter-from,
.collapse-leave-to {
  max-height: 0;
  opacity: 0;
}

.collapse-enter-to,
.collapse-leave-from {
  max-height: 500px;
  opacity: 1;
}
</style>
