<template>
  <div class="perf-test-view">
    <div class="view-header">
      <h3 class="view-title">{{ tl('性能测试') }}</h3>
      <div class="view-actions">
        <a-select v-model="sourceFilter" :placeholder="tl('全部来源')" allow-clear style="width: 140px" @change="onSearch">
          <a-option v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</a-option>
        </a-select>
        <a-button @click="onSearch">{{ tl('刷新') }}</a-button>
        <a-button type="primary" @click="openAiOrchestrate">{{ tl('AI 编排') }}</a-button>
        <a-button type="primary" @click="openCreate">{{ tl('新建场景') }}</a-button>
      </div>
    </div>

    <a-tabs :key="`perf-tabs-${locale}`" v-model:active-key="activeTab" type="card-gutter">
      <a-tab-pane key="scenarios" :title="tl('场景管理')">
        <a-table
          :data="scenarios"
          :loading="scenarioLoading"
          row-key="id"
          :pagination="scenarioPagination"
          @page-change="onScenarioPageChange"
          @page-size-change="onScenarioPageSizeChange"
        >
          <template #columns>
            <a-table-column title="ID" data-index="id" :width="70" />
            <a-table-column :title="tl('场景名称')" data-index="name" />
            <a-table-column :title="tl('来源')" data-index="source" :width="90">
              <template #cell="{ record }">{{ sourceLabel(record.source) }}</template>
            </a-table-column>
            <a-table-column :title="tl('请求数')" data-index="request_count" :width="90" />
            <a-table-column :title="tl('创建人')" data-index="creator_name" :width="110" />
            <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
            <a-table-column :title="tl('操作')" :width="250" fixed="right">
              <template #cell="{ record }">
                <a-space>
                  <a-button size="mini" @click="openDetail(record)">{{ tl('详情') }}</a-button>
                  <a-button size="mini" type="primary" @click="handleExecute(record)">{{ tl('执行') }}</a-button>
                  <a-button size="mini" @click="openRender(record)">{{ tl('脚本预览') }}</a-button>
                  <a-dropdown>
                    <a-button size="mini">{{ tl('导入') }}</a-button>
                    <template #content>
                      <a-doption @click="openImportFromTemplate(record)">{{ tl('场景模板') }}</a-doption>
                      <a-doption @click="openImportInterfaces(record)">{{ tl('接口导入') }}</a-doption>
                      <a-doption @click="openImportSwagger(record)">{{ tl('Swagger') }}</a-doption>
                      <a-doption @click="openImportHar(record)">{{ tl('HAR') }}</a-doption>
                    </template>
                  </a-dropdown>
                  <a-popconfirm :content="tl('确定删除该场景？')" @ok="handleDelete(record)">
                    <a-button size="mini" status="danger">{{ tl('删除') }}</a-button>
                  </a-popconfirm>
                </a-space>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="executions" :title="tl('执行记录')">
        <a-table :data="executions" :loading="executionLoading" row-key="id" :pagination="false">
          <template #columns>
            <a-table-column title="ID" data-index="id" :width="70" />
            <a-table-column :title="tl('场景')" data-index="scenario_name" />
            <a-table-column :title="tl('状态')" :width="110">
              <template #cell="{ record }">
                <a-tag :color="executionStatusColor(record.status)">{{ executionStatusLabel(record.status) }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column :title="tl('进度')" :width="180">
              <template #cell="{ record }">
                <a-progress :percent="record.progress || 0" size="mini" />
              </template>
            </a-table-column>
            <a-table-column :title="tl('执行人')" data-index="executed_by_name" :width="110" />
            <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
            <a-table-column :title="tl('操作')" :width="160" fixed="right">
              <template #cell="{ record }">
                <a-space>
                  <a-button
                    v-if="record.status === 'pending'"
                    size="mini"
                    type="primary"
                    @click="handleStart(record)"
                  >{{ tl('启动') }}</a-button>
                  <a-button
                    v-else-if="record.status === 'running'"
                    size="mini"
                    status="warning"
                    @click="handleStop(record)"
                  >{{ tl('停止') }}</a-button>
                  <a-button
                    v-if="record.status === 'running'"
                    size="mini"
                    type="primary"
                    @click="startRealtime(record.id)"
                  >{{ tl('监控') }}</a-button>
                  <a-button v-else-if="record.status === 'completed'" size="mini" @click="openReport(record)">
                    {{ tl('报告') }}
                  </a-button>
                </a-space>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="reports" :title="tl('压测报告')">
        <a-table :data="reports" :loading="reportLoading" row-key="id" :pagination="false">
          <template #columns>
            <a-table-column title="ID" data-index="id" :width="70" />
            <a-table-column :title="tl('执行')" data-index="execution" :width="90" />
            <a-table-column :title="tl('总请求')" data-index="total_requests" :width="90" />
            <a-table-column :title="tl('错误率%')" data-index="error_rate" :width="90" />
            <a-table-column :title="tl('P95(ms)')" data-index="p95" :width="90" />
            <a-table-column :title="tl('峰值QPS')" data-index="peak_rps" :width="90" />
            <a-table-column :title="tl('创建时间')" data-index="created_at" :width="170" />
            <a-table-column :title="tl('操作')" :width="100" fixed="right">
              <template #cell="{ record }">
                <a-button size="mini" @click="openReport(record)">{{ tl('详情') }}</a-button>
              </template>
            </a-table-column>
          </template>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <!-- 新建场景 -->
    <a-modal v-model:visible="createVisible" :title="tl('新建场景')" @ok="submitCreate" @cancel="createVisible = false">
      <a-form :model="createForm" layout="vertical">
        <a-form-item :label="tl('场景名称')" required>
          <a-input v-model="createForm.name" />
        </a-form-item>
        <a-form-item :label="tl('场景描述')">
          <a-textarea v-model="createForm.description" :rows="3" />
        </a-form-item>
        <a-form-item :label="tl('来源')">
          <a-select v-model="createForm.source">
            <a-option v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</a-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- AI 编排 -->
    <a-modal v-model:visible="aiVisible" :title="tl('AI 压测编排')" @ok="submitAiOrchestrate" @cancel="aiVisible = false">
      <a-form layout="vertical">
        <a-form-item :label="tl('业务链路描述')" required>
          <a-textarea v-model="aiRequirements" :rows="5" placeholder="例如：用户登录后批量查询订单，模拟秒杀并发" />
        </a-form-item>
        <a-form-item :label="tl('关联接口ID（可选，逗号分隔）')">
          <a-input v-model="aiInterfaceIds" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 场景详情 -->
    <a-drawer v-model:visible="detailVisible" :title="tl('场景详情')" :width="560">
      <template v-if="currentScenario">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item :label="tl('场景名称')">{{ currentScenario.name }}</a-descriptions-item>
          <a-descriptions-item :label="tl('描述')">{{ currentScenario.description || '-' }}</a-descriptions-item>
          <a-descriptions-item :label="tl('来源')">{{ sourceLabel(currentScenario.source) }}</a-descriptions-item>
          <a-descriptions-item :label="tl('负载模型')">
            <span v-if="currentScenario.plan">
              users={{ currentScenario.plan.users }} · spawn={{ currentScenario.plan.spawn_rate }}/s · duration={{ currentScenario.plan.duration }}s · think={{ currentScenario.plan.think_time }}s
            </span>
            <span v-else>-</span>
          </a-descriptions-item>
        </a-descriptions>
        <h4 class="subsection-title">{{ tl('请求列表') }}</h4>
        <a-table :data="currentScenario.requests" row-key="id" :pagination="false" size="small">
          <template #columns>
            <a-table-column :title="tl('方法')" data-index="method" :width="70" />
            <a-table-column :title="tl('名称')" data-index="name" />
            <a-table-column :title="tl('权重')" data-index="weight" :width="70" />
          </template>
        </a-table>
      </template>
    </a-drawer>

    <!-- 脚本预览 -->
    <a-drawer v-model:visible="renderVisible" :title="tl('Locust 脚本预览')" :width="600">
      <pre class="locust-pre">{{ locustfile }}</pre>
    </a-drawer>

    <!-- 报告详情 -->
    <a-drawer v-model:visible="reportVisible" :title="tl('压测报告详情')" :width="680">
      <template v-if="currentReport">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item :label="tl('总请求')">{{ currentReport.total_requests }}</a-descriptions-item>
          <a-descriptions-item :label="tl('总失败')">{{ currentReport.total_failures }}</a-descriptions-item>
          <a-descriptions-item :label="tl('错误率%')">{{ currentReport.error_rate }}</a-descriptions-item>
          <a-descriptions-item :label="tl('总QPS')">{{ currentReport.total_rps }}</a-descriptions-item>
          <a-descriptions-item :label="tl('峰值QPS')">{{ currentReport.peak_rps }}</a-descriptions-item>
          <a-descriptions-item :label="tl('平均RT(ms)')">{{ currentReport.avg_response_time }}</a-descriptions-item>
          <a-descriptions-item :label="tl('P50(ms)')">{{ currentReport.p50 }}</a-descriptions-item>
          <a-descriptions-item :label="tl('P95(ms)')">{{ currentReport.p95 }}</a-descriptions-item>
          <a-descriptions-item :label="tl('P99(ms)')">{{ currentReport.p99 }}</a-descriptions-item>
        </a-descriptions>
        <h4 class="subsection-title">{{ tl('QPS 时序') }}</h4>
        <EChart :option="rpsChartOption" height="220px" />
        <h4 class="subsection-title">{{ tl('AI 诊断') }}</h4>
        <div v-if="currentReport.bottleneck_summary" class="diag-box">
          <div class="diag-summary">{{ bottleneckText.summary }}</div>
          <ul v-for="b in bottleneckText.bottlenecks" :key="b.name" class="diag-bottleneck">
            <li><b>{{ b.name }}</b> [{{ b.severity }}] — {{ b.detail }}</li>
          </ul>
          <p class="diag-suggest"><b>{{ tl('建议') }}：</b>{{ bottleneckText.suggestions.join('；') }}</p>
        </div>
        <a-button v-else type="primary" :loading="diagnosing" @click="handleDiagnose">
          {{ tl('AI 智能分析瓶颈') }}
        </a-button>
      </template>
    </a-drawer>

    <!-- 导入：常规弹窗 -->
    <a-modal v-model:visible="importVisible" :title="importTitle" @ok="submitImport" @cancel="importVisible = false">
      <a-form layout="vertical">
        <a-form-item :label="importLabel">
          <a-textarea v-if="importKind === 'swagger' || importKind === 'har'" v-model="importText" :rows="6" />
          <a-input v-else v-model="importText" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 实时执行面板 -->
    <a-drawer v-model:visible="realtimeVisible" :title="tl('实时执行监控')" :width="640">
      <a-descriptions :column="2" size="small">
        <a-descriptions-item :label="tl('进度')">{{ realtime.progress }}%</a-descriptions-item>
        <a-descriptions-item :label="tl('当前QPS')">{{ realtime.rps }}</a-descriptions-item>
        <a-descriptions-item :label="tl('并发用户')">{{ realtime.users }}</a-descriptions-item>
      </a-descriptions>
      <EChart :option="realtimeChartOption" height="260px" />
      <div class="realtime-tip">{{ tl('执行结束后请切换到报告标签查看完整报表') }}</div>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { useAppI18n } from '@/composables/useAppI18n'
import { useProjectStore } from '@/store/projectStore'
import { extractPaginationData, extractResponseData } from '@/features/ui-automation/types'
import EChart from '../components/EChart.vue'
import { perfScenarioApi, perfReportApi, perfExecutionApi } from '../api'
import { perfWebSocket } from '../services/websocket'
import type {
  PerfTestScenario, PerfTestExecution, PerfTestReport, PerfRealtimeUpdate, PerfScenarioTemplate,
} from '../types'

const { locale, t, tl } = useAppI18n()
const projectStore = useProjectStore()
const projectId = computed(() => projectStore.currentProjectId)

const sourceOptions = [
  { value: 'interface', label: tl('接口') },
  { value: 'swagger', label: tl('Swagger') },
  { value: 'har', label: tl('HAR') },
  { value: 'ai', label: tl('AI') },
]
const sourceFilter = ref<string | undefined>(undefined)
const activeTab = ref('scenarios')
const sourceLabel = (s: string) => sourceOptions.find((o) => o.value === s)?.label || s

const scenarios = ref<PerfTestScenario[]>([])
const scenarioLoading = ref(false)
const scenarioPagination = reactive({ current: 1, pageSize: 10, total: 0, showTotal: true })
const executions = ref<PerfTestExecution[]>([])
const executionLoading = ref(false)
const reports = ref<PerfTestReport[]>([])
const reportLoading = ref(false)

async function fetchScenarios() {
  if (!projectId.value) return
  scenarioLoading.value = true
  try {
    const res = await perfScenarioApi.list({ project: projectId.value, source: sourceFilter.value })
    const { items, count } = extractPaginationData(res)
    scenarios.value = items
    scenarioPagination.total = count
  } catch {
    Message.error(tl('加载场景列表失败'))
  } finally {
    scenarioLoading.value = false
  }
}

async function fetchExecutions() {
  if (!projectId.value) return
  executionLoading.value = true
  try {
    const res = await perfExecutionApi.list({})
    executions.value = extractPaginationData(res).items
  } catch {
    Message.error(tl('加载执行记录失败'))
  } finally {
    executionLoading.value = false
  }
}

async function fetchReports() {
  reportLoading.value = true
  try {
    const res = await perfReportApi.list({})
    reports.value = extractPaginationData(res).items
  } catch {
    Message.error(tl('加载报告失败'))
  } finally {
    reportLoading.value = false
  }
}

function loadAll() {
  fetchScenarios()
  fetchExecutions()
  fetchReports()
}

const onSearch = () => {
  scenarioPagination.current = 1
  fetchScenarios()
}
const onScenarioPageChange = (page: number) => { scenarioPagination.current = page; fetchScenarios() }
const onScenarioPageSizeChange = (size: number) => { scenarioPagination.pageSize = size; scenarioPagination.current = 1; fetchScenarios() }

// 新建场景
const createVisible = ref(false)
const createForm = reactive({ name: '', description: '', source: 'interface' })
const openCreate = () => {
  createForm.name = ''
  createForm.description = ''
  createForm.source = 'interface'
  createVisible.value = true
}
const submitCreate = async () => {
  if (!projectId.value) { Message.warning(tl('请先选择项目')); return }
  if (!createForm.name.trim()) { Message.warning(tl('请输入场景名称')); return }
  try {
    await perfScenarioApi.create({ name: createForm.name, description: createForm.description, source: createForm.source as any, project: projectId.value })
    Message.success(tl('创建成功'))
    createVisible.value = false
    fetchScenarios()
  } catch {
    Message.error(tl('创建失败'))
  }
}

// AI 编排
const aiVisible = ref(false)
const aiRequirements = ref('')
const aiInterfaceIds = ref('')
const openAiOrchestrate = () => { aiRequirements.value = ''; aiInterfaceIds.value = ''; aiVisible.value = true }
const submitAiOrchestrate = async () => {
  if (!projectId.value) { Message.warning(tl('请先选择项目')); return }
  if (!aiRequirements.value.trim()) { Message.warning(tl('请输入业务链路描述')); return }
  const ids = aiInterfaceIds.value.split(',').map((s) => Number(s.trim())).filter((n) => Number.isFinite(n) && n > 0)
  try {
    await perfScenarioApi.aiOrchestrate({ requirement: aiRequirements.value, project_id: projectId.value, interface_ids: ids.length ? ids : undefined })
    Message.success(tl('编排成功'))
    aiVisible.value = false
    fetchScenarios()
  } catch {
    Message.error(tl('编排失败'))
  }
}

// 场景详情
const detailVisible = ref(false)
const currentScenario = ref<PerfTestScenario | null>(null)
const openDetail = async (record: PerfTestScenario) => {
  try {
    const res = await perfScenarioApi.get(record.id)
    currentScenario.value = extractResponseData<PerfTestScenario>(res)
  } catch {
    currentScenario.value = record
  }
  detailVisible.value = true
}

// 脚本预览
const renderVisible = ref(false)
const locustfile = ref('')
const openRender = async (record: PerfTestScenario) => {
  try {
    const res = await perfScenarioApi.render(record.id)
    locustfile.value = extractResponseData<{ locustfile: string }>(res)?.locustfile || ''
  } catch {
    locustfile.value = record.locustfile || ''
  }
  renderVisible.value = true
}

// 删除
const handleDelete = async (record: PerfTestScenario) => {
  try {
    await perfScenarioApi.delete(record.id)
    Message.success(tl('删除成功'))
    fetchScenarios()
  } catch {
    Message.error(tl('删除失败'))
  }
}

// 执行
const handleExecute = async (record: PerfTestScenario) => {
  try {
    await perfScenarioApi.execute(record.id)
    Message.success(tl('执行已启动'))
    fetchExecutions()
  } catch {
    Message.error(tl('启动执行失败'))
  }
}

// 执行记录：启动/停止
const handleStart = async (record: PerfTestExecution) => {
  try {
    await perfExecutionApi.start(record.id)
    Message.success(tl('已启动'))
    fetchExecutions()
  } catch {
    Message.error(tl('启动失败'))
  }
}
const handleStop = async (record: PerfTestExecution) => {
  try {
    await perfExecutionApi.stop(record.id)
    Message.success(tl('已停止'))
    fetchExecutions()
  } catch {
    Message.error(tl('停止失败'))
  }
}

// 实时 HTTP 执行会话（scenario.execute 产生的 running 执行）
const realtimeVisible = ref(false)
const realtime = reactive<PerfRealtimeUpdate>({ progress: 0, rps: 0, users: 0 })
const realtimeSeries = ref<Array<{ time: number; rps: number }>>([])
let offUpdate: (() => void) | null = null
const startRealtime = (executionId: number) => {
  realtime.progress = 0; realtime.rps = 0; realtime.users = 0
  realtimeSeries.value = []
  realtimeVisible.value = true
  perfWebSocket.connect(executionId).catch(() => Message.error(tl('实时连接失败')))
  offUpdate = perfWebSocket.onUpdate((u) => {
    realtime.progress = u.progress
    realtime.rps = u.rps
    realtime.users = u.users
    realtimeSeries.value.push({ time: realtimeSeries.value.length, rps: u.rps })
  })
}

const realtimeChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', data: realtimeSeries.value.map((p) => p.time) },
  yAxis: { type: 'value', name: 'QPS' },
  series: [{ type: 'line', data: realtimeSeries.value.map((p) => p.rps), smooth: true }],
}))

// 报告
const reportVisible = ref(false)
const currentReport = ref<PerfTestReport | null>(null)
const diagnosing = ref(false)
const bottleneckText = computed(() => {
  const d = currentReport.value?.bottleneck_summary
  if (!d) return { summary: '', bottlenecks: [], suggestions: [] }
  return {
    summary: (d as any).summary || '',
    bottlenecks: (d as any).bottlenecks || [],
    suggestions: (d as any).suggestions || [],
  }
})
const openReport = async (record: PerfTestExecution | PerfTestReport) => {
  const reportId = 'execution' in record ? record.id : record.report_id
  if (!reportId) { Message.warning(tl('暂无报告')); return }
  try {
    const res = await perfReportApi.get(reportId)
    currentReport.value = extractResponseData<PerfTestReport>(res)
  } catch {
    currentReport.value = null
  }
  reportVisible.value = true
}
const rpsChartOption = computed(() => {
  const series = currentReport.value?.rps_series || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: series.map((p) => p.time) },
    yAxis: { type: 'value', name: 'QPS' },
    series: [{ type: 'line', data: series.map((p) => p.rps ?? 0), smooth: true, areaStyle: { opacity: 0.2 } }],
  }
})
const handleDiagnose = async () => {
  if (!currentReport.value) return
  diagnosing.value = true
  try {
    await perfReportApi.diagnose(currentReport.value.id)
    Message.success(tl('诊断任务已提交'))
  } catch {
    Message.error(tl('诊断提交失败'))
  } finally {
    diagnosing.value = false
  }
}

// 导入弹窗
const importVisible = ref(false)
const importKind = ref<'interface' | 'swagger' | 'har' | 'template'>('interface')
const importText = ref('')
const importScenarioId = ref<number | null>(null)
const importTitle = computed(() => {
  if (importKind.value === 'template') return tl('从场景模板创建')
  if (importKind.value === 'swagger') return tl('导入 Swagger')
  if (importKind.value === 'har') return tl('导入 HAR')
  return tl('导入接口')
})
const importLabel = computed(() => {
  if (importKind.value === 'template') return tl('选择模板 Key')
  if (importKind.value === 'swagger') return tl('Swagger/OpenAPI 定义 (JSON)')
  if (importKind.value === 'har') return tl('HAR (JSON 字符串)')
  return tl('接口ID（逗号分隔）')
})
const openImportSwagger = (record: PerfTestScenario) => { importKind.value = 'swagger'; importText.value = ''; importScenarioId.value = record.id; importVisible.value = true }
const openImportHar = (record: PerfTestScenario) => { importKind.value = 'har'; importText.value = ''; importScenarioId.value = record.id; importVisible.value = true }
const openImportInterfaces = (record: PerfTestScenario) => { importKind.value = 'interface'; importText.value = ''; importScenarioId.value = record.id; importVisible.value = true }
const openImportFromTemplate = async (record: PerfTestScenario) => {
  try {
    const res = await perfScenarioApi.templates()
    const templates = extractResponseData<PerfScenarioTemplate[]>(res) || []
    if (!templates.length) { Message.info(tl('暂无可用模板')); return }
    const tpl = templates[0]
    await perfScenarioApi.createFromTemplate({ template: tpl.key, project_id: record.project, name: `${record.name}-模板` })
    Message.success(tl('创建成功'))
    fetchScenarios()
  } catch {
    Message.error(tl('创建失败'))
  }
}
const submitImport = async () => {
  if (!importScenarioId.value || !importText.value.trim()) { Message.warning(tl('请输入内容')); return }
  try {
    if (importKind.value === 'swagger') {
      await perfScenarioApi.importSwagger(importScenarioId.value, JSON.parse(importText.value))
    } else if (importKind.value === 'har') {
      await perfScenarioApi.importHar(importScenarioId.value, JSON.parse(importText.value))
    } else if (importKind.value === 'interface') {
      const ids = importText.value.split(',').map((s) => Number(s.trim())).filter((n) => Number.isFinite(n) && n > 0)
      await perfScenarioApi.importInterfaces(importScenarioId.value, ids)
    }
    Message.success(tl('导入成功'))
    importVisible.value = false
    fetchScenarios()
  } catch {
    Message.error(tl('导入失败'))
  }
}

const executionStatusLabel = (s: string) => ({ pending: tl('待执行'), running: tl('执行中'), completed: tl('已完成'), failed: tl('失败'), canceled: tl('已取消') } as Record<string, string>)[s] || s
const executionStatusColor = (s: string) => ({ pending: 'gray', running: 'blue', completed: 'green', failed: 'red', canceled: 'orange' } as Record<string, string>)[s] || 'gray'

onMounted(() => {
  loadAll()
})
onBeforeUnmount(() => {
  perfWebSocket.disconnect()
  offUpdate?.()
})
</script>

<style scoped>
.perf-test-view { padding: 16px 20px; }
.view-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.view-title { margin: 0; font-size: 18px; }
.view-actions { display: flex; gap: 8px; }
.subsection-title { margin: 14px 0 8px; }
.locust-pre { background: var(--color-fill-2, #f5f5f5); padding: 12px; border-radius: 6px; overflow: auto; max-height: 70vh; font-size: 12px; }
.diag-box { font-size: 13px; }
.diag-summary { margin-bottom: 8px; }
.diag-bottleneck { padding-left: 18px; margin: 4px 0; }
.diag-suggest { color: #e6a23c; }
.realtime-tip { margin-top: 12px; color: var(--color-text-3, #999); font-size: 12px; }
</style>
