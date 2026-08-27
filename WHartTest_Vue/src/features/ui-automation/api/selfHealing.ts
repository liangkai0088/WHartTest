// UI 自愈记录 API 服务

import request from '@/utils/request'

const BASE_URL = '/ui-automation'

export interface UiSelfHealingRecord {
  id: number
  execution_record: number | null
  test_case: number | null
  test_case_name: string
  element: number | null
  element_name: string
  step_id: number | null
  failure_message: string
  status: 'pending' | 'diagnosing' | 'healed' | 'failed' | 'ignored'
  diagnosis: Record<string, any>
  fix_summary: {
    element_id?: number
    old?: { locator_type: string; locator_value: string }
    new?: { locator_type: string; locator_value: string }
    reason?: string
    error?: string
  } | Record<string, any>
  rerun_batch_id: number | null
  rerun_success: boolean | null
  retry_count: number
  max_retry: number
  created_at: string
  updated_at: string
}

export interface UiSelfHealingStats {
  total: number
  status_counts: Record<string, number>
  success_rate: number
  rerun_total: number
  rerun_success: number
}

export const selfHealingApi = {
  list: (params?: { status?: string; test_case?: number; rerun_success?: boolean; search?: string }) =>
    request.get(`${BASE_URL}/self-healing-records/`, { params }),

  stats: () => request.get<UiSelfHealingStats>(`${BASE_URL}/self-healing-records/stats/`),
}
