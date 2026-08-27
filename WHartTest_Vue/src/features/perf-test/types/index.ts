// 性能测试模块类型定义

export type PerfScenarioSource = 'interface' | 'swagger' | 'har' | 'ai'
export type PerfHttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS'
export type PerfExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'canceled'

/** 动态参数提取规则 */
export interface PerfVariable {
  name: string
  path: string
}

/** 断言规则 */
export interface PerfValidator {
  type: 'status_code' | 'json'
  expected?: number | string
  path?: string
}

export interface PerfTestRequest {
  id: number
  scenario: number
  name: string
  method: PerfHttpMethod
  url: string
  headers: Record<string, string>
  params: Record<string, string>
  body: Record<string, any>
  variables: PerfVariable[]
  validators: PerfValidator[]
  weight: number
  order: number
  created_at: string
}

export interface PerfTestPlan {
  id: number
  scenario: number
  users: number
  spawn_rate: number
  duration: number
  think_time: number
  target_qps: number | null
  node: number | null
  node_name: string | null
  created_at: string
  updated_at: string
}

export interface PerfTestScenario {
  id: number
  name: string
  description: string
  source: PerfScenarioSource
  project: number
  locustfile: string
  requests: PerfTestRequest[]
  plan: PerfTestPlan | null
  request_count: number
  creator_name: string
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface PerfScenarioForm {
  name: string
  description?: string
  source?: PerfScenarioSource
  project: number
}

export interface PerfTestExecution {
  id: number
  scenario: number
  scenario_name: string
  plan_snapshot: Record<string, any> | null
  status: PerfExecutionStatus
  progress: number
  celery_task_id: string | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  executed_by: number | null
  executed_by_name: string
  node: number | null
  node_name: string | null
  report_id: number | null
  created_at: string
}

export interface PerfDiagBottleneck {
  name: string
  severity: 'high' | 'medium' | 'low'
  detail: string
}

export interface PerfDiagResult {
  summary: string
  bottlenecks: PerfDiagBottleneck[]
  suggestions: string[]
}

export interface PerfTestReport {
  id: number
  execution: number
  total_requests: number
  total_failures: number
  error_rate: number
  avg_response_time: number
  min_response_time: number
  max_response_time: number
  p50: number
  p95: number
  p99: number
  total_rps: number
  peak_rps: number
  rps_series: Array<{ time: number; rps?: number; response_time?: number }>
  bottleneck_summary: PerfDiagResult | Record<string, any> | null
  created_at: string
}

export interface PerfTestNode {
  id: number
  name: string
  host: string
  status: 'online' | 'offline'
  cpu_usage: number
  memory_usage: number
  last_heartbeat: string | null
  created_at: string
}

export interface PerfScenarioTemplate {
  key: string
  name: string
  description: string
}

/** 实时推送载荷 */
export interface PerfRealtimeUpdate {
  progress: number
  rps: number
  users: number
}

/** 分页响应结构 */
export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
