// 代码覆盖率 API 服务

import request from '@/utils/request'
import type {
  CoverageReport,
  CoverageFile,
  CoverageDelta,
  CoverageUploadForm,
  CoverageGateConfig,
  CoverageGateResult,
  PaginatedResponse,
} from '../types'

const BASE_URL = '/code-coverage'

export const coverageReportApi = {
  list: (params?: { project?: number; format?: string; test_type?: string; status?: string; search?: string }) =>
    request.get<PaginatedResponse<CoverageReport>>(`${BASE_URL}/reports/`, { params }),

  get: (id: string) => request.get<CoverageReport>(`${BASE_URL}/reports/${id}/`),

  upload: (form: CoverageUploadForm) => {
    const data = new FormData()
    data.append('project_id', String(form.project_id))
    data.append('name', form.name)
    data.append('format', form.format)
    if (form.test_type) data.append('test_type', form.test_type)
    if (form.test_execution_ref) data.append('test_execution_ref', form.test_execution_ref)
    if (form.git_commit) data.append('git_commit', form.git_commit)
    data.append('file', form.file)
    return request.post<CoverageReport>(`${BASE_URL}/reports/`, data)
  },

  files: (id: string) =>
    request.get<PaginatedResponse<CoverageFile>>(`${BASE_URL}/reports/${id}/files/`),

  generateDelta: (id: string, baseReportId: string) =>
    request.post<CoverageDelta>(`${BASE_URL}/reports/${id}/generate_delta/`, { base_report_id: baseReportId }),

  checkGate: (id: string) => request.get<CoverageGateResult>(`${BASE_URL}/reports/${id}/check_gate/`),
}

export const coverageDeltaApi = {
  list: (params?: { project?: number; git_commit?: string; base_commit?: string }) =>
    request.get<PaginatedResponse<CoverageDelta>>(`${BASE_URL}/deltas/`, { params }),

  get: (id: string) => request.get<CoverageDelta>(`${BASE_URL}/deltas/${id}/`),
}

export const coverageGateApi = {
  byProject: (project: number) =>
    request.get<CoverageGateConfig>(`${BASE_URL}/gate-config/by_project/`, { params: { project } }),

  update: (id: number, data: Partial<CoverageGateConfig>) =>
    request.patch<CoverageGateConfig>(`${BASE_URL}/gate-config/${id}/`, data),
}
