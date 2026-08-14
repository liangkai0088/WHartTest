import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { CodeAnalysisService } from '../services/codeAnalysisService';
import type {
  CodeProject,
  Snapshot,
  CodeFile,
  SpecAnalysisTask,
  SpecSuggestion,
  ComponentAnalysisTask,
  ElementSuggestion,
  ApproveRejectResult,
  GitImportResult,
  ChangeSummary,
  TestCodeLink,
  ChangeImpactRecord,
} from '../services/codeAnalysisService';

export const useCodeAnalysisStore = defineStore('codeAnalysis', () => {
  // ─── State ───
  const codeProjects = ref<CodeProject[]>([]);
  const selectedProjectId = ref<number | null>(null);
  const currentSnapshot = ref<Snapshot | null>(null);
  const loading = ref(false);
  const uploadProgress = ref(0);
  const uploading = ref(false);

  // Files
  const codeFiles = ref<CodeFile[]>([]);
  const filesLoading = ref(false);

  // Spec analysis
  const specTasks = ref<SpecAnalysisTask[]>([]);
  const currentSpecTaskId = ref<number | null>(null);
  const specSuggestions = ref<SpecSuggestion[]>([]);
  const specLoading = ref(false);

  // Component analysis
  const componentTasks = ref<ComponentAnalysisTask[]>([]);
  const currentComponentTaskId = ref<number | null>(null);
  const elementSuggestions = ref<ElementSuggestion[]>([]);
  const componentLoading = ref(false);

  // Links
  const links = ref<TestCodeLink[]>([]);
  const linksLoading = ref(false);

  // Impacts
  const impacts = ref<ChangeImpactRecord[]>([]);
  const impactsLoading = ref(false);

  // Change analysis / Git import
  const changeAnalysisRunning = ref(false);
  const gitImportRunning = ref(false);
  const lastChangeSummary = ref<ChangeSummary | null>(null);

  // ─── Computed ───
  const selectedProject = computed(() =>
    codeProjects.value.find((p) => p.id === selectedProjectId.value) ?? null,
  );

  const currentSpecTask = computed(() =>
    specTasks.value.find((t) => t.id === currentSpecTaskId.value) ?? null,
  );

  const currentComponentTask = computed(() =>
    componentTasks.value.find((t) => t.id === currentComponentTaskId.value) ?? null,
  );

  const outdatedLinksCount = computed(() =>
    links.value.filter((l) => l.status === 'outdated').length,
  );

  const unresolvedImpactsCount = computed(() =>
    impacts.value.filter((i) => !i.resolved).length,
  );

  // ─── Actions: Projects ───

  async function loadProjects(projectId: number) {
    loading.value = true;
    try {
      codeProjects.value = await CodeAnalysisService.listProjects(projectId);
      if (!selectedProjectId.value && codeProjects.value.length > 0) {
        selectedProjectId.value = codeProjects.value[0].id;
      }
    } catch (e) {
      console.error('loadProjects failed', e);
    } finally {
      loading.value = false;
    }
  }

  async function createProject(projectId: number, name: string) {
    const project = await CodeAnalysisService.createProject(projectId, name);
    codeProjects.value.push(project);
    selectedProjectId.value = project.id;
    return project;
  }

  async function uploadZip(projectId: number, codeProjectId: number, file: File) {
    uploading.value = true;
    uploadProgress.value = 0;
    try {
      const snapshot = await CodeAnalysisService.uploadZip(
        projectId,
        codeProjectId,
        file,
        (pct) => { uploadProgress.value = pct; },
      );
      currentSnapshot.value = snapshot;
      // refresh project list to update snapshot info
      await loadProjects(projectId);
      return snapshot;
    } finally {
      uploading.value = false;
      uploadProgress.value = 0;
    }
  }

  // ─── Actions: Files ───

  async function loadFiles(projectId: number, codeProjectId: number, params?: { snapshot_id?: number; q?: string }) {
    filesLoading.value = true;
    try {
      codeFiles.value = await CodeAnalysisService.listFiles(projectId, codeProjectId, params || {});
    } catch (e) {
      console.error('loadFiles failed', e);
      codeFiles.value = [];
    } finally {
      filesLoading.value = false;
    }
  }

  async function loadFileContent(projectId: number, codeProjectId: number, fileId: number) {
    return await CodeAnalysisService.getFileContent(projectId, codeProjectId, fileId);
  }

  // ─── Actions: Spec Analysis ───

  async function runSpecAnalysis(projectId: number, opts: { file?: File; specUrl?: string }) {
    specLoading.value = true;
    try {
      let task: SpecAnalysisTask;
      if (opts.file) {
        task = await CodeAnalysisService.runSpecAnalysisByFile(projectId, opts.file);
      } else if (opts.specUrl) {
        task = await CodeAnalysisService.runSpecAnalysisByUrl(projectId, opts.specUrl);
      } else {
        throw new Error('Must provide file or specUrl');
      }
      specTasks.value.unshift(task);
      currentSpecTaskId.value = task.id;
      return task;
    } finally {
      specLoading.value = false;
    }
  }

  async function loadSpecSuggestions(projectId: number, taskId: number, status?: string) {
    specLoading.value = true;
    try {
      specSuggestions.value = await CodeAnalysisService.getSpecSuggestions(projectId, taskId, { status });
    } catch (e) {
      console.error('loadSpecSuggestions failed', e);
      specSuggestions.value = [];
    } finally {
      specLoading.value = false;
    }
  }

  async function refreshSpecTask(projectId: number, taskId: number) {
    try {
      const task = await CodeAnalysisService.getSpecAnalysisTask(projectId, taskId);
      const idx = specTasks.value.findIndex((t) => t.id === taskId);
      if (idx >= 0) specTasks.value[idx] = task;
      return task;
    } catch (e) {
      console.error('refreshSpecTask failed', e);
      return null;
    }
  }

  async function approveSpecSuggestions(projectId: number, taskId: number, ids: number[]): Promise<ApproveRejectResult[]> {
    const results = await CodeAnalysisService.approveSpecSuggestions(projectId, taskId, ids);
    // refresh suggestions
    await loadSpecSuggestions(projectId, taskId, 'pending');
    await refreshSpecTask(projectId, taskId);
    return results;
  }

  async function rejectSpecSuggestions(projectId: number, taskId: number, ids: number[]): Promise<ApproveRejectResult[]> {
    const results = await CodeAnalysisService.rejectSpecSuggestions(projectId, taskId, ids);
    await loadSpecSuggestions(projectId, taskId, 'pending');
    await refreshSpecTask(projectId, taskId);
    return results;
  }

  // ─── Actions: Component Analysis ───

  async function runComponentAnalysis(projectId: number, params?: { snapshot_id?: number; file_filter?: string }) {
    componentLoading.value = true;
    try {
      const task = await CodeAnalysisService.runComponentAnalysis(projectId, params);
      componentTasks.value.unshift(task);
      currentComponentTaskId.value = task.id;
      return task;
    } finally {
      componentLoading.value = false;
    }
  }

  async function loadElementSuggestions(projectId: number, taskId: number, status?: string) {
    componentLoading.value = true;
    try {
      elementSuggestions.value = await CodeAnalysisService.getElementSuggestions(projectId, taskId, { status });
    } catch (e) {
      console.error('loadElementSuggestions failed', e);
      elementSuggestions.value = [];
    } finally {
      componentLoading.value = false;
    }
  }

  async function refreshComponentTask(projectId: number, taskId: number) {
    try {
      const task = await CodeAnalysisService.getComponentAnalysisTask(projectId, taskId);
      const idx = componentTasks.value.findIndex((t) => t.id === taskId);
      if (idx >= 0) componentTasks.value[idx] = task;
      return task;
    } catch (e) {
      console.error('refreshComponentTask failed', e);
      return null;
    }
  }

  async function approveElementSuggestions(projectId: number, taskId: number, ids: number[]): Promise<ApproveRejectResult[]> {
    const results = await CodeAnalysisService.approveElementSuggestions(projectId, taskId, ids);
    await loadElementSuggestions(projectId, taskId, 'pending');
    await refreshComponentTask(projectId, taskId);
    return results;
  }

  async function rejectElementSuggestions(projectId: number, taskId: number, ids: number[]): Promise<ApproveRejectResult[]> {
    const results = await CodeAnalysisService.rejectElementSuggestions(projectId, taskId, ids);
    await loadElementSuggestions(projectId, taskId, 'pending');
    await refreshComponentTask(projectId, taskId);
    return results;
  }

  // ─── Actions: Git Import ───

  async function gitImport(projectId: number, codeProjectId: number, gitUrl: string, branch?: string): Promise<GitImportResult> {
    gitImportRunning.value = true;
    try {
      const result = await CodeAnalysisService.gitImport(projectId, codeProjectId, gitUrl, branch);
      await loadProjects(projectId);
      return result;
    } finally {
      gitImportRunning.value = false;
    }
  }

  // ─── Actions: Change Analysis ───

  async function analyzeChanges(projectId: number, codeProjectId: number): Promise<ChangeSummary> {
    changeAnalysisRunning.value = true;
    try {
      const summary = await CodeAnalysisService.analyzeChanges(projectId, codeProjectId);
      lastChangeSummary.value = summary;
      // reload impacts after analysis
      await loadImpacts(projectId, codeProjectId);
      return summary;
    } finally {
      changeAnalysisRunning.value = false;
    }
  }

  // ─── Actions: Links ───

  async function loadLinks(projectId: number, codeProjectId: number, status?: string) {
    linksLoading.value = true;
    try {
      links.value = await CodeAnalysisService.listLinks(projectId, codeProjectId, status ? { status } : undefined);
    } catch (e) {
      console.error('loadLinks failed', e);
      links.value = [];
    } finally {
      linksLoading.value = false;
    }
  }

  async function createLink(
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
    const link = await CodeAnalysisService.createLink(projectId, codeProjectId, data);
    links.value.unshift(link);
    return link;
  }

  async function deleteLink(projectId: number, codeProjectId: number, linkId: number) {
    await CodeAnalysisService.deleteLink(projectId, codeProjectId, linkId);
    links.value = links.value.filter((l) => l.id !== linkId);
  }

  // ─── Actions: Impacts ───

  async function loadImpacts(projectId: number, codeProjectId: number, resolved?: boolean) {
    impactsLoading.value = true;
    try {
      const params: { resolved?: boolean } = {};
      if (resolved !== undefined) params.resolved = resolved;
      impacts.value = await CodeAnalysisService.listImpacts(projectId, codeProjectId, params);
    } catch (e) {
      console.error('loadImpacts failed', e);
      impacts.value = [];
    } finally {
      impactsLoading.value = false;
    }
  }

  async function resolveImpact(projectId: number, codeProjectId: number, impactId: number) {
    await CodeAnalysisService.resolveImpact(projectId, codeProjectId, impactId);
    const idx = impacts.value.findIndex((i) => i.id === impactId);
    if (idx >= 0) impacts.value[idx].resolved = true;
  }

  return {
    // state
    codeProjects,
    selectedProjectId,
    selectedProject,
    currentSnapshot,
    loading,
    uploadProgress,
    uploading,
    codeFiles,
    filesLoading,
    specTasks,
    currentSpecTaskId,
    currentSpecTask,
    specSuggestions,
    specLoading,
    componentTasks,
    currentComponentTaskId,
    currentComponentTask,
    elementSuggestions,
    componentLoading,
    links,
    linksLoading,
    impacts,
    impactsLoading,
    changeAnalysisRunning,
    gitImportRunning,
    lastChangeSummary,
    outdatedLinksCount,
    unresolvedImpactsCount,
    // actions
    loadProjects,
    createProject,
    uploadZip,
    loadFiles,
    loadFileContent,
    runSpecAnalysis,
    loadSpecSuggestions,
    refreshSpecTask,
    approveSpecSuggestions,
    rejectSpecSuggestions,
    runComponentAnalysis,
    loadElementSuggestions,
    refreshComponentTask,
    approveElementSuggestions,
    rejectElementSuggestions,
    gitImport,
    analyzeChanges,
    loadLinks,
    createLink,
    deleteLink,
    loadImpacts,
    resolveImpact,
  };
});
