/**
 * 执行看板 Pinia Store
 * 管理实时运行状态，订阅 WebSocket 事件
 */

import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { executionDashboardSocket } from '../services/executionDashboardSocket'
import { getRunSnapshot } from '../services/executionDashboardApi'
import type {
  NodeState,
  RunState,
  SnapshotEta,
  RunStartedData,
  NodeStatusChangedData,
  RunStatsData,
  EtaUpdateData,
  RunFinishedData,
  SnapshotNode,
} from '../types'

/** 创建空白 RunState */
function emptyRunState(): RunState {
  return {
    runId: null,
    suiteName: '',
    executor: '',
    status: '',
    startedAt: undefined,
    total: 0,
    passed: 0,
    failed: 0,
    skipped: 0,
    error: 0,
    running: 0,
    pending: 0,
    passRate: 0,
    elapsed: 0,
    eta: null,
  }
}

export const useExecutionDashboardStore = defineStore('executionDashboard', () => {
  // ─── 状态 ───
  const connected = executionDashboardSocket.connected
  const run = reactive<RunState>(emptyRunState())
  const nodes = ref<Map<number, NodeState>>(new Map())
  const loading = ref(false)

  // 清理函数收集
  let unsubscribers: Array<() => void> = []

  // ─── 内部工具 ───
  function reset() {
    Object.assign(run, emptyRunState())
    nodes.value = new Map()
  }

  function applySnapshotNode(n: SnapshotNode) {
    nodes.value.set(n.id, {
      id: n.id,
      testcase_id: n.testcase_id,
      name: n.name,
      status: n.status,
      execution_time: n.execution_time,
      error_message: n.error_message,
      started_at: n.started_at,
      completed_at: n.completed_at,
    })
  }

  // ─── 事件处理 ───
  function handleRunStarted(data: Record<string, unknown>) {
    const d = data as unknown as RunStartedData
    reset()
    run.runId = d.run_id
    run.suiteName = d.suite_name
    run.executor = d.executor
    run.status = 'running'
    run.total = d.total
    run.pending = d.total
  }

  function handleNodeStatusChanged(data: Record<string, unknown>) {
    const d = data as unknown as NodeStatusChangedData
    const existing = nodes.value.get(d.node_id)
    nodes.value.set(d.node_id, {
      id: d.node_id,
      testcase_id: d.testcase_id,
      name: d.name,
      status: d.status,
      execution_time: d.execution_time ?? existing?.execution_time,
      error_message: d.error_message ?? existing?.error_message,
      started_at: d.started_at ?? existing?.started_at,
      completed_at: d.status !== 'running' && d.status !== 'pending' ? new Date().toISOString() : existing?.completed_at,
    })
  }

  function handleRunStats(data: Record<string, unknown>) {
    const d = data as unknown as RunStatsData
    run.total = d.total
    run.passed = d.passed
    run.failed = d.failed
    run.skipped = d.skipped
    run.error = d.error
    run.running = d.running
    run.pending = d.pending
    run.passRate = d.pass_rate
    run.elapsed = d.elapsed
  }

  function handleEtaUpdate(data: Record<string, unknown>) {
    const d = data as unknown as EtaUpdateData
    run.eta = {
      eta_seconds: d.eta_seconds,
      remaining_seconds: d.remaining_seconds,
      confidence: d.confidence,
      progress: d.progress,
    }
  }

  function handleRunFinished(data: Record<string, unknown>) {
    const d = data as unknown as RunFinishedData
    run.status = d.status
    run.passRate = d.pass_rate
    run.elapsed = d.duration
    run.passed = d.passed
    run.failed = d.failed
    run.skipped = d.skipped
    run.error = d.error
    run.running = 0
    run.pending = 0
    run.eta = null
  }

  // ─── 公开 Action ───

  /** 连接 WS 并订阅所有事件 */
  async function connectProject(projectId: number) {
    // 先断开旧连接
    disconnect()

    // 注册事件处理
    unsubscribers.push(
      executionDashboardSocket.on('run_started', (data) => handleRunStarted(data)),
      executionDashboardSocket.on('node_status_changed', (data) => handleNodeStatusChanged(data)),
      executionDashboardSocket.on('run_stats', (data) => handleRunStats(data)),
      executionDashboardSocket.on('eta_update', (data) => handleEtaUpdate(data)),
      executionDashboardSocket.on('run_finished', (data) => handleRunFinished(data)),
    )

    // 重连时自动刷新快照
    unsubscribers.push(
      executionDashboardSocket.onReconnect(() => {
        if (run.runId) {
          loadSnapshot(run.runId)
        }
      })
    )

    try {
      await executionDashboardSocket.connect(projectId)
    } catch (e) {
      console.error('[ExecDashStore] WS connect failed:', e)
    }
  }

  /** 断开 WS 连接并清理 */
  function disconnect() {
    unsubscribers.forEach(fn => fn())
    unsubscribers = []
    executionDashboardSocket.disconnect()
    reset()
  }

  /** 加载快照 */
  async function loadSnapshot(runId: number) {
    loading.value = true
    try {
      const res = await getRunSnapshot(runId)
      if (res.success && res.data) {
        const snap = res.data
        run.runId = snap.run.id
        run.suiteName = snap.run.suite_name || ''
        run.executor = snap.run.executor || ''
        run.status = snap.run.status
        run.startedAt = snap.run.started_at
        run.total = snap.run.total_count
        run.passed = snap.run.passed_count
        run.failed = snap.run.failed_count
        run.skipped = snap.run.skipped_count
        run.error = snap.run.error_count
        run.passRate = snap.run.pass_rate
        run.elapsed = snap.run.duration || 0
        run.eta = snap.eta as SnapshotEta | null

        const newNodes = new Map<number, NodeState>()
        for (const n of snap.nodes) {
          newNodes.set(n.id, {
            id: n.id,
            testcase_id: n.testcase_id,
            name: n.name,
            status: n.status,
            execution_time: n.execution_time,
            error_message: n.error_message,
            started_at: n.started_at,
            completed_at: n.completed_at,
          })
        }
        nodes.value = newNodes
      }
    } catch (e) {
      console.error('[ExecDashStore] Snapshot load failed:', e)
    } finally {
      loading.value = false
    }
  }

  return {
    connected,
    run,
    nodes,
    loading,
    connectProject,
    disconnect,
    loadSnapshot,
    reset,
  }
})
