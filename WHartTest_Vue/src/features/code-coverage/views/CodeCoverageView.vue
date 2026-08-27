<template>
  <div class="coverage-view">
    <div class="view-header">
      <h3 class="view-title">{{ tl('代码覆盖率') }}</h3>
      <div class="view-actions">
        <a-select v-model="statusFilter" :placeholder="tl('全部状态')" allow-clear style="width: 140px" @change="onSearch">
          <a-option value="completed">{{ tl('已完成') }}</a-option>
          <a-option value="failed">{{ tl('失败') }}</a-option>
          <a-option value="processing">{{ tl('处理中') }}</a-option>
        </a-select>
        <a-button @click="onSearch">{{ tl('刷新') }}</a-button>
        <a-button type="primary" @click="openUpload">{{ tl('上传报告') }}</a-button>
      </div>
    </div>

    <a-card class="gate-card" size="small">
      <template #title>{{ tl('覆盖率门禁') }}</template>
      <a-space>
        <span>{{ tl('启用') }}</span>
        <a-switch v-model="gateConfig.enabled" />
        <span>{{ tl('最小行覆盖率阈值(%)') }}</span>
        <a-input-number v-model="gateConfig.min_line_coverage" :min="0" :max="100" :step="1" style="width: 110px" />
        <a-button type="primary" :loading="gateSaving" @click="saveGate">{{ tl('保存') }}</a-button>
      </a-space>
    </a-card>

    <a-tabs :key="`coverage-tabs-${locale}`" v-model:active-key="activeTab" type="card-gutter">
      <a-tab-pane key="reports" :title="tl('覆盖率报表')">
        <a-table :data="reports" :loading="reportLoading" row-key="id" :pagination="pagination"
          @page-change="onPageChange" @page-size-change="onPageSizeChange">
          <template #columns>
            <a-table-column :title="tl('名称')" data-index="name" />
            <a-table-column :title="tl('格式')" data-index="format" :width="110" />
            <a-table-column :title="tl('测试类型')" data-index="test_type" :width="100" />
            <a-table-column :title="tl('行覆盖率%')" :width="110">
              <template #cell="{ record }">{{ record.summary?.line_coverage ?? '-' }}</template>
            </a-table-column>
            <a-table-column :title="tl('门禁')" :width="90">
              <template #cell="{ record }">
                <span v-if="!gateConfig.enabled">-</span>
                <a-tag v-else :color="isGatePassed(record) ? 'green' : 'red'">
                  {{ isGatePassed(record) ? tl('通过') : tl('阻断') }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="tl('文件数')" :width="90">
              <template #cell="{ record }">{{ record.file_count }}</template>
            </a-table-column>
            <a-table-column :title="tl('状态')" :width="100">
              <template #cell="{ record }">
                <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="tl('提交')" data-index="git_commit" :width="120" />
            <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
            <a-table-column :title="tl('操作')" :width="170" fixed="right">
              <template #cell="{ record }">
                <a-space>
                  <a-button size="mini" @click="openDetail(record)">{{ tl('详情') }}</a-button>
                  <a-button size="mini" @click="openDelta(record)">{{ tl('增量') }}</a-button>
                </a-space>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="deltas" :title="tl('增量覆盖率')">
        <a-table :data="deltas" :loading="deltaLoading" row-key="id" :pagination="false">
          <template #columns>
            <a-table-column :title="tl('提交')" data-index="git_commit" :width="140" />
            <a-table-column :title="tl('基线')" data-index="base_commit" :width="140" />
            <a-table-column :title="tl('新增行')" :width="90">
              <template #cell="{ record }">{{ record.summary?.new_lines_total }}</template>
            </a-table-column>
            <a-table-column :title="tl('新增覆盖行')" :width="110">
              <template #cell="{ record }">{{ record.summary?.covered_new_lines }}</template>
            </a-table-column>
            <a-table-column :title="tl('增量覆盖率%')" :width="120">
              <template #cell="{ record }">{{ record.summary?.delta_coverage }}</template>
            </a-table-column>
            <a-table-column :title="tl('变更文件')" :width="90">
              <template #cell="{ record }">
                {{ (record.summary?.files_added || 0) + (record.summary?.files_modified || 0) + (record.summary?.files_removed || 0) }}
              </template>
            </a-table-column>
            <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
          </template>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <!-- 上传报告 -->
    <a-modal v-model:visible="uploadVisible" :title="tl('上传覆盖率报告')" @ok="submitUpload" @cancel="uploadVisible = false">
      <a-form :model="uploadForm" layout="vertical">
        <a-form-item :label="tl('报告名称')" required>
          <a-input v-model="uploadForm.name" />
        </a-form-item>
        <a-form-item :label="tl('格式')">
          <a-select v-model="uploadForm.format">
            <a-option value="cobertura">Cobertura</a-option>
            <a-option value="lcov">LCOV</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('测试类型')">
          <a-select v-model="uploadForm.test_type">
            <a-option value="api">{{ tl('API') }}</a-option>
            <a-option value="ui">{{ tl('UI') }}</a-option>
            <a-option value="unit">{{ tl('单元') }}</a-option>
            <a-option value="manual">{{ tl('手工') }}</a-option>
          </a-select>
        </a-form-item>
        <a-form-item :label="tl('提交哈希')">
          <a-input v-model="uploadForm.git_commit" />
        </a-form-item>
        <a-form-item :label="tl('覆盖率文件')" required>
          <a-upload :file-list="fileList" :limit="1" :auto-upload="false" accept=".xml,.info"
            @change="onFileChange">
            <template #upload-button>
              <a-button>{{ tl('选择文件') }}</a-button>
            </template>
          </a-upload>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 报告详情 -->
    <a-drawer v-model:visible="detailVisible" :title="tl('覆盖率报表详情')" :width="680">
      <template v-if="currentReport">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item :label="tl('文件数')">{{ currentReport.file_count }}</a-descriptions-item>
          <a-descriptions-item :label="tl('总行数')">{{ currentReport.summary?.lines_total }}</a-descriptions-item>
          <a-descriptions-item :label="tl('覆盖行数')">{{ currentReport.summary?.lines_covered }}</a-descriptions-item>
          <a-descriptions-item :label="tl('行覆盖率%')">{{ currentReport.summary?.line_coverage }}</a-descriptions-item>
          <a-descriptions-item :label="tl('分支覆盖%')">{{ currentReport.summary?.branch_coverage }}</a-descriptions-item>
          <a-descriptions-item :label="tl('提交哈希')">{{ currentReport.git_commit || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="tl('门禁')">
            <a-tag v-if="currentReport.gate?.enabled" :color="currentReport.gate.passed ? 'green' : 'red'">
              {{ currentReport.gate.passed ? tl('通过') : tl('阻断') }}
              ({{ currentReport.gate.threshold }}%)
            </a-tag>
            <span v-else>-</span>
          </a-descriptions-item>
        </a-descriptions>
        <h4 class="subsection-title">{{ tl('覆盖率概览') }}</h4>
        <a-row :gutter="16">
          <a-col :span="12">
            <div class="cov-progress">
              <span>{{ tl('行覆盖率') }}</span>
              <a-progress :percent="currentReport.summary?.line_coverage || 0" :stroke-width="14" />
            </div>
          </a-col>
          <a-col :span="12">
            <div class="cov-progress">
              <span>{{ tl('分支覆盖率') }}</span>
              <a-progress :percent="currentReport.summary?.branch_coverage || 0" :stroke-width="14" />
            </div>
          </a-col>
        </a-row>
        <h4 class="subsection-title">{{ tl('文件覆盖率分布') }}</h4>
        <EChart :option="filesBucketOption" height="240px" />
        <h4 class="subsection-title">{{ tl('文件级覆盖率') }}</h4>
        <a-table :data="files" :loading="fileLoading" row-key="id" :pagination="false" size="small"
          :default-sort="{ field: 'line_coverage', direction: 'ascend' }">
          <template #columns>
            <a-table-column :title="tl('文件路径')" data-index="file_path" />
            <a-table-column :title="tl('行覆盖%')" data-index="line_coverage" :width="90" :sortable="true">
              <template #cell="{ record }">{{ record.line_coverage }}</template>
            </a-table-column>
            <a-table-column :title="tl('分支覆盖%')" :width="90">
              <template #cell="{ record }">{{ record.branch_coverage ?? '-' }}</template>
            </a-table-column>
            <a-table-column :title="tl('覆盖/总行')" :width="110">
              <template #cell="{ record }">
                <span class="lines-stat">{{ record.lines_covered }} / {{ record.lines_total }}</span>
              </template>
            </a-table-column>
            <a-table-column :title="tl('操作')" :width="80" fixed="right">
              <template #cell="{ record }">
                <a-button size="mini" @click="openLine(record)">{{ tl('行级') }}</a-button>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </template>
    </a-drawer>

    <!-- 行级覆盖热力图 -->
    <a-drawer v-model:visible="lineVisible" :title="tl('行级覆盖热力图')" :width="720">
      <template v-if="currentFile">
        <div class="line-summary">
          <a-descriptions :column="3" size="small">
            <a-descriptions-item :label="tl('文件')">{{ currentFile.file_path }}</a-descriptions-item>
            <a-descriptions-item :label="tl('行覆盖%')">{{ currentFile.line_coverage }}</a-descriptions-item>
            <a-descriptions-item :label="tl('覆盖/总行')">{{ currentFile.lines_covered }} / {{ currentFile.lines_total }}</a-descriptions-item>
          </a-descriptions>
        </div>
        <div class="heatmap-legend">
          <span class="heat-cell covered"></span><span>{{ tl('已覆盖') }}</span>
          <span class="heat-cell uncovered"></span><span>{{ tl('未覆盖') }}</span>
        </div>
        <div class="heatmap">
          <span v-for="cell in lineCells" :key="cell.line" class="heat-cell"
            :style="{ background: lineCellColor(cell.hits) }" @click="selectHeatCell(cell)"></span>
          <div v-if="!lineCells.length" class="heatmap-empty">{{ tl('暂无行级数据') }}</div>
        </div>
        <div v-if="selectedHeatCell" class="heatmap-detail">
          {{ tl('行') }} {{ selectedHeatCell.line }} — {{ selectedHeatCell.hits }} {{ tl('次命中') }}
        </div>
      </template>
    </a-drawer>

    <!-- 增量生成 -->
    <a-modal v-model:visible="deltaVisible" :title="tl('生成增量覆盖率')" @ok="submitDelta" @cancel="deltaVisible = false">
      <a-form layout="vertical">
        <a-form-item :label="tl('选择基线报告')" required>
          <a-select v-model="baseReportId" show-search>
            <a-option v-for="r in reportOptions" :key="r.id" :value="r.id">{{ r.name }}</a-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 增量详情 -->
    <a-drawer v-model:visible="deltaDetailVisible" :title="tl('增量覆盖详情')" :width="640">
      <template v-if="currentDelta">
        <a-descriptions :column="2" size="small">
          <a-descriptions-item :label="tl('新增行')">{{ currentDelta.summary?.new_lines_total }}</a-descriptions-item>
          <a-descriptions-item :label="tl('新增覆盖行')">{{ currentDelta.summary?.covered_new_lines }}</a-descriptions-item>
          <a-descriptions-item :label="tl('增量覆盖率%')">{{ currentDelta.summary?.delta_coverage }}</a-descriptions-item>
        </a-descriptions>
        <h4 class="subsection-title">{{ tl('变更文件') }}</h4>
        <a-table :data="currentDelta.files" row-key="file_path" :pagination="false" size="small">
          <template #columns>
            <a-table-column :title="tl('文件')" data-index="file_path" />
            <a-table-column :title="tl('状态')" data-index="status" :width="90">
              <template #cell="{ record }">{{ deltaFileStatusLabel(record.status) }}</template>
            </a-table-column>
            <a-table-column :title="tl('新增行')" data-index="new_lines" :width="80" />
            <a-table-column :title="tl('覆盖新增')" data-index="covered_new_lines" :width="90" />
            <a-table-column :title="tl('增量%')" data-index="delta_coverage" :width="80" />
          </template>
        </a-table>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, onMounted, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAppI18n } from '@/composables/useAppI18n'
import { useProjectStore } from '@/store/projectStore'
import { extractPaginationData, extractResponseData } from '@/features/ui-automation/types'
import EChart from '@/features/perf-test/components/EChart.vue'
import { coverageReportApi, coverageDeltaApi, coverageGateApi } from '../api'
import type {
  CoverageReport, CoverageFile, CoverageDelta, CoverageUploadForm, CoverageGateConfig,
} from '../types'

const { locale, t, tl } = useAppI18n()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

const activeTab = ref('reports')
const statusFilter = ref<string | undefined>(undefined)

const reports = ref<CoverageReport[]>([])
const reportLoading = ref(false)
const pagination = reactive({ current: 1, pageSize: 10, total: 0, showTotal: true })

const deltas = ref<CoverageDelta[]>([])
const deltaLoading = ref(false)

const statusLabel = (s: string) => ({ processing: tl('处理中'), completed: tl('已完成'), failed: tl('失败') } as Record<string, string>)[s] || s
const statusColor = (s: string) => ({ processing: 'gray', completed: 'green', failed: 'red' } as Record<string, string>)[s] || 'gray'
const deltaFileStatusLabel = (s: string) => ({ added: tl('新增'), modified: tl('修改'), removed: tl('删除'), unchanged: tl('未变') } as Record<string, string>)[s] || s

async function fetchReports() {
  if (!projectId.value) return
  reportLoading.value = true
  try {
    const res = await coverageReportApi.list({ project: projectId.value, status: statusFilter.value })
    const { items, count } = extractPaginationData(res)
    reports.value = items
    pagination.total = count
  } catch {
    Message.error(tl('加载报表失败'))
  } finally {
    reportLoading.value = false
  }
}

async function fetchDeltas() {
  if (!projectId.value) return
  deltaLoading.value = true
  try {
    const res = await coverageDeltaApi.list({ project: projectId.value })
    deltas.value = extractPaginationData(res).items
  } catch {
    Message.error(tl('加载增量失败'))
  } finally {
    deltaLoading.value = false
  }
}

function loadAll() {
  fetchReports()
  fetchDeltas()
}

// 覆盖率门禁
const gateConfig = reactive<{ enabled: boolean; min_line_coverage: number }>({ enabled: false, min_line_coverage: 80 })
const gateSaving = ref(false)

async function fetchGate() {
  if (!projectId.value) return
  try {
    const res = await coverageGateApi.byProject(projectId.value)
    const gate = extractResponseData<CoverageGateConfig>(res)
    if (gate) {
      gateConfig.enabled = gate.enabled
      gateConfig.min_line_coverage = gate.min_line_coverage
    }
  } catch {
    // 忽略门禁读取失败，默认不启用
  }
}

async function saveGate() {
  if (!projectId.value) return
  gateSaving.value = true
  try {
    const res = await coverageGateApi.byProject(projectId.value)
    const gate = extractResponseData<CoverageGateConfig>(res)
    if (gate) {
      await coverageGateApi.update(gate.id, { enabled: gateConfig.enabled, min_line_coverage: gateConfig.min_line_coverage })
      Message.success(tl('门禁已保存'))
      fetchReports()
    }
  } catch {
    Message.error(tl('保存门禁失败'))
  } finally {
    gateSaving.value = false
  }
}

function isGatePassed(record: CoverageReport): boolean {
  const actual = record.summary?.line_coverage ?? 0
  return actual >= gateConfig.min_line_coverage
}

const onSearch = () => { pagination.current = 1; fetchReports() }
const onPageChange = (page: number) => { pagination.current = page; fetchReports() }
const onPageSizeChange = (size: number) => { pagination.pageSize = size; pagination.current = 1; fetchReports() }

// 上传
const uploadVisible = ref(false)
const fileList = ref<any[]>([])
const uploadForm = reactive({
  name: '', format: 'cobertura' as 'cobertura' | 'lcov', test_type: 'api' as CoverageUploadForm['test_type'], git_commit: '',
})
const openUpload = () => { uploadForm.name = ''; uploadForm.format = 'cobertura'; uploadForm.test_type = 'api'; uploadForm.git_commit = ''; fileList.value = []; uploadVisible.value = true }
const onFileChange = (fileItemList: any) => { fileList.value = fileItemList }
const submitUpload = async () => {
  if (!projectId.value) { Message.warning(tl('请先选择项目')); return }
  const file = fileList.value[0]?.file || fileList.value[0]
  if (!uploadForm.name.trim() || !file) { Message.warning(tl('请填写名称并选择文件')); return }
  try {
    await coverageReportApi.upload({ project_id: projectId.value, name: uploadForm.name, format: uploadForm.format, test_type: uploadForm.test_type, git_commit: uploadForm.git_commit, file })
    Message.success(tl('上传成功'))
    uploadVisible.value = false
    fetchReports()
  } catch {
    Message.error(tl('上传失败'))
  }
}

// 详情
const detailVisible = ref(false)
const currentReport = ref<CoverageReport | null>(null)
const files = ref<CoverageFile[]>([])
const fileLoading = ref(false)
const openDetail = async (record: CoverageReport) => {
  currentReport.value = record
  detailVisible.value = true
  fileLoading.value = true
  try {
    const res = await coverageReportApi.files(record.id)
    files.value = extractPaginationData(res).items
  } catch {
    files.value = []
  } finally {
    fileLoading.value = false
  }
}

// 增量
const deltaVisible = ref(false)
const baseReportId = ref<string | undefined>(undefined)
const currentDeltaRecordId = ref<string | null>(null)
const reportOptions = computed(() => reports.value.filter((r) => r.id !== currentDeltaRecordId.value && r.status === 'completed'))
const openDelta = (record: CoverageReport) => {
  currentDeltaRecordId.value = record.id
  baseReportId.value = undefined
  deltaVisible.value = true
}
const submitDelta = async () => {
  if (!currentDeltaRecordId.value || !baseReportId.value) { Message.warning(tl('请选择基线报告')); return }
  try {
    await coverageReportApi.generateDelta(currentDeltaRecordId.value, baseReportId.value)
    Message.success(tl('生成成功'))
    deltaVisible.value = false
    fetchDeltas()
  } catch {
    Message.error(tl('生成失败'))
  }
}

// 增量详情
const deltaDetailVisible = ref(false)
const currentDelta = ref<CoverageDelta | null>(null)
const openDeltaDetail = (record: CoverageDelta) => {
  currentDelta.value = record
  deltaDetailVisible.value = true
}

// 行级热力图：覆盖率分布柱状图（文件覆盖率分桶）
const filesBucketOption = computed(() => {
  const buckets = [0, 20, 40, 60, 80, 100]
  const labels = ['0-20', '20-40', '40-60', '60-80', '80-100']
  const counts = labels.map((_, i) =>
    files.value.filter((f) => f.line_coverage >= buckets[i] && f.line_coverage < (buckets[i + 1] ?? 101)).length
  )
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: labels },
    yAxis: { type: 'value', name: tl('文件数') },
    series: [{ type: 'bar', data: counts, itemStyle: { color: '#3a7afe' }, barMaxWidth: 40 }],
  }
})

// 行级热力图
const lineVisible = ref(false)
const currentFile = ref<CoverageFile | null>(null)
const selectedHeatCell = ref<{ line: number; hits: number } | null>(null)
const lineCells = computed(() => {
  const detail = currentFile.value?.lines_detail || {}
  const cells = Object.entries(detail)
    .map(([k, hits]) => ({ line: Number(k), hits: Number(hits) }))
    .sort((a, b) => a.line - b.line)
  return cells
})
const lineCellColor = (hits: number) => (hits > 0 ? '#3a7afe' : '#e5e6eb')
const openLine = (record: CoverageFile) => {
  currentFile.value = record
  selectedHeatCell.value = null
  lineVisible.value = true
}
const selectHeatCell = (cell: { line: number; hits: number }) => { selectedHeatCell.value = cell }

watch(projectId, () => { onSearch(); fetchDeltas(); fetchGate() })
onMounted(() => { loadAll(); fetchGate() })
</script>

<style scoped>
.coverage-view { padding: 16px 20px; }
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.view-title { margin: 0; font-size: 18px; }
.view-actions { display: flex; gap: 8px; }
.gate-card { margin-bottom: 14px; }
.subsection-title { margin: 14px 0 8px; }
.cov-progress { margin-bottom: 8px; }
.cov-progress span { display: block; margin-bottom: 4px; }
.lines-stat { font-variant-numeric: tabular-nums; }
.line-summary { margin-bottom: 8px; }
.heatmap-legend { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; font-size: 12px; color: var(--color-text-3, #999); }
.heatmap { display: flex; flex-wrap: wrap; gap: 2px; max-height: 360px; overflow: auto; padding: 4px; background: var(--color-fill-2, #f5f5f5); border-radius: 6px; }
.heat-cell { display: inline-block; width: 12px; height: 12px; border-radius: 2px; flex: 0 0 auto; }
.heatmap-legend .heat-cell { width: 12px; height: 12px; }
.heatmap-empty { padding: 20px; color: var(--color-text-3, #999); }
.heatmap-detail { margin-top: 8px; font-size: 12px; color: var(--color-text-2, #444); }
</style>
