<template>
  <div class="self-healing-view">
    <div class="view-header">
      <h3 class="view-title">{{ tl('UID 自愈记录') }}</h3>
      <div class="view-actions">
        <a-statistic :title="tl('成功率')" :value="stats.success_rate" :precision="1" suffix="%" />
        <a-statistic :title="tl('自愈数')" :value="stats.status_counts?.healed || 0" />
        <a-statistic :title="tl('总记录')" :value="stats.total" />
      </div>
    </div>

    <a-card class="trend-card" size="small">
      <template #title>{{ tl('自愈成功率趋势') }}</template>
      <EChart v-if="trendPoints.length" :option="trendOption" height="240px" />
      <a-empty v-else :description="tl('暂无趋势数据')" />
    </a-card>

    <a-table :data="records" :loading="loading" row-key="id" :pagination="pagination"
      @page-change="onPageChange" @page-size-change="onPageSizeChange">
      <template #columns>
        <a-table-column title="ID" data-index="id" :width="70" />
        <a-table-column :title="tl('用例')" data-index="test_case_name" />
        <a-table-column :title="tl('元素')" data-index="element_name" :width="160" />
        <a-table-column :title="tl('失败信息')" data-index="failure_message" />
        <a-table-column :title="tl('状态')" :width="100">
          <template #cell="{ record }">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="tl('重跑成功')" :width="100">
          <template #cell="{ record }">
            <span v-if="record.rerun_success === null">-</span>
            <a-tag v-else :color="record.rerun_success ? 'green' : 'red'">
              {{ record.rerun_success ? tl('是') : tl('否') }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column :title="tl('重试')" :width="90">
          <template #cell="{ record }">{{ record.retry_count }} / {{ record.max_retry }}</template>
        </a-table-column>
        <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
        <a-table-column :title="tl('操作')" :width="100" fixed="right">
          <template #cell="{ record }">
            <a-button size="mini" @click="openDetail(record)">{{ tl('详情') }}</a-button>
          </template>
        </a-table-column>
      </template>
    </a-table>

    <a-drawer v-model:visible="detailVisible" :title="tl('自愈详情')" :width="560">
      <template v-if="currentRecord">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item :label="tl('失败信息')">{{ currentRecord.failure_message }}</a-descriptions-item>
          <a-descriptions-item :label="tl('诊断')">
            <pre class="detail-pre">{{ JSON.stringify(currentRecord.diagnosis || {}, null, 2) }}</pre>
          </a-descriptions-item>
          <a-descriptions-item :label="tl('回写摘要')">
            <pre class="detail-pre">{{ JSON.stringify(currentRecord.fix_summary || {}, null, 2) }}</pre>
          </a-descriptions-item>
        </a-descriptions>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted, computed } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAppI18n } from '@/composables/useAppI18n'
import { extractPaginationData, extractResponseData } from '../types'
import { selfHealingApi, type UiSelfHealingRecord, type UiSelfHealingStats, type UiSelfHealingTrendPoint } from '../api/selfHealing'
import EChart from '@/features/perf-test/components/EChart.vue'
import type { EChartsOption } from 'echarts'

const { locale, t, tl } = useAppI18n()

const records = ref<UiSelfHealingRecord[]>([])
const loading = ref(false)
const pagination = reactive({ current: 1, pageSize: 10, total: 0, showTotal: true })
const stats = reactive<Partial<UiSelfHealingStats>>({})

const statusLabel = (s: string) => ({ pending: tl('待诊断'), diagnosing: tl('诊断中'), healed: tl('已自愈'), failed: tl('自愈失败'), ignored: tl('已忽略') } as Record<string, string>)[s] || s
const statusColor = (s: string) => ({ pending: 'gray', diagnosing: 'blue', healed: 'green', failed: 'red', ignored: 'orange' } as Record<string, string>)[s] || 'gray'

async function fetchRecords() {
  loading.value = true
  try {
    const res = await selfHealingApi.list({})
    const { items, count } = extractPaginationData(res)
    records.value = items
    pagination.total = count
  } catch {
    Message.error(tl('加载自愈记录失败'))
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  try {
    const res = await selfHealingApi.stats()
    Object.assign(stats, extractResponseData<UiSelfHealingStats>(res))
  } catch {
    Message.error(tl('加载统计失败'))
  }
}

const trendPoints = ref<UiSelfHealingTrendPoint[]>([])
const trendOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', data: trendPoints.value.map((p) => p.date) },
  yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
  series: [{
    name: tl('成功率'),
    type: 'line',
    smooth: true,
    data: trendPoints.value.map((p) => p.success_rate),
    areaStyle: { opacity: 0.15 },
  }],
}))

async function fetchTrend() {
  try {
    const res = await selfHealingApi.trend()
    trendPoints.value = extractResponseData<UiSelfHealingTrendPoint[]>(res) || []
  } catch {
    Message.error(tl('加载趋势失败'))
  }
}

const onPageChange = (page: number) => { pagination.current = page; fetchRecords() }
const onPageSizeChange = (size: number) => { pagination.pageSize = size; pagination.current = 1; fetchRecords() }

const detailVisible = ref(false)
const currentRecord = ref<UiSelfHealingRecord | null>(null)
const openDetail = (record: UiSelfHealingRecord) => { currentRecord.value = record; detailVisible.value = true }

onMounted(() => { fetchRecords(); fetchStats(); fetchTrend() })
</script>

<style scoped>
.self-healing-view { padding: 16px 20px; }
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.view-title { margin: 0; font-size: 18px; }
.view-actions { display: flex; gap: 24px; }
.trend-card { margin-bottom: 14px; }
.detail-pre { margin: 0; background: var(--color-fill-2, #f5f5f5); padding: 10px; border-radius: 6px; max-height: 240px; overflow: auto; font-size: 12px; }
</style>
