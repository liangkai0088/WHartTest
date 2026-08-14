/**
 * 执行看板 REST API 服务
 */

import { request } from '@/utils/request'
import type { SnapshotResponse, EventRecord } from '../types'
import { getTestExecutionList, type TestExecutionListResponse } from '@/services/testExecutionService'

/**
 * 获取执行快照
 */
export const getRunSnapshot = (runId: number) =>
  request<SnapshotResponse>({
    url: `/execution-dashboard/runs/${runId}/snapshot/`,
    method: 'get',
  })

/**
 * 获取执行事件列表（游标分页）
 */
export const getRunEvents = (
  runId: number,
  params?: { after_id?: number; limit?: number }
) =>
  request<EventRecord[]>({
    url: `/execution-dashboard/runs/${runId}/events/`,
    method: 'get',
    params: {
      limit: params?.limit ?? 500,
      ...(params?.after_id ? { after_id: params.after_id } : {}),
    },
  })

/**
 * 获取所有执行事件（循环拉取直到耗尽，最多 cap 条）
 */
export const getAllRunEvents = async (
  runId: number,
  cap = 5000
): Promise<EventRecord[]> => {
  const all: EventRecord[] = []
  let afterId: number | undefined = undefined
  const limit = 500

  while (all.length < cap) {
    const res = await getRunEvents(runId, { after_id: afterId, limit })
    if (!res.success || !res.data || res.data.length === 0) break
    all.push(...res.data)
    afterId = res.data[res.data.length - 1].id
    if (res.data.length < limit) break
  }

  return all.slice(0, cap)
}

/**
 * 获取运行列表（复用已有测试执行列表 API）
 */
export const getRunsList = (
  projectId: number,
  params?: { search?: string; ordering?: string }
): Promise<TestExecutionListResponse> => {
  return getTestExecutionList(projectId, params)
}
