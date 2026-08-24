import { request } from '@/utils/request';
import service from '@/utils/request';

// ─── Types ───

export interface CodeProject {
  id: number;
  name: string;
  source_type: string;
  current_snapshot_id?: number | null;
  current_snapshot_version?: number | null;
  current_snapshot_file_count?: number | null;
  snapshot_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface Snapshot {
  id: number;
  version_no: number;
  file_count: number;
  project_id?: number;
  created_at?: string;
}

export interface CodeFile {
  id: number;
  path: string;
  language: string;
  size: number;
  sha256: string;
  content_stored: boolean;
}

export interface FileContentResponse {
  path: string;
  content: string;
}

export interface SpecAnalysisTask {
  id: number;
  status: string;
  spec_name: string;
  suggestion_count?: number;
  approved_count?: number;
  rejected_count?: number;
  warnings?: string[];
  created_at?: string;
  updated_at?: string;
}

export interface SpecSuggestionPayload {
  name: string;
  method: string;
  path: string;
  priority: string;
  description: string;
  steps: string[];
}

export interface SpecSuggestion {
  id: number;
  status: string;
  payload: SpecSuggestionPayload;
  imported_interface_id?: number | null;
  task_id?: number;
}

export interface ComponentAnalysisTask {
  id: number;
  status: string;
  suggestion_count?: number;
  approved_count?: number;
  rejected_count?: number;
  warnings?: string[];
  snapshot_id?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ElementLocator {
  type: string;
  value: string;
}

export interface ElementSuggestionPayload {
  page_name: string;
  file_path: string;
  element_name: string;
  locator: {
    primary: ElementLocator;
    backups: ElementLocator[];
    iframe?: string;
  };
}

export interface ElementSuggestion {
  id: number;
  status: string;
  payload: ElementSuggestionPayload;
  task_id?: number;
}

export interface ApproveRejectResult {
  id: number;
  success: boolean;
  message?: string;
}

export interface GitImportResult {
  snapshot_id: number;
  status: string;
}

export interface ChangeSummary {
  changed_files: number;
  added: number;
  modified: number;
  deleted: number;
  impacted_links: number;
  records_created: number;
  snapshot_id: number;
}

export interface TestCodeLink {
  id: number;
  testcase_type: 'functional' | 'api' | 'ui';
  testcase_id: number;
  testcase_name: string;
  code_file_id?: number | null;
  code_file_path?: string;
  path?: string;
  symbol?: string;
  locator_ref?: string;
  status: 'linked' | 'outdated';
  last_verified_at?: string | null;
  created_at?: string;
}

export interface DiffHunk {
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  added: number;
  removed: number;
}

export interface DiffSummary {
  hunks?: DiffHunk[];
  files_changed?: number;
  truncated?: boolean;
  status?: 'added' | 'modified' | 'deleted';
  old_sha256?: string;
  new_sha256?: string;
  size_delta?: number;
}

export interface ChangeImpactRecord {
  id: number;
  code_file_id: number;
  code_file_path: string;
  path?: string;
  testcase_type: string;
  testcase_id: number;
  testcase_name: string;
  diff_status: 'added' | 'modified' | 'deleted';
  old_sha256?: string;
  new_sha256?: string;
  size_delta?: number;
  diff_summary?: DiffSummary | null;
  resolved: boolean;
  created_at?: string;
}

// ─── Helper: build base URL ───

function base(projectId: number): string {
  return `/projects/${projectId}/code`;
}

// ─── Service ───

export const CodeAnalysisService = {
  // ==================== Projects ====================

  async listProjects(projectId: number): Promise<CodeProject[]> {
    const res = await request<CodeProject[]>({
      url: `${base(projectId)}/projects/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list code projects');
  },

  async createProject(projectId: number, name: string): Promise<CodeProject> {
    const res = await request<CodeProject>({
      url: `${base(projectId)}/projects/`,
      method: 'POST',
      data: { name },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to create code project');
  },

  // ==================== Snapshots ====================

  async uploadZip(
    projectId: number,
    codeProjectId: number,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<Snapshot> {
    const formData = new FormData();
    formData.append('file', file);

    const res = await service.post(
      `${(service.defaults.baseURL || '/api')}${base(projectId)}/projects/${codeProjectId}/upload/`,
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
      return body.data as Snapshot;
    }
    throw new Error(body?.message || 'Failed to upload zip');
  },

  // ==================== Files ====================

  async listFiles(
    projectId: number,
    codeProjectId: number,
    params: { snapshot_id?: number; q?: string },
  ): Promise<CodeFile[]> {
    const res = await request<{ files: CodeFile[] } | CodeFile[]>({
      url: `${base(projectId)}/projects/${codeProjectId}/files/`,
      method: 'GET',
      params,
    });
    if (res.success) {
      const d = res.data as any;
      if (Array.isArray(d)) return d;
      if (d?.files) return d.files;
      return [];
    }
    throw new Error(res.error || 'Failed to list files');
  },

  async getFileContent(
    projectId: number,
    codeProjectId: number,
    fileId: number,
  ): Promise<FileContentResponse> {
    const res = await request<FileContentResponse>({
      url: `${base(projectId)}/projects/${codeProjectId}/files/${fileId}/content/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get file content');
  },

  // ==================== Spec Analysis ====================

  async runSpecAnalysisByFile(
    projectId: number,
    file: File,
  ): Promise<SpecAnalysisTask> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await request<SpecAnalysisTask>({
      url: `${base(projectId)}/spec-analysis/`,
      method: 'POST',
      data: formData,
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to run spec analysis');
  },

  async runSpecAnalysisByUrl(
    projectId: number,
    specUrl: string,
  ): Promise<SpecAnalysisTask> {
    const res = await request<SpecAnalysisTask>({
      url: `${base(projectId)}/spec-analysis/`,
      method: 'POST',
      data: { spec_url: specUrl },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to run spec analysis');
  },

  async getSpecAnalysisTask(
    projectId: number,
    taskId: number,
  ): Promise<SpecAnalysisTask> {
    const res = await request<SpecAnalysisTask>({
      url: `${base(projectId)}/spec-analysis/${taskId}/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get spec analysis task');
  },

  async getSpecSuggestions(
    projectId: number,
    taskId: number,
    params?: { status?: string },
  ): Promise<SpecSuggestion[]> {
    const res = await request<SpecSuggestion[]>({
      url: `${base(projectId)}/spec-analysis/${taskId}/suggestions/`,
      method: 'GET',
      params,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get spec suggestions');
  },

  async approveSpecSuggestions(
    projectId: number,
    taskId: number,
    suggestionIds: number[],
  ): Promise<ApproveRejectResult[]> {
    const res = await request<ApproveRejectResult[]>({
      url: `${base(projectId)}/spec-analysis/${taskId}/approve/`,
      method: 'POST',
      data: { suggestion_ids: suggestionIds },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to approve suggestions');
  },

  async rejectSpecSuggestions(
    projectId: number,
    taskId: number,
    suggestionIds: number[],
  ): Promise<ApproveRejectResult[]> {
    const res = await request<ApproveRejectResult[]>({
      url: `${base(projectId)}/spec-analysis/${taskId}/reject/`,
      method: 'POST',
      data: { suggestion_ids: suggestionIds },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to reject suggestions');
  },

  // ==================== Component Analysis ====================

  async runComponentAnalysis(
    projectId: number,
    params?: { snapshot_id?: number; file_filter?: string },
  ): Promise<ComponentAnalysisTask> {
    const res = await request<ComponentAnalysisTask>({
      url: `${base(projectId)}/component-analysis/`,
      method: 'POST',
      data: params || {},
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to run component analysis');
  },

  async getComponentAnalysisTask(
    projectId: number,
    taskId: number,
  ): Promise<ComponentAnalysisTask> {
    const res = await request<ComponentAnalysisTask>({
      url: `${base(projectId)}/component-analysis/${taskId}/`,
      method: 'GET',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get component analysis task');
  },

  async getElementSuggestions(
    projectId: number,
    taskId: number,
    params?: { status?: string },
  ): Promise<ElementSuggestion[]> {
    const res = await request<ElementSuggestion[]>({
      url: `${base(projectId)}/component-analysis/${taskId}/element-suggestions/`,
      method: 'GET',
      params,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to get element suggestions');
  },

  async approveElementSuggestions(
    projectId: number,
    taskId: number,
    suggestionIds: number[],
  ): Promise<ApproveRejectResult[]> {
    const res = await request<ApproveRejectResult[]>({
      url: `${base(projectId)}/component-analysis/${taskId}/approve/`,
      method: 'POST',
      data: { suggestion_ids: suggestionIds },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to approve element suggestions');
  },

  async rejectElementSuggestions(
    projectId: number,
    taskId: number,
    suggestionIds: number[],
  ): Promise<ApproveRejectResult[]> {
    const res = await request<ApproveRejectResult[]>({
      url: `${base(projectId)}/component-analysis/${taskId}/reject/`,
      method: 'POST',
      data: { suggestion_ids: suggestionIds },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to reject element suggestions');
  },

  // ==================== Git Import ====================

  async gitImport(
    projectId: number,
    codeProjectId: number,
    gitUrl: string,
    branch?: string,
  ): Promise<GitImportResult> {
    const res = await request<GitImportResult>({
      url: `${base(projectId)}/projects/${codeProjectId}/git-import/`,
      method: 'POST',
      data: { git_url: gitUrl, branch: branch || undefined },
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to import from git');
  },

  // ==================== Change Analysis ====================

  async analyzeChanges(
    projectId: number,
    codeProjectId: number,
  ): Promise<ChangeSummary> {
    const res = await request<ChangeSummary>({
      url: `${base(projectId)}/projects/${codeProjectId}/analyze-changes/`,
      method: 'POST',
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to analyze changes');
  },

  // ==================== Links ====================

  async listLinks(
    projectId: number,
    codeProjectId: number,
    params?: { status?: string },
  ): Promise<TestCodeLink[]> {
    const res = await request<TestCodeLink[]>({
      url: `${base(projectId)}/projects/${codeProjectId}/links/`,
      method: 'GET',
      params,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list links');
  },

  async createLink(
    projectId: number,
    codeProjectId: number,
    data: {
      testcase_type: string;
      testcase_id: number;
      code_file_id?: number;
      path?: string;
      symbol?: string;
      locator_ref?: string;
    },
  ): Promise<TestCodeLink> {
    const res = await request<TestCodeLink>({
      url: `${base(projectId)}/projects/${codeProjectId}/links/`,
      method: 'POST',
      data,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to create link');
  },

  async deleteLink(
    projectId: number,
    codeProjectId: number,
    linkId: number,
  ): Promise<void> {
    const res = await request<void>({
      url: `${base(projectId)}/projects/${codeProjectId}/links/${linkId}/`,
      method: 'DELETE',
    });
    if (!res.success) throw new Error(res.error || 'Failed to delete link');
  },

  // ==================== Impacts ====================

  async listImpacts(
    projectId: number,
    codeProjectId: number,
    params?: { resolved?: boolean },
  ): Promise<ChangeImpactRecord[]> {
    const res = await request<ChangeImpactRecord[]>({
      url: `${base(projectId)}/projects/${codeProjectId}/impacts/`,
      method: 'GET',
      params,
    });
    if (res.success) return res.data!;
    throw new Error(res.error || 'Failed to list impacts');
  },

  async resolveImpact(
    projectId: number,
    codeProjectId: number,
    impactId: number,
  ): Promise<void> {
    const res = await request<void>({
      url: `${base(projectId)}/projects/${codeProjectId}/impacts/${impactId}/resolve/`,
      method: 'POST',
    });
    if (!res.success) throw new Error(res.error || 'Failed to resolve impact');
  },
};

export const {
  listProjects,
  createProject,
  uploadZip,
  listFiles,
  getFileContent,
  runSpecAnalysisByFile,
  runSpecAnalysisByUrl,
  getSpecAnalysisTask,
  getSpecSuggestions,
  approveSpecSuggestions,
  rejectSpecSuggestions,
  runComponentAnalysis,
  getComponentAnalysisTask,
  getElementSuggestions,
  approveElementSuggestions,
  rejectElementSuggestions,
  gitImport,
  analyzeChanges,
  listLinks,
  createLink,
  deleteLink,
  listImpacts,
  resolveImpact,
} = CodeAnalysisService;
