// 代码覆盖率模块类型定义

export type CoverageFormat = 'cobertura' | 'lcov'
export type CoverageTestType = 'api' | 'ui' | 'unit' | 'manual'
export type CoverageReportStatus = 'processing' | 'completed' | 'failed'

export interface CoverageSummary {
  lines_total: number
  lines_covered: number
  line_coverage: number
  branches_total: number
  branches_covered: number
  branch_coverage: number
  files_total: number
}

export interface CoverageReport {
  id: string
  project: number
  name: string
  format: CoverageFormat
  test_type: CoverageTestType
  test_execution_ref: string | null
  git_commit: string | null
  status: CoverageReportStatus
  error_message: string | null
  summary: CoverageSummary | null
  uploader: number | null
  uploader_name: string
  file_count: number
  gate: CoverageGateOnReport | null
  created_at: string
}

export interface CoverageFile {
  id: number
  report: string
  file_path: string
  line_coverage: number
  branch_coverage: number | null
  lines_total: number
  lines_covered: number
  lines_detail: Record<string, number>
}

export type CoverageDeltaFileStatus = 'added' | 'modified' | 'removed' | 'unchanged'

export interface CoverageDeltaFile {
  file_path: string
  status: CoverageDeltaFileStatus
  new_lines: number
  covered_new_lines: number
  delta_coverage: number
  removed_lines: number
}

export interface CoverageDelta {
  id: string
  project: number
  report: string | null
  base_report: string | null
  git_commit: string
  base_commit: string | null
  summary: {
    new_lines_total: number
    covered_new_lines: number
    delta_coverage: number
    files_added: number
    files_modified: number
    files_unchanged: number
    files_removed: number
  }
  files: CoverageDeltaFile[]
  uploader: number | null
  uploader_name: string
  created_at: string
}

export interface CoverageUploadForm {
  project_id: number
  name: string
  format: CoverageFormat
  test_type?: CoverageTestType
  test_execution_ref?: string
  git_commit?: string
  file: File
}

export interface CoverageGateConfig {
  id: number
  project: number
  enabled: boolean
  min_line_coverage: number
  created_at: string
  updated_at: string
}

export interface CoverageGateResult {
  enabled: boolean
  threshold: number | null
  actual_line_coverage: number | null
  passed: boolean | null
}

export interface CoverageGateOnReport {
  enabled: boolean
  threshold: number | null
  actual: number | null
  passed: boolean | null
}

/** 分页响应结构 */
export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
