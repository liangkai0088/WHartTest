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
        <h4 class="subsection-title">{{ tl('文件级覆盖率') }}</h4>
        <a-table :data="files" :loading="fileLoading" row-key="id" :pagination="false" size="small">
          <template #columns>
            <a-table-column :title="tl('文件路径')" data-index="file_path" />
            <a-table-column :title="tl('行覆盖%')" data-index="line_coverage" :width="90" />
            <a-table-column :title="tl('分支覆盖%')" :width="90">
              <template #cell="{ record }">{{ record.branch_coverage ?? '-' }}</template>
            </a-table-column>
          </template>
        </a-table>
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
import { coverageReportApi, coverageDeltaApi } from '../api'
import type {
  CoverageReport, CoverageFile, CoverageDelta, CoverageUploadForm,
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

watch(projectId, () => { onSearch(); fetchDeltas() })
onMounted(loadAll)
</script>

<style scoped>
.coverage-view { padding: 16px 20px; }
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.view-title { margin: 0; font-size: 18px; }
.view-actions { display: flex; gap: 8px; }
.subsection-title { margin: 14px 0 8px; }
.cov-progress { margin-bottom: 8px; }
.cov-progress span { display: block; margin-bottom: 4px; }
</style>
