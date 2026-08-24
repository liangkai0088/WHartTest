# WHartTest 源码分析（wharttest-code-analysis）

WHartTest 平台「源码级 AI 智能分析」（`code_analysis`）功能的 VS Code 客户端扩展。支持：

- 配置服务器地址与登录，获取 JWT 令牌
- 将当前工作区源码打包上传（zip）到后端，触发 AI 分析
- 查看未解决的影响用例（impact 列表）
- 在浏览器打开 AI 源码分析页

## 安装与构建

环境要求：VS Code >= 1.90，Node.js >= 18。

```bash
cd WHartTest_VSCode
npm install          # 若 npmjs 慢，可加 --registry=https://registry.npmmirror.com
npm run compile      # TypeScript 编译到 out/
```

调试运行：用 VS Code 打开本目录，按 `F5`（选择 "扩展开发宿主"）。
发布打包（可选）：安装 `vsce` 后执行 `vsce package`。

## 使用步骤

1. 打开要分析的工作区文件夹。
2. 命令面板（`Cmd/Ctrl+Shift+P`）执行 **WHartTest: 配置服务器 / 登录**：
   - 输入服务器地址（默认 `http://localhost:8913`）
   - 输入项目 ID `projectId`
   - 输入源码分析项目 ID `codeProjectId`（可留空，留空则自动创建）
   - 输入用户名与密码，获取令牌
3. 执行 **WHartTest: 上传当前工作区源码**，等待打包上传完成。
4. 执行 **WHartTest: 查看影响用例**，从列表中选择用例跳转到 Web 分析页；也可选择"在浏览器打开影响页"。
5. 执行 **WHartTest: 打开 AI 源码分析页** 直接打开分析页。

### 命令列表

| 命令 ID | 标题 | 说明 |
| --- | --- | --- |
| `wharttest.configure` | WHartTest: 配置服务器 / 登录 | 配置服务器、项目 ID、登录获取令牌；codeProjectId 留空时自动创建 |
| `wharttest.uploadWorkspace` | WHartTest: 上传当前工作区源码 | 打包第一个工作区文件夹并上传（自动排除 node_modules/.git/dist/build/.next/out/coverage/*.zip/.DS_Store；上限 20000 文件 / 50MB） |
| `wharttest.viewImpacts` | WHartTest: 查看影响用例 | 拉取未解决影响用例（最多 50 条），选择后打开 Web 影响页 |
| `wharttest.openDashboard` | WHartTest: 打开 AI 源码分析页 | 浏览器打开 `{serverUrl}/code-analysis` |

### 设置

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `wharttest.serverUrl` | string | `http://localhost:8913` | WHartTest 后端服务地址 |
| `wharttest.projectId` | number | `0` | WHartTest 项目 ID |
| `wharttest.codeProjectId` | number | `0` | 源码分析项目 ID；为 0 时配置流程会自动创建 |

## 令牌存储说明

登录成功后扩展只保存 JWT（access token），**不保存密码**。令牌通过 VS Code `SecretStorage`（`context.secrets`）加密存储，不会写入配置或磁盘明文文件。令牌失效（后端返回 401）时会提示重新登录。

## 多部分上传实现说明

multipart 上传采用 `form-data` npm 包构造（字段名 `file`），使用 Node 内置 `http/https` 发送，并显式设置 `Content-Length`，兼容性优于依赖全局 `fetch`/`FormData`/`Blob` 的方案（VS Code 扩展宿主对全局 `undici FormData` 的支持取决于运行时版本）。

## 与 MCP 方案的对比

本扩展通过 **REST + JWT** 与后端交互，适合在 VS Code 内手动触发分析、查看结果。

若希望 AI 助手（Claude Code / Cursor 等）直接调用源码分析能力，可使用仓库中的 **WHartTest_MCP** 方案：它提供 MCP streamable-http 服务，通过 `X-API-Key` 认证，配置 MCP server 的 `url` 与 `apiKey` 后即可由 Agent 按需调用分析工具。两者可并存：MCP 面向 Agent 自动调用，本扩展面向开发者手动操作。
