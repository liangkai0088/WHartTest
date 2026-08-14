import { request } from '@/utils/request';
import service from '@/utils/request';

// ─── Types ───

export type QaEngine = 'midscene' | 'agent_browser';

export interface QaSuite {
  id: number;
  name: string;
  group: string | null;
  engine: QaEngine;
  base_url: string | null;
  description: string | null;
  source: string | null;
  status: string;
  test_count: number;
  yaml_content: string | null;
  llm_config_id: number | null;
  created_at: string;
}

export interface QaRunSummary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  warnings: number;
  duration: number;
}

export interface QaRun {
  id: number;
  suite_id: number;
  batch_id: string | null;
  status: string;
  summary: QaRunSummary | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  report_md?: string | null;
}

export interface QaStepResult {
  id: number;
  test_index: number;
  test_name: string;
  step_index: number;
  action: string;
  status: string;
  error: string | null;
  screenshot_path: string | null;
  locator_meta: string | null;
  duration_ms: number | null;
}

export interface QaRunDetail {
  run: QaRun;
  steps: QaStepResult[];
}

export interface BatchRunResult {
  batch_id: string;
  runs: Array<{ suite_id: number; run_id: number; status: string }>;
}

export interface LocatorCacheEntry {
  id: number;
  description: string;
  selector: string;
  strategy: string;
  hits: number;
  updated_at: string;
}

export interface PrdGenerateResult {
  suite_id: number;
  status: string;
}

// ─── Helper ───

function base(projectId: number): string {
  return `/projects/${projectId}/web-qa`;
}

// ─── Service ───

export const WebQaService = {
  // ==================== Suites ====================

  async listSuites(projectId: number): Promise<QaSuite[]> {
    const res = await request<QaSuite[]>({
      url: `${base(projectId)}/suites/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list suites');
  },

  async getSuite(projectId: number, suiteId: number): Promise<QaSuite> {
    const res = await request<QaSuite>({
      url: `${base(projectId)}/suites/${suiteId}/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get suite');
  },

  async createSuite(
    projectId: number,
    data: {
      name: string;
      group?: string;
      engine?: QaEngine;
      base_url?: string;
      description?: string;
      yaml_content?: string;
      llm_config_id?: number;
    },
  ): Promise<QaSuite> {
    const res = await request<QaSuite>({
      url: `${base(projectId)}/suites/`,
      method: 'POST',
      data,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to create suite');
  },

  async updateSuite(
    projectId: number,
    suiteId: number,
    data: Partial<{
      name: string;
      group: string;
      engine: QaEngine;
      base_url: string;
      description: string;
      llm_config_id: number;
    }>,
  ): Promise<QaSuite> {
    const res = await request<QaSuite>({
      url: `${base(projectId)}/suites/${suiteId}/`,
      method: 'PUT',
      data,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to update suite');
  },

  async updateSuiteYaml(
    projectId: number,
    suiteId: number,
    yamlContent: string,
  ): Promise<QaSuite> {
    const res = await request<QaSuite>({
      url: `${base(projectId)}/suites/${suiteId}/yaml/`,
      method: 'PUT',
      data: { yaml_content: yamlContent },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to update YAML');
  },

  async deleteSuite(projectId: number, suiteId: number): Promise<void> {
    const res = await request<void>({
      url: `${base(projectId)}/suites/${suiteId}/`,
      method: 'DELETE',
    });
    if (!res.success) throw new Error(res.error || 'Failed to delete suite');
  },

  async importSuite(
    projectId: number,
    file: File,
    group?: string,
    engine?: QaEngine,
    onProgress?: (percent: number) => void,
  ): Promise<QaSuite> {
    const formData = new FormData();
    formData.append('file', file);
    if (group) formData.append('group', group);
    if (engine) formData.append('engine', engine);

    const res = await service.post(
      `${(service.defaults.baseURL || '/api')}${base(projectId)}/suites/import/`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (ev) => {
          if (ev.total && onProgress) {
            onProgress(Math.round((ev.loaded * 100) / ev.total));
          }
        },
      },
    );

    const body = res.data;
    if (body && body.status === 'success' && body.data) {
      return body.data as QaSuite;
    }
    throw new Error(body?.message || 'Failed to import suite');
  },

  async runSuite(
    projectId: number,
    suiteId: number,
  ): Promise<{ run_id: number; status: string }> {
    const res = await request<{ run_id: number; status: string }>({
      url: `${base(projectId)}/suites/${suiteId}/run/`,
      method: 'POST',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to run suite');
  },

  // ==================== Batch ====================

  async batchRun(
    projectId: number,
    data: { suite_ids?: number[]; group?: string },
  ): Promise<BatchRunResult> {
    const res = await request<BatchRunResult>({
      url: `${base(projectId)}/batch-run/`,
      method: 'POST',
      data,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to batch run');
  },

  // ==================== Runs ====================

  async listRuns(
    projectId: number,
    params?: { suite_id?: number; batch_id?: string },
  ): Promise<QaRun[]> {
    const res = await request<QaRun[]>({
      url: `${base(projectId)}/runs/`,
      method: 'GET',
      params,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list runs');
  },

  async getRunDetail(projectId: number, runId: number): Promise<QaRunDetail> {
    const res = await request<QaRunDetail>({
      url: `${base(projectId)}/runs/${runId}/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get run detail');
  },

  async getRunReportMd(projectId: number, runId: number): Promise<string> {
    const res = await request<string>({
      url: `${base(projectId)}/runs/${runId}/report.md/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get report');
  },

  // ==================== PRD Generate ====================

  async prdGenerate(
    projectId: number,
    data: { requirement_document_id?: number; text?: string },
  ): Promise<PrdGenerateResult> {
    const res = await request<PrdGenerateResult>({
      url: `${base(projectId)}/prd-generate/`,
      method: 'POST',
      data,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to generate from PRD');
  },

  // ==================== Locator Cache ====================

  async listLocatorCache(projectId: number): Promise<LocatorCacheEntry[]> {
    const res = await request<LocatorCacheEntry[]>({
      url: `${base(projectId)}/locator-cache/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list locator cache');
  },

  async deleteLocatorCache(projectId: number, cacheId: number): Promise<void> {
    const res = await request<void>({
      url: `${base(projectId)}/locator-cache/${cacheId}/`,
      method: 'DELETE',
    });
    if (!res.success) throw new Error(res.error || 'Failed to delete cache entry');
  },
};

export const {
  listSuites,
  getSuite,
  createSuite,
  updateSuite,
  updateSuiteYaml,
  deleteSuite,
  importSuite,
  runSuite,
  batchRun,
  listRuns,
  getRunDetail,
  getRunReportMd,
  prdGenerate,
  listLocatorCache,
  deleteLocatorCache,
} = WebQaService;
