import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { WebQaService } from '../services/webQaService';
import type {
  QaSuite,
  QaRun,
  QaRunDetail,
  BatchRunResult,
  LocatorCacheEntry,
  QaEngine,
} from '../services/webQaService';

export const useWebQaStore = defineStore('webQa', () => {
  // ─── State ───
  const suites = ref<QaSuite[]>([]);
  const suitesLoading = ref(false);

  const runs = ref<QaRun[]>([]);
  const runsLoading = ref(false);

  const currentRunDetail = ref<QaRunDetail | null>(null);
  const runDetailLoading = ref(false);
  const runReportMd = ref<string | null>(null);

  const batchResult = ref<BatchRunResult | null>(null);
  const batchRuns = ref<QaRun[]>([]);
  const batchLoading = ref(false);

  const locatorCache = ref<LocatorCacheEntry[]>([]);
  const cacheLoading = ref(false);

  const prdGenerating = ref(false);
  const prdGeneratingSuiteId = ref<number | null>(null);

  // ─── Polling ───
  let runPollTimer: ReturnType<typeof setInterval> | null = null;
  let prdPollTimer: ReturnType<typeof setInterval> | null = null;

  // ─── Computed ───
  const groups = computed(() => {
    const set = new Set<string>();
    for (const s of suites.value) {
      if (s.group) set.add(s.group);
    }
    return Array.from(set).sort();
  });

  // ─── Actions: Suites ───

  async function loadSuites(projectId: number) {
    suitesLoading.value = true;
    try {
      suites.value = await WebQaService.listSuites(projectId);
    } catch (e) {
      console.error('loadSuites failed', e);
      suites.value = [];
    } finally {
      suitesLoading.value = false;
    }
  }

  async function refreshSuite(projectId: number, suiteId: number) {
    try {
      const suite = await WebQaService.getSuite(projectId, suiteId);
      const idx = suites.value.findIndex((s) => s.id === suiteId);
      if (idx >= 0) suites.value[idx] = suite;
      return suite;
    } catch (e) {
      console.error('refreshSuite failed', e);
      return null;
    }
  }

  async function createSuite(
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
  ) {
    const suite = await WebQaService.createSuite(projectId, data);
    suites.value.unshift(suite);
    return suite;
  }

  async function updateSuite(
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
  ) {
    const suite = await WebQaService.updateSuite(projectId, suiteId, data);
    const idx = suites.value.findIndex((s) => s.id === suiteId);
    if (idx >= 0) suites.value[idx] = suite;
    return suite;
  }

  async function updateSuiteYaml(projectId: number, suiteId: number, yamlContent: string) {
    const suite = await WebQaService.updateSuiteYaml(projectId, suiteId, yamlContent);
    const idx = suites.value.findIndex((s) => s.id === suiteId);
    if (idx >= 0) suites.value[idx] = suite;
    return suite;
  }

  async function deleteSuite(projectId: number, suiteId: number) {
    await WebQaService.deleteSuite(projectId, suiteId);
    suites.value = suites.value.filter((s) => s.id !== suiteId);
  }

  async function importSuite(
    projectId: number,
    file: File,
    group?: string,
    engine?: QaEngine,
    onProgress?: (percent: number) => void,
  ) {
    const suite = await WebQaService.importSuite(projectId, file, group, engine, onProgress);
    suites.value.unshift(suite);
    return suite;
  }

  // ─── Actions: Runs ───

  async function loadRuns(projectId: number, params?: { suite_id?: number; batch_id?: string }) {
    runsLoading.value = true;
    try {
      runs.value = await WebQaService.listRuns(projectId, params);
    } catch (e) {
      console.error('loadRuns failed', e);
      runs.value = [];
    } finally {
      runsLoading.value = false;
    }
  }

  async function loadRunDetail(projectId: number, runId: number) {
    runDetailLoading.value = true;
    runReportMd.value = null;
    try {
      currentRunDetail.value = await WebQaService.getRunDetail(projectId, runId);
    } catch (e) {
      console.error('loadRunDetail failed', e);
      currentRunDetail.value = null;
    } finally {
      runDetailLoading.value = false;
    }
  }

  async function loadRunReport(projectId: number, runId: number) {
    try {
      runReportMd.value = await WebQaService.getRunReportMd(projectId, runId);
    } catch (e) {
      console.error('loadRunReport failed', e);
      runReportMd.value = null;
    }
  }

  async function runSuite(projectId: number, suiteId: number) {
    const result = await WebQaService.runSuite(projectId, suiteId);
    return result;
  }

  function startRunPolling(projectId: number, runIds: number[], onComplete?: () => void) {
    stopRunPolling();
    runPollTimer = setInterval(async () => {
      try {
        const allRuns = await WebQaService.listRuns(projectId);
        // Update batch runs from the global list
        for (const run of allRuns) {
          const idx = batchRuns.value.findIndex((r) => r.id === run.id);
          if (idx >= 0) batchRuns.value[idx] = run;
        }
        // Check if all target runs are done
        const allDone = runIds.every((rid) => {
          const r = batchRuns.value.find((x) => x.id === rid) || allRuns.find((x) => x.id === rid);
          return r && r.status !== 'pending' && r.status !== 'running';
        });
        if (allDone) {
          stopRunPolling();
          onComplete?.();
        }
      } catch (e) {
        console.error('run polling error', e);
      }
    }, 3000);
  }

  function stopRunPolling() {
    if (runPollTimer) {
      clearInterval(runPollTimer);
      runPollTimer = null;
    }
  }

  // ─── Actions: Batch ───

  async function batchRun(
    projectId: number,
    data: { suite_ids?: number[]; group?: string },
  ) {
    batchLoading.value = true;
    try {
      const result = await WebQaService.batchRun(projectId, data);
      batchResult.value = result;
      // Load runs for this batch
      const batchRunsList = await WebQaService.listRuns(projectId, { batch_id: result.batch_id });
      batchRuns.value = batchRunsList;
      // Start polling
      const runIds = result.runs.map((r) => r.run_id);
      startRunPolling(projectId, runIds);
      return result;
    } catch (e) {
      console.error('batchRun failed', e);
      throw e;
    } finally {
      batchLoading.value = false;
    }
  }

  // ─── Actions: PRD Generate ───

  async function prdGenerate(
    projectId: number,
    data: { requirement_document_id?: number; text?: string },
    onComplete?: (suiteId: number) => void,
  ) {
    prdGenerating.value = true;
    try {
      const result = await WebQaService.prdGenerate(projectId, data);
      prdGeneratingSuiteId.value = result.suite_id;
      // Start polling
      startPrdPolling(projectId, result.suite_id, onComplete);
      return result;
    } catch (e) {
      prdGenerating.value = false;
      throw e;
    }
  }

  function startPrdPolling(
    projectId: number,
    suiteId: number,
    onComplete?: (suiteId: number) => void,
  ) {
    stopPrdPolling();
    let elapsed = 0;
    prdPollTimer = setInterval(async () => {
      elapsed += 3;
      if (elapsed > 90) {
        stopPrdPolling();
        prdGenerating.value = false;
        prdGeneratingSuiteId.value = null;
        return;
      }
      try {
        const suite = await WebQaService.getSuite(projectId, suiteId);
        const idx = suites.value.findIndex((s) => s.id === suiteId);
        if (idx >= 0) suites.value[idx] = suite;
        else suites.value.unshift(suite);

        if (suite.status !== 'generating') {
          stopPrdPolling();
          prdGenerating.value = false;
          prdGeneratingSuiteId.value = null;
          onComplete?.(suiteId);
        }
      } catch (e) {
        console.error('prd polling error', e);
      }
    }, 3000);
  }

  function stopPrdPolling() {
    if (prdPollTimer) {
      clearInterval(prdPollTimer);
      prdPollTimer = null;
    }
  }

  // ─── Actions: Locator Cache ───

  async function loadLocatorCache(projectId: number) {
    cacheLoading.value = true;
    try {
      locatorCache.value = await WebQaService.listLocatorCache(projectId);
    } catch (e) {
      console.error('loadLocatorCache failed', e);
      locatorCache.value = [];
    } finally {
      cacheLoading.value = false;
    }
  }

  async function deleteLocatorCache(projectId: number, cacheId: number) {
    await WebQaService.deleteLocatorCache(projectId, cacheId);
    locatorCache.value = locatorCache.value.filter((c) => c.id !== cacheId);
  }

  // ─── Cleanup ───

  function cleanup() {
    stopRunPolling();
    stopPrdPolling();
  }

  return {
    // state
    suites,
    suitesLoading,
    runs,
    runsLoading,
    currentRunDetail,
    runDetailLoading,
    runReportMd,
    batchResult,
    batchRuns,
    batchLoading,
    locatorCache,
    cacheLoading,
    prdGenerating,
    prdGeneratingSuiteId,
    groups,
    // actions
    loadSuites,
    refreshSuite,
    createSuite,
    updateSuite,
    updateSuiteYaml,
    deleteSuite,
    importSuite,
    runSuite,
    loadRuns,
    loadRunDetail,
    loadRunReport,
    startRunPolling,
    stopRunPolling,
    batchRun,
    prdGenerate,
    loadLocatorCache,
    deleteLocatorCache,
    cleanup,
  };
});
