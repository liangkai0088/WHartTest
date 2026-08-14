/**
 * AI 执行进度看板 — 共享类型定义
 */

// ─── WebSocket 事件类型 ───

export type NodeStatus = 'pending' | 'running' | 'pass' | 'fail' | 'skip' | 'error'

export interface WsEnvelope<T = Record<string, unknown>> {
  event: string
  ts: string
  data: T
}

export interface RunStartedData {
  run_id: number
  project_id: number
  suite_id: number
  suite_name: string
  total: number
  max_concurrent: number
  executor: string
}

export interface NodeStatusChangedData {
  run_id: number
  node_id: number
  testcase_id: number
  name: string
  status: NodeStatus
  started_at?: string
  execution_time?: number
  error_message?: string
}

export interface RunStatsData {
  run_id: number
  total: number
  passed: number
  failed: number
  skipped: number
  error: number
  running: number
  pending: number
  pass_rate: number
  elapsed: number
}

export interface EtaUpdateData {
  run_id: number
  eta_seconds: number
  remaining_seconds: number
  confidence: 'high' | 'medium' | 'low'
  progress: number
}

export interface RunFinishedData {
  run_id: number
  status: string
  pass_rate: number
  duration: number
  passed: number
  failed: number
  skipped: number
  error: number
}

// ─── REST 响应类型 ───

export interface SnapshotNode {
  id: number
  testcase_id: number
  name: string
  status: NodeStatus
  execution_time?: number
  error_message?: string
  started_at?: string
  completed_at?: string
}

export interface SnapshotEta {
  eta_seconds: number
  remaining_seconds: number
  confidence: 'high' | 'medium' | 'low'
  progress: number
}

export interface SnapshotRun {
  id: number
  suite_name?: string
  status: string
  executor?: string
  started_at?: string
  completed_at?: string
  total_count: number
  passed_count: number
  failed_count: number
  skipped_count: number
  error_count: number
  pass_rate: number
  duration?: number
}

export interface SnapshotResponse {
  run: SnapshotRun
  nodes: SnapshotNode[]
  eta: SnapshotEta | null
}

export interface EventRecord {
  id: number
  event_type: string
  status?: string
  payload: Record<string, unknown>
  created_at: string
}

// ─── 前端状态类型 ───

export interface NodeState {
  id: number
  testcase_id: number
  name: string
  status: NodeStatus
  execution_time?: number
  error_message?: string
  started_at?: string
  completed_at?: string
}

export interface RunState {
  runId: number | null
  suiteName: string
  executor: string
  status: string
  startedAt?: string
  total: number
  passed: number
  failed: number
  skipped: number
  error: number
  running: number
  pending: number
  passRate: number
  elapsed: number
  eta: SnapshotEta | null
}
