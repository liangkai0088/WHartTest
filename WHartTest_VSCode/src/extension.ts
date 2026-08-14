import * as path from 'path';
import * as http from 'http';
import * as https from 'https';
import * as vscode from 'vscode';
import AdmZip from 'adm-zip';
import FormData from 'form-data';

/**
 * WHartTest「源码级 AI 智能分析」VS Code 扩展
 *
 * 后端 REST 契约（响应统一信封 {status, code, message, data}）：
 *   - 登录            POST {serverUrl}/api/token/                            {username, password} -> data.access (JWT)
 *   - 创建代码项目     POST {serverUrl}/api/projects/{projectId}/code/projects/  {name, source_type:'zip_upload'} -> data.id
 *   - 上传源码 zip     POST {serverUrl}/api/projects/{projectId}/code/projects/{codeProjectId}/upload/   multipart 字段 'file'
 *   - 影响用例列表     GET  {serverUrl}/api/projects/{projectId}/code/projects/{codeProjectId}/impacts/?resolved=false
 *   - 分析页          {serverUrl}/code-analysis（浏览器打开）
 */

const CONFIG_SECTION = 'wharttest';
const SECRET_TOKEN_KEY = 'wharttest.accessToken';

const MAX_FILE_COUNT = 20000;
const MAX_BYTES = 50 * 1024 * 1024; // 50MB

/** findFiles 排除规则：node_modules/.git/dist/build/.next/out/coverage/*.zip/.DS_Store */
const EXCLUDE_GLOB =
  '{**/node_modules/**,**/.git/**,**/dist/**,**/build/**,**/.next/**,**/out/**,**/coverage/**,**/*.zip,**/.DS_Store}';

/** 后端响应信封 */
interface Envelope<T = unknown> {
  status: number;
  code: string;
  message: string;
  data: T;
}

class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/* ------------------------------------------------------------------ */
/* HTTP 基础设施（使用 node 内置 http/https + form-data 包，不依赖全局 fetch） */
/* ------------------------------------------------------------------ */

function httpRequest(opts: {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: Buffer | string;
}): Promise<{ status: number; bodyText: string }> {
  return new Promise((resolve, reject) => {
    const u = new URL(opts.url);
    const mod = u.protocol === 'https:' ? https : http;
    const headers: Record<string, string> = { ...opts.headers };
    const body = typeof opts.body === 'string' ? Buffer.from(opts.body, 'utf8') : opts.body;
    if (body && !headers['Content-Length']) {
      headers['Content-Length'] = String(body.byteLength);
    }
    const req = mod.request(
      u,
      { method: opts.method, headers },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        res.on('end', () => resolve({ status: res.statusCode ?? 0, bodyText: Buffer.concat(chunks).toString('utf8') }));
      }
    );
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

/** 调用 REST API，HTTP 状态 >= 400 时抛 ApiError（携带 status，供 401 重登录判断） */
async function apiRequest<T>(
  opts: { method: string; url: string; headers?: Record<string, string>; body?: Buffer | string }
): Promise<Envelope<T>> {
  const resp = await httpRequest(opts);
  let env: Envelope<T>;
  try {
    env = JSON.parse(resp.bodyText) as Envelope<T>;
  } catch {
    throw new ApiError(`无法解析后端响应 (HTTP ${resp.status})`, resp.status);
  }
  if (resp.status >= 400) {
    throw new ApiError(env.message || `请求失败 (HTTP ${resp.status})`, resp.status);
  }
  return env;
}

/* ------------------------------------------------------------------ */
/* 配置 / 工具                                                          */
/* ------------------------------------------------------------------ */

function getConfig(): { serverUrl: string; projectId: number; codeProjectId: number } {
  const cfg = vscode.workspace.getConfiguration(CONFIG_SECTION);
  return {
    serverUrl: cfg.get<string>('serverUrl', '').replace(/\/+$/, ''),
    projectId: cfg.get<number>('projectId', 0),
    codeProjectId: cfg.get<number>('codeProjectId', 0),
  };
}

async function promptInput(
  prompt: string,
  value: string,
  placeHolder: string,
  password = false
): Promise<string | undefined> {
  const v = await vscode.window.showInputBox({ prompt, value, placeHolder, password, ignoreFocusOut: true });
  if (v === undefined) return undefined; // 用户取消
  return v.trim();
}

async function requireConfig(context: vscode.ExtensionContext): Promise<{ serverUrl: string; projectId: number; codeProjectId: number; token: string } | undefined> {
  const { serverUrl, projectId, codeProjectId } = getConfig();
  if (!serverUrl || projectId <= 0 || codeProjectId <= 0) {
    vscode.window.showErrorMessage('请先运行 "WHartTest: 配置服务器 / 登录"');
    return undefined;
  }
  const token = await context.secrets.get(SECRET_TOKEN_KEY);
  if (!token) {
    vscode.window.showErrorMessage('未找到登录令牌，请先运行 "WHartTest: 配置服务器 / 登录"');
    return undefined;
  }
  return { serverUrl, projectId, codeProjectId, token };
}

/** 401 -> 提示重新登录并进入配置流程 */
async function handleApiError(e: unknown, context: vscode.ExtensionContext, action: string): Promise<void> {
  if (e instanceof ApiError && e.status === 401) {
    vscode.window.showWarningMessage('登录令牌已失效，请重新登录');
    await configure(context);
    return;
  }
  vscode.window.showErrorMessage(`${action}失败：${msg(e)}`);
}

/* ------------------------------------------------------------------ */
/* 命令：configure（配置服务器 / 登录）                                  */
/* ------------------------------------------------------------------ */

async function configure(context: vscode.ExtensionContext): Promise<void> {
  try {
    const cfg = vscode.workspace.getConfiguration(CONFIG_SECTION);

    const serverUrl = await promptInput(
      'WHartTest 服务器地址',
      cfg.get<string>('serverUrl', 'http://localhost:8913'),
      'http://localhost:8913'
    );
    if (serverUrl === undefined) return;

    const projectIdStr = await promptInput(
      'WHartTest 项目 ID (projectId)',
      String(cfg.get<number>('projectId', 0) || ''),
      '必填，正整数'
    );
    if (projectIdStr === undefined) return;
    const projectId = Number.parseInt(projectIdStr, 10);
    if (!Number.isInteger(projectId) || projectId <= 0) {
      vscode.window.showErrorMessage('projectId 必须为正整数');
      return;
    }

    const codeProjectIdStr = await promptInput(
      '源码分析项目 ID (codeProjectId，留空自动创建)',
      String(cfg.get<number>('codeProjectId', 0) || ''),
      '可留空，将自动创建'
    );
    if (codeProjectIdStr === undefined) return;

    const username = await promptInput('WHartTest 用户名', '', '');
    if (username === undefined) return;
    const password = await promptInput('WHartTest 密码（仅本次获取令牌，不保存）', '', '', true);
    if (password === undefined) return;

    const base = serverUrl.replace(/\/+$/, '');

    // 1) 登录获取 JWT
    const loginResp = await apiRequest<{ access: string }>({
      method: 'POST',
      url: `${base}/api/token/`,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const token = loginResp.data?.access;
    if (!token) throw new Error('登录响应缺少 access token');

    // 2) 保存配置与令牌
    await cfg.update('serverUrl', base, vscode.ConfigurationTarget.Global);
    await cfg.update('projectId', projectId, vscode.ConfigurationTarget.Global);
    await context.secrets.store(SECRET_TOKEN_KEY, token);

    // 3) codeProjectId 无效/留空 -> 自动创建
    let codeProjectId = codeProjectIdStr.trim() ? Number.parseInt(codeProjectIdStr, 10) : 0;
    if (!Number.isInteger(codeProjectId) || codeProjectId <= 0) {
      const name = vscode.workspace.workspaceFolders?.[0]?.name ?? 'untitled';
      codeProjectId = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'WHartTest: 创建源码分析项目…' },
        async () => {
          const resp = await apiRequest<{ id: number }>({
            method: 'POST',
            url: `${base}/api/projects/${projectId}/code/projects/`,
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ name, source_type: 'zip_upload' }),
          });
          if (!resp.data?.id) throw new Error('创建源码项目响应缺少 id');
          return resp.data.id;
        }
      );
      await cfg.update('codeProjectId', codeProjectId, vscode.ConfigurationTarget.Global);
    }

    vscode.window.showInformationMessage(
      `WHartTest 配置完成：项目 ${projectId}，源码项目 ${codeProjectId}。令牌已安全保存到 VS Code SecretStorage。`
    );
  } catch (e) {
    vscode.window.showErrorMessage(`配置失败：${msg(e)}`);
  }
}

/* ------------------------------------------------------------------ */
/* 命令：uploadWorkspace（上传当前工作区源码）                            */
/* ------------------------------------------------------------------ */

async function uploadWorkspace(context: vscode.ExtensionContext): Promise<void> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    vscode.window.showErrorMessage('请先打开一个工作区文件夹');
    return;
  }
  const required = await requireConfig(context);
  if (!required) return;
  const { serverUrl, projectId, codeProjectId, token } = required;

  try {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: 'WHartTest: 上传工作区源码', cancellable: false },
      async (progress) => {
        progress.report({ message: '扫描文件…' });
        const files = await vscode.workspace.findFiles('**/*', EXCLUDE_GLOB, MAX_FILE_COUNT + 1);
        if (files.length > MAX_FILE_COUNT) {
          throw new Error(`文件数 ${files.length} 超过上限 ${MAX_FILE_COUNT}，请精简工作区后重试`);
        }

        // 使用 adm-zip 逐个文件打包（保留相对路径）
        const zip = new AdmZip();
        let totalBytes = 0;
        for (let i = 0; i < files.length; i++) {
          const content = await vscode.workspace.fs.readFile(files[i]);
          totalBytes += content.byteLength;
          if (totalBytes > MAX_BYTES) {
            throw new Error('源码总大小超过 50MB 上限，请精简工作区后重试');
          }
          const rel = path.relative(folder.uri.fsPath, files[i].fsPath).split(path.sep).join('/');
          zip.addFile(rel, Buffer.from(content));
          if ((i + 1) % 500 === 0) {
            progress.report({ message: `已读取 ${i + 1}/${files.length} 个文件` });
          }
        }

        progress.report({ message: '压缩中…' });
        const zipBuffer = zip.toBuffer();
        if (zipBuffer.byteLength > MAX_BYTES) {
          throw new Error('压缩包超过 50MB 上限，请精简工作区后重试');
        }

        // multipart 上传（字段名 'file'）
        progress.report({ message: '上传中…' });
        const form = new FormData();
        form.append('file', zipBuffer, { filename: `${folder.name}.zip`, contentType: 'application/zip' });
        const resp = await apiRequest<Record<string, unknown>>({
          method: 'POST',
          url: `${serverUrl}/api/projects/${projectId}/code/projects/${codeProjectId}/upload/`,
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': `multipart/form-data; boundary=${form.getBoundary()}`,
          },
          body: form.getBuffer(),
        });

        // 快照信息字段后端未在契约中固定，做防御式读取
        const d = resp.data;
        const version = d?.version ?? d?.snapshot_version ?? d?.snapshot_id ?? '-';
        const count = d?.file_count ?? d?.fileCount ?? files.length;
        return { version, count };
      }
    );

    vscode.window.showInformationMessage(`上传成功：快照版本 ${result.version}，文件数 ${result.count}`);
  } catch (e) {
    await handleApiError(e, context, '上传');
  }
}

/* ------------------------------------------------------------------ */
/* 命令：viewImpacts（查看影响用例）                                     */
/* ------------------------------------------------------------------ */

interface ImpactRecord {
  code_file_path?: string;
  testcase_name?: string;
  diff_status?: string;
  diff_summary?: string;
  old_sha?: string;
  new_sha?: string;
  hunk_count?: number | string;
}

function impactDetail(im: ImpactRecord): string {
  const parts: string[] = [];
  if (im.old_sha && im.new_sha) parts.push(`${im.old_sha.slice(0, 8)} → ${im.new_sha.slice(0, 8)}`);
  if (im.hunk_count !== undefined && im.hunk_count !== null) parts.push(`hunks: ${im.hunk_count}`);
  if (im.diff_summary) parts.push(im.diff_summary);
  return parts.join(' · ');
}

async function viewImpacts(context: vscode.ExtensionContext): Promise<void> {
  const required = await requireConfig(context);
  if (!required) return;
  const { serverUrl, projectId, codeProjectId, token } = required;

  try {
    const resp = await apiRequest<ImpactRecord[]>({
      method: 'GET',
      url: `${serverUrl}/api/projects/${projectId}/code/projects/${codeProjectId}/impacts/?resolved=false`,
      headers: { Authorization: `Bearer ${token}` },
    });
    const impacts = Array.isArray(resp.data) ? resp.data.slice(0, 50) : [];
    if (impacts.length === 0) {
      vscode.window.showInformationMessage('暂无未解决的影响用例');
      return;
    }

    const items: vscode.QuickPickItem[] = impacts.map((im) => ({
      label: `[${im.diff_status ?? '?'}] ${im.code_file_path ?? ''} → 用例: ${im.testcase_name ?? ''}`,
      detail: impactDetail(im),
    }));
    const openPageItem: vscode.QuickPickItem = {
      label: '$(globe) 在浏览器打开影响页',
      description: `${serverUrl}/code-analysis`,
    };

    const picked = await vscode.window.showQuickPick(
      [...items, { label: '', kind: vscode.QuickPickItemKind.Separator }, openPageItem],
      { matchOnDetail: true, placeHolder: '选择影响用例查看详情（最多显示 50 条）' }
    );
    if (!picked) return;

    if (picked === openPageItem) {
      await vscode.env.openExternal(vscode.Uri.parse(`${serverUrl}/code-analysis`));
      return;
    }

    const idx = items.indexOf(picked);
    const im = impacts[idx];
    const q = new URLSearchParams({
      projectId: String(projectId),
      codeProjectId: String(codeProjectId),
      file: im?.code_file_path ?? '',
      testcase: im?.testcase_name ?? '',
    });
    await vscode.env.openExternal(vscode.Uri.parse(`${serverUrl}/code-analysis?${q.toString()}`));
  } catch (e) {
    await handleApiError(e, context, '获取影响用例');
  }
}

/* ------------------------------------------------------------------ */
/* 命令：openDashboard（打开 AI 源码分析页）                             */
/* ------------------------------------------------------------------ */

async function openDashboard(): Promise<void> {
  const { serverUrl } = getConfig();
  if (!serverUrl) {
    vscode.window.showErrorMessage('请先配置服务器地址（运行 "WHartTest: 配置服务器 / 登录"）');
    return;
  }
  await vscode.env.openExternal(vscode.Uri.parse(`${serverUrl}/code-analysis`));
}

/* ------------------------------------------------------------------ */

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand('wharttest.configure', () => configure(context)),
    vscode.commands.registerCommand('wharttest.uploadWorkspace', () => uploadWorkspace(context)),
    vscode.commands.registerCommand('wharttest.viewImpacts', () => viewImpacts(context)),
    vscode.commands.registerCommand('wharttest.openDashboard', openDashboard)
  );
}

export function deactivate(): void {}
