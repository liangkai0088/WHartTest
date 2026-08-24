<template>
  <div class="change-impact-panel">
    <!-- Top actions row -->
    <div class="actions-row">
      <a-space>
        <a-button
          type="primary"
          size="small"
          :loading="store.changeAnalysisRunning"
          :disabled="!store.selectedProjectId"
          @click="handleAnalyze"
        >
          <template #icon><icon-swap /></template>
          {{ tl('分析代码变更') }}
        </a-button>
        <a-button size="small" :disabled="!store.selectedProjectId" @click="reloadImpacts">
          <template #icon><icon-refresh /></template>
        </a-button>
      </a-space>

      <!-- Last summary badge -->
      <div v-if="store.lastChangeSummary" class="summary-chips">
        <a-tag color="green" size="small">+{{ store.lastChangeSummary.added }}</a-tag>
        <a-tag color="arcoblue" size="small">~{{ store.lastChangeSummary.modified }}</a-tag>
        <a-tag color="red" size="small">-{{ store.lastChangeSummary.deleted }}</a-tag>
        <span class="summary-text">
          {{ store.lastChangeSummary.impacted_links }} {{ tl('影响链接') }}
        </span>
      </div>
    </div>

    <!-- Git import zone -->
    <div class="git-import-section">
      <div class="section-label">{{ tl('Git 导入') }}</div>
      <a-space>
        <a-input
          v-model="gitUrl"
          :placeholder="tl('Git 仓库 URL')"
          size="small"
          style="width: 280px"
        />
        <a-input
          v-model="gitBranch"
          :placeholder="tl('分支 (默认 main)')"
          size="small"
          style="width: 140px"
        />
        <a-button
          type="primary"
          size="small"
          :loading="store.gitImportRunning"
          :disabled="!gitUrl || !store.selectedProjectId"
          @click="handleGitImport"
        >
          {{ tl('导入') }}
        </a-button>
      </a-space>
    </div>

    <!-- Resolve filter -->
    <div class="filter-row">
      <a-radio-group v-model="resolvedFilter" type="button" size="small" @change="reloadImpacts">
        <a-radio value="unresolved">{{ tl('未处理') }}</a-radio>
        <a-radio value="all">{{ tl('全部') }}</a-radio>
        <a-radio value="resolved">{{ tl('已处理') }}</a-radio>
      </a-radio-group>
      <a-button
        size="small"
        :disabled="selectedIds.length === 0"
        :loading="bulkResolving"
        @click="handleBulkResolve"
      >
        {{ tl('批量标记已处理') }} ({{ selectedIds.length }})
      </a-button>
    </div>

    <!-- Impacts table -->
    <a-spin :loading="store.impactsLoading">
      <div v-if="filteredImpacts.length === 0 && !store.impactsLoading" class="empty-state">
        <a-empty :description="tl('暂无变更影响记录')" />
      </div>
      <a-table
        v-else
        :data="filteredImpacts"
        :pagination="false"
        size="small"
        :row-key="(r: any) => r.id"
        :bordered="false"
        :scroll="{ y: 360 }"
        :expanded-keys="expandedKeys"
        :expandable="rowExpandable"
        @expand="(key: number) => toggleExpand(key)"
      >
        <template #columns>
          <a-table-column :width="36">
            <template #cell="{ record }">
              <a-checkbox
                :model-value="selectedIds.includes(record.id)"
                :disabled="record.resolved"
                @change="(val: boolean) => toggleSelect(record.id, val)"
              />
            </template>
          </a-table-column>
          <a-table-column :title="tl('文件路径')" :width="240">
            <template #cell="{ record }">
              <span class="mono-path">{{ record.code_file_path }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('变更类型')" :width="90">
            <template #cell="{ record }">
              <a-tag :color="diffColor(record.diff_status)" size="small">
                {{ diffLabel(record.diff_status) }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('关联用例')">
            <template #cell="{ record }">
              <a-tag :color="typeColor(record.testcase_type)" size="small">
                {{ typeLabel(record.testcase_type) }}
              </a-tag>
              <span class="case-name">{{ record.testcase_name }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('Diff')" :width="100">
            <template #cell="{ record }">
              <template v-if="record.diff_summary?.hunks?.length">
                <span class="diff-stat added">+{{ hunkTotalAdded(record.diff_summary.hunks) }}</span>
                <span class="diff-stat removed">-{{ hunkTotalRemoved(record.diff_summary.hunks) }}</span>
              </template>
              <template v-else-if="record.diff_summary && isFallbackDiff(record.diff_summary)">
                <span class="diff-stat" :class="record.diff_summary.size_delta && record.diff_summary.size_delta > 0 ? 'added' : record.diff_summary.size_delta && record.diff_summary.size_delta < 0 ? 'removed' : ''">
                  {{ formatSizeDelta(record.diff_summary.size_delta) }}
                </span>
              </template>
              <span v-else class="no-diff">-</span>
            </template>
          </a-table-column>
          <a-table-column :title="tl('状态')" :width="80">
            <template #cell="{ record }">
              <a-tag v-if="record.resolved" color="green" size="small">{{ tl('已处理') }}</a-tag>
              <a-tag v-else color="orange" size="small">{{ tl('待处理') }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="tl('操作')" :width="80">
            <template #cell="{ record }">
              <a-button
                v-if="!record.resolved"
                type="text"
                size="small"
                @click.stop="handleResolve(record)"
              >
                {{ tl('标记已处理') }}
              </a-button>
              <span v-else class="resolved-text">{{ tl('已处理') }}</span>
            </template>
          </a-table-column>
        </template>

        <!-- Expandable diff detail -->
        <template #expand-row="{ record }">
          <div class="diff-expand" v-if="record.diff_summary">
            <!-- Hunk-based diff (git import) -->
            <template v-if="isHunkDiff(record.diff_summary)">
              <div class="hunk-list">
                <div
                  v-for="(hunk, idx) in visibleHunks(record.diff_summary.hunks!)"
                  :key="idx"
                  class="hunk-block"
                >
                  <div class="hunk-header">
                    <span class="hunk-range">@@ -{{ hunk.old_start }},{{ hunk.old_lines }} +{{ hunk.new_start }},{{ hunk.new_lines }} @@</span>
                    <span class="hunk-stats">
                      <span class="hunk-added">+{{ hunk.added }}</span>
                      <span class="hunk-removed">-{{ hunk.removed }}</span>
                    </span>
                  </div>
                </div>
                <div v-if="hiddenHunkCount(record.diff_summary.hunks!, record.diff_summary.truncated) > 0" class="hunk-truncated">
                  {{ tl('还有') }} {{ hiddenHunkCount(record.diff_summary.hunks!, record.diff_summary.truncated) }} {{ tl('个 hunk 未显示') }}
                </div>
              </div>
            </template>

            <!-- Fallback diff (zip upload) -->
            <template v-else-if="isFallbackDiff(record.diff_summary)">
              <div class="fallback-diff">
                <div class="fallback-row">
                  <span class="fallback-label">{{ tl('旧版本') }}</span>
                  <a-tooltip :content="record.diff_summary.old_sha256 || tl('无')">
                    <span class="mono-sha">{{ shortSha(record.diff_summary.old_sha256) }}</span>
                  </a-tooltip>
                </div>
                <div class="fallback-row">
                  <span class="fallback-label">{{ tl('新版本') }}</span>
                  <a-tooltip :content="record.diff_summary.new_sha256 || tl('无')">
                    <span class="mono-sha">{{ shortSha(record.diff_summary.new_sha256) }}</span>
                  </a-tooltip>
                </div>
                <div class="fallback-row" v-if="record.diff_summary.size_delta !== undefined">
                  <span class="fallback-label">{{ tl('大小变化') }}</span>
                  <span class="fallback-value">{{ formatSizeDelta(record.diff_summary.size_delta) }}</span>
                </div>
              </div>
            </template>

            <template v-else>
              <span class="no-diff-detail">{{ tl('无 diff 详情') }}</span>
            </template>
          </div>
        </template>
      </a-table>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconSwap, IconRefresh } from '@arco-design/web-vue/es/icon';
import { useAppI18n } from '@/composables/useAppI18n';
import { useProjectStore } from '@/store/projectStore';
import { useCodeAnalysisStore } from '../store/codeAnalysisStore';
import type { ChangeImpactRecord, DiffSummary, DiffHunk } from '../services/codeAnalysisService';

const { tl } = useAppI18n();
const projectStore = useProjectStore();
const store = useCodeAnalysisStore();

const gitUrl = ref('');
const gitBranch = ref('');
const resolvedFilter = ref('unresolved');
const selectedIds = ref<number[]>([]);
const bulkResolving = ref(false);
const expandedKeys = ref<number[]>([]);

const MAX_VISIBLE_HUNKS = 10;

const filteredImpacts = computed(() => {
  if (resolvedFilter.value === 'unresolved') return store.impacts.filter((i) => !i.resolved);
  if (resolvedFilter.value === 'resolved') return store.impacts.filter((i) => i.resolved);
  return store.impacts;
});

// Only show expand icon for rows that have diff data
const rowExpandable = (record: ChangeImpactRecord): boolean => {
  return hasDiffData(record);
};

function hasDiffData(record: ChangeImpactRecord): boolean {
  const ds = record.diff_summary;
  if (!ds) return false;
  if (ds.hunks && ds.hunks.length > 0) return true;
  if (ds.old_sha256 || ds.new_sha256 || ds.size_delta !== undefined) return true;
  return false;
}

function isHunkDiff(ds: DiffSummary): boolean {
  return !!(ds.hunks && ds.hunks.length > 0);
}

function isFallbackDiff(ds: DiffSummary): boolean {
  return !!(ds.old_sha256 || ds.new_sha256 || ds.size_delta !== undefined) && !isHunkDiff(ds);
}

function visibleHunks(hunks: DiffHunk[]): DiffHunk[] {
  return hunks.slice(0, MAX_VISIBLE_HUNKS);
}

function hiddenHunkCount(hunks: DiffHunk[], truncated?: boolean): number {
  if (hunks.length > MAX_VISIBLE_HUNKS) return hunks.length - MAX_VISIBLE_HUNKS;
  if (truncated) return 1; // backend flagged truncation but count unknown
  return 0;
}

function shortSha(sha?: string): string {
  if (!sha) return '-';
  return sha.slice(0, 8);
}

function formatSizeDelta(bytes?: number): string {
  if (bytes === undefined || bytes === null) return '-';
  const abs = Math.abs(bytes);
  const sign = bytes >= 0 ? '+' : '-';
  if (abs < 1024) return `${sign}${abs}B`;
  if (abs < 1024 * 1024) return `${sign}${(abs / 1024).toFixed(1)}KB`;
  return `${sign}${(abs / (1024 * 1024)).toFixed(1)}MB`;
}

function diffColor(s: string): string {
  switch (s) {
    case 'added': return 'green';
    case 'modified': return 'arcoblue';
    case 'deleted': return 'red';
    default: return 'gray';
  }
}

function diffLabel(s: string): string {
  switch (s) {
    case 'added': return tl('新增');
    case 'modified': return tl('修改');
    case 'deleted': return tl('删除');
    default: return s;
  }
}

function typeColor(t: string): string {
  switch (t) {
    case 'api': return 'arcoblue';
    case 'ui': return 'purple';
    case 'functional': return 'green';
    default: return 'gray';
  }
}

function typeLabel(t: string): string {
  switch (t) {
    case 'api': return 'API';
    case 'ui': return 'UI';
    case 'functional': return tl('功能');
    default: return t;
  }
}

function toggleSelect(id: number, val: boolean | (string | number | boolean)[]) {
  if (val) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id);
  } else {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  }
}

function toggleExpand(key: number) {
  const idx = expandedKeys.value.indexOf(key);
  if (idx >= 0) {
    expandedKeys.value.splice(idx, 1);
  } else {
    expandedKeys.value.push(key);
  }
}

function hunkTotalAdded(hunks: DiffHunk[]): number {
  return hunks.reduce((sum, h) => sum + h.added, 0);
}

function hunkTotalRemoved(hunks: DiffHunk[]): number {
  return hunks.reduce((sum, h) => sum + h.removed, 0);
}

async function reloadImpacts() {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  await store.loadImpacts(pid, cpId);
}

async function handleAnalyze() {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  try {
    const summary = await store.analyzeChanges(pid, cpId);
    Message.success(
      `${tl('变更分析完成')}: +${summary.added} ~${summary.modified} -${summary.deleted}, ${summary.impacted_links} ${tl('影响链接')}`,
    );
  } catch (e: any) {
    Message.error(e.message || tl('分析失败'));
  }
}

async function handleGitImport() {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId || !gitUrl.value) return;
  try {
    const result = await store.gitImport(pid, cpId, gitUrl.value, gitBranch.value || undefined);
    Message.success(`${tl('Git 导入成功')}, snapshot #${result.snapshot_id}`);
    gitUrl.value = '';
    gitBranch.value = '';
  } catch (e: any) {
    Message.error(e.message || tl('导入失败'));
  }
}

async function handleResolve(record: ChangeImpactRecord) {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  try {
    await store.resolveImpact(pid, cpId, record.id);
    Message.success(tl('已标记为已处理'));
  } catch (e: any) {
    Message.error(e.message || tl('操作失败'));
  }
}

async function handleBulkResolve() {
  const pid = projectStore.currentProjectId;
  const cpId = store.selectedProjectId;
  if (!pid || !cpId) return;
  bulkResolving.value = true;
  try {
    let ok = 0;
    for (const id of selectedIds.value) {
      try {
        await store.resolveImpact(pid, cpId, id);
        ok++;
      } catch { /* skip individual failures */ }
    }
    Message.success(`${tl('批量标记已处理')}: ${ok}/${selectedIds.value.length}`);
    selectedIds.value = [];
  } finally {
    bulkResolving.value = false;
  }
}

// Auto-load impacts when selected project changes
watch(
  () => store.selectedProjectId,
  async (cpId) => {
    const pid = projectStore.currentProjectId;
    if (pid && cpId) {
      await store.loadImpacts(pid, cpId);
    }
  },
  { immediate: true },
);
</script>

<style scoped>
.change-impact-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.actions-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-chips {
  display: flex;
  align-items: center;
  gap: 4px;
}

.summary-text {
  font-size: 12px;
  color: var(--theme-text-tertiary);
  margin-left: 4px;
}

.git-import-section {
  padding: 10px 14px;
  background: var(--theme-surface-soft);
  border-radius: 8px;
}

.section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-text-secondary);
  margin-bottom: 6px;
}

.filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.mono-path {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text);
}

.case-name {
  font-size: 12px;
  color: var(--theme-text-secondary);
  margin-left: 4px;
}

.resolved-text {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}

/* ── Diff column stats ── */
.diff-stat {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
}

.diff-stat.added {
  color: #16a34a;
}

.diff-stat.removed {
  color: #dc2626;
}

.diff-stat.added + .diff-stat.removed {
  margin-left: 6px;
}

.no-diff {
  color: var(--theme-text-tertiary);
  font-size: 12px;
}

/* ── Expandable diff detail ── */
.diff-expand {
  padding: 8px 12px 12px;
}

.hunk-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hunk-block {
  background: var(--theme-surface-soft);
  border: 1px solid var(--theme-border);
  border-radius: 4px;
  overflow: hidden;
}

.hunk-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-family: monospace;
  font-size: 12px;
}

.hunk-range {
  color: var(--theme-accent);
  font-weight: 500;
}

.hunk-stats {
  display: flex;
  gap: 8px;
}

.hunk-added {
  color: #16a34a;
  font-weight: 600;
}

.hunk-removed {
  color: #dc2626;
  font-weight: 600;
}

.hunk-truncated {
  font-size: 11px;
  color: var(--theme-text-tertiary);
  padding: 4px 10px;
  text-align: center;
}

/* Fallback diff (zip) */
.fallback-diff {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.fallback-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fallback-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--theme-text-secondary);
  width: 64px;
  flex-shrink: 0;
}

.mono-sha {
  font-family: monospace;
  font-size: 12px;
  color: var(--theme-text);
  cursor: help;
}

.fallback-value {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-text);
}

.no-diff-detail {
  font-size: 12px;
  color: var(--theme-text-tertiary);
}
</style>
