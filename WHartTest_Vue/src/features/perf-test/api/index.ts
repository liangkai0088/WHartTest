// 性能测试 API 服务

import request from '@/utils/request'
import type {
  PerfTestScenario,
  PerfScenarioForm,
  PerfTestRequest,
  PerfTestPlan,
  PerfTestExecution,
  PerfTestReport,
  PerfTestNode,
  PerfScenarioTemplate,
  PaginatedResponse,
} from '../types'

const BASE_URL = '/perf-test'

export const perfScenarioApi = {
  list: (params?: { project?: number; source?: string; search?: string }) =>
    request.get<PaginatedResponse<PerfTestScenario>>(`${BASE_URL}/scenarios/`, { params }),

  get: (id: number) => request.get<PerfTestScenario>(`${BASE_URL}/scenarios/${id}/`),

  create: (data: PerfScenarioForm) => request.post<PerfTestScenario>(`${BASE_URL}/scenarios/`, data),

  update: (id: number, data: Partial<PerfScenarioForm>) =>
    request.patch<PerfTestScenario>(`${BASE_URL}/scenarios/${id}/`, data),

  delete: (id: number) => request.delete(`${BASE_URL}/scenarios/${id}/`),

  render: (id: number) => request.post<{ locustfile: string }>(`${BASE_URL}/scenarios/${id}/render/`),

  importInterfaces: (id: number, interfaceIds: number[]) =>
    request.post<{ created: number }>(`${BASE_URL}/scenarios/${id}/import_interfaces/`, { interface_ids: interfaceIds }),

  importSwagger: (id: number, spec: Record<string, any>) =>
    request.post<{ created: number }>(`${BASE_URL}/scenarios/${id}/import_swagger/`, { spec }),

  importHar: (id: number, har: Record<string, any> | string) =>
    request.post<{ created: number }>(`${BASE_URL}/scenarios/${id}/import_har/`, { har }),

  execute: (id: number) => request.post<PerfTestExecution>(`${BASE_URL}/scenarios/${id}/execute/`),

  templates: () => request.get<PerfScenarioTemplate[]>(`${BASE_URL}/scenarios/templates/`),

  createFromTemplate: (data: { template: string; project_id: number; name?: string }) =>
    request.post<PerfTestScenario>(`${BASE_URL}/scenarios/create_from_template/`, data),

  aiOrchestrate: (data: { requirement: string; project_id: number; interface_ids?: number[] }) =>
    request.post<PerfTestScenario>(`${BASE_URL}/scenarios/ai_orchestrate/`, data),
}

export const perfRequestApi = {
  list: (params?: { scenario?: number; method?: string }) =>
    request.get<PaginatedResponse<PerfTestRequest>>(`${BASE_URL}/requests/`, { params }),
  get: (id: number) => request.get<PerfTestRequest>(`${BASE_URL}/requests/${id}/`),
  create: (data: Partial<PerfTestRequest>) => request.post<PerfTestRequest>(`${BASE_URL}/requests/`, data),
  update: (id: number, data: Partial<PerfTestRequest>) =>
    request.patch<PerfTestRequest>(`${BASE_URL}/requests/${id}/`, data),
  delete: (id: number) => request.delete(`${BASE_URL}/requests/${id}/`),
}

export const perfPlanApi = {
  list: (params?: { scenario?: number }) =>
    request.get<PaginatedResponse<PerfTestPlan>>(`${BASE_URL}/plans/`, { params }),
  get: (id: number) => request.get<PerfTestPlan>(`${BASE_URL}/plans/${id}/`),
  create: (data: Partial<PerfTestPlan>) => request.post<PerfTestPlan>(`${BASE_URL}/plans/`, data),
  update: (id: number, data: Partial<PerfTestPlan>) =>
    request.patch<PerfTestPlan>(`${BASE_URL}/plans/${id}/`, data),
  delete: (id: number) => request.delete(`${BASE_URL}/plans/${id}/`),
}

export const perfExecutionApi = {
  list: (params?: { scenario?: number; status?: string }) =>
    request.get<PaginatedResponse<PerfTestExecution>>(`${BASE_URL}/executions/`, { params }),
  get: (id: number) => request.get<PerfTestExecution>(`${BASE_URL}/executions/${id}/`),
  start: (id: number) => request.post<PerfTestExecution>(`${BASE_URL}/executions/${id}/start/`),
  stop: (id: number) => request.post<PerfTestExecution>(`${BASE_URL}/executions/${id}/stop/`),
}

export const perfReportApi = {
  list: (params?: { execution?: number }) =>
    request.get<PaginatedResponse<PerfTestReport>>(`${BASE_URL}/reports/`, { params }),
  get: (id: number) => request.get<PerfTestReport>(`${BASE_URL}/reports/${id}/`),
  diagnose: (id: number) => request.post<{ task_id: string; report_id: number }>(`${BASE_URL}/reports/${id}/diagnose/`),
}

export const perfNodeApi = {
  list: (params?: { status?: string }) =>
    request.get<PaginatedResponse<PerfTestNode>>(`${BASE_URL}/nodes/`, { params }),
}
