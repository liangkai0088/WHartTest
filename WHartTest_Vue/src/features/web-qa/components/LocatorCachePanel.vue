<template>
  <div class="locator-cache-panel">
    <div class="panel-notice">
      <icon-info-circle class="notice-icon" />
      <span>{{ tl('仅语义引擎使用；视觉引擎缓存由 Midscene 自管理。') }}</span>
    </div>

    <div class="toolbar">
      <a-button size="small" :loading="store.cacheLoading" @click="handleRefresh">
        <template #icon><icon-refresh /></template>
        {{ tl('刷新') }}
      </a-button>
    </div>

    <a-spin :loading="store.cacheLoading">
      <a-table
        v-if="store.locatorCache.length > 0"
        :data="store.locatorCache"
        :pagination="false"
        size="small"
        :row-key="(r: any) => r.id"
        :bordered="false"
        :scroll="{ y: 420 }"
        row-class="cache-row"
      >
        <template #columns>
          <a-table-column :title="tl('描述')" :width="200">
            <template #cell="{ record }">
              <span class="cache-desc">{{ record.description }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('选择器')">
            <template #cell="{ record }">
              <code class="cache-selector">{{ record.selector }}</code>
            </template>
          </a-table-column>
          <a-table-column :title="tl('策略')" :width="100">
            <template #cell="{ record }">
              <a-tag :color="strategyColor(record.strategy)" size="small">
                {{ record.strategy }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('命中')" :width="70" align="center">
            <template #cell="{ record }">
              <span class="cache-hits">{{ record.hits }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('更新时间')" :width="140">
            <template #cell="{ record }">
              <span class="cache-time">{{ formatTime(record.updated_at) }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('操作')" :width="80" align="right">
            <template #cell="{ record }">
              <a-popconfirm
                :content="tl('确定删除此缓存条目？')"
                @ok="handleDelete(record)"
                position="left"
              >
                <a-button size="mini" status="danger">
                  {{ tl('删除') }}
                </a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </template>
      </a-table>
      <div v-else-if="!store.cacheLoading" class="empty-state">
        <a-empty>
          <template #image>
            <icon-storage style="font-size: 42px; color: var(--theme-empty-icon);" />
          </template>
          <template #description>
            <div>{{ tl('暂无定位缓存') }}</div>
            <div class="empty-hint">{{ tl('运行语义引擎测试后，定位结果会自动缓存。') }}</div>
          </template>
        </a-empty>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, onMounted } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconRefresh, IconInfoCircle, IconStorage } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useWebQaStore } from '../store/webQaStore';
import type { LocatorCacheEntry } from '../services/webQaService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useWebQaStore();

function strategyColor(s: string): string {
  switch (s) {
    case 'llm': return 'purple';
    case 'find': return 'arcoblue';
    case 'dom': return 'green';
    default: return 'gray';
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

async function handleRefresh() {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  await store.loadLocatorCache(pid);
  Message.success(tl('已刷新'));
}

async function handleDelete(entry: LocatorCacheEntry) {
  const pid = projectStore.currentProjectId;
  if (!pid) return;
  try {
    await store.deleteLocatorCache(pid, entry.id);
    Message.success(tl('已删除'));
  } catch (e: any) {
    Message.error(e.message || tl('删除失败'));
  }
}

const pid = computed(() => projectStore.currentProjectId);

watch(pid, async (val) => {
  if (val) await store.loadLocatorCache(val);
}, { immediate: true });
</script>

<style scoped>
.locator-cache-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(255, 125, 0, 0.06);
  border: 1px solid rgba(255, 125, 0, 0.15);
  border-radius: 8px;
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.notice-icon {
  color: #ff7d00;
  font-size: 15px;
}

.toolbar {
  display: flex;
  justify-content: flex-end;
}

.cache-desc {
  font-size: 13px;
  font-weight: 500;
  color: var(--theme-text);
}

.cache-selector {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  font-size: 12px;
  color: var(--theme-accent);
  background: rgba(var(--theme-accent-rgb), 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
}

.cache-hits {
  font-weight: 600;
  font-size: 13px;
  color: var(--theme-text);
}

.cache-time {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

.empty-state {
  padding: 60px 20px;
  text-align: center;
}

.empty-hint {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-top: 6px;
}
</style>
