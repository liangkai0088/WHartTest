'use strict';
/**
 * WHartTest 组件解析器服务端
 *
 * 长驻 Node.js 子进程，通过 stdin/stdout 逐行 JSON-RPC 通信。
 *
 * 请求格式（每行一个）：
 *   {"id": "uuid", "method": "parse_file", "params": {"path": "src/views/Login.vue", "content": "..."}}
 *   {"id": "uuid", "method": "ping", "params": {}}
 *
 * 响应格式（每行一个）：
 *   {"id": "uuid", "ok": true,  "result": {"path": "...", "elements": [...]}}
 *   {"id": "uuid", "ok": false, "error": "错误信息"}
 *
 * 支持文件类型：
 *   - .vue   -> @vue/compiler-sfc 模板 AST 遍历
 *   - .jsx/.js（可含 JSX）/ .tsx -> @babel/parser（jsx/typescript 插件）AST 遍历
 *   - .ts    -> @babel/parser（typescript 插件）
 *   - 其他   -> 直接返回空元素列表
 */

const readline = require('readline');

const MAX_ELEMENTS = 500; // 单文件元素数量上限
const MAX_AST_NODES = 200000; // 单文件 AST 遍历节点上限
const MAX_DEPTH = 80;

let vueCompiler = null;
let babelParser = null;
let vueLoadError = null;
let babelLoadError = null;

function ensureVue() {
  if (vueCompiler) return true;
  try {
    vueCompiler = require('@vue/compiler-sfc');
    return true;
  } catch (e) {
    vueLoadError = String((e && e.message) || e);
    return false;
  }
}

function ensureBabel() {
  if (babelParser) return true;
  try {
    babelParser = require('@babel/parser');
    return true;
  } catch (e) {
    babelLoadError = String((e && e.message) || e);
    return false;
  }
}

function normalizePropName(name) {
  // 归一化跨框架的属性名
  if (name === 'htmlFor' || name === 'for') return 'label-for';
  return name;
}

// ---------------- Vue 模板 AST 遍历 ----------------

function vueText(node) {
  if (!node) return '';
  if (node.type === 2) return node.content || ''; // TEXT
  if (node.type === 5) {
    // INTERPOLATION
    const c = node.content;
    return c && c.content ? c.content : '';
  }
  let s = '';
  for (const c of node.children || []) s += vueText(c);
  for (const b of node.branches || []) s += vueText(b);
  return s;
}

let vueNodeCount = 0;

function walkVueTree(node, depth, out) {
  if (!node || depth > MAX_DEPTH) return;
  vueNodeCount += 1;
  if (vueNodeCount > MAX_AST_NODES) return;

  if (node.type === 1) {
    // ELEMENT
    const props = {};
    for (const p of node.props || []) {
      if (!p || !p.name) continue;
      const name = String(p.name);
      // 跳过指令（:xx / @xx / v-xx / #xx）
      if (name.startsWith(':') || name.startsWith('@') || name.startsWith('#') || name.startsWith('v-')) continue;
      if (p.value && p.value.content !== undefined && p.value.content !== null) {
        props[normalizePropName(name)] = String(p.value.content);
      } else {
        props[normalizePropName(name)] = true;
      }
    }
    const text = vueText(node).replace(/\s+/g, ' ').trim();
    if (out.length < MAX_ELEMENTS) {
      out.push({
        tag: node.tag,
        name: node.tag,
        props,
        text,
        line: node.loc && node.loc.start ? node.loc.start.line : 0,
        depth,
      });
      for (const c of node.children || []) walkVueTree(c, depth + 1, out);
      for (const b of node.branches || []) walkVueTree(b, depth + 1, out);
    }
  } else {
    for (const c of node.children || []) walkVueTree(c, depth, out);
    for (const b of node.branches || []) walkVueTree(b, depth, out);
  }
}

function parseVue(path, content) {
  if (!ensureVue()) return { error: 'vue compiler 不可用: ' + vueLoadError };
  let parsed;
  try {
    parsed = vueCompiler.parse(content, { filename: path });
  } catch (e) {
    return { error: 'Vue 解析失败: ' + ((e && e.message) || e) };
  }
  const ast = parsed && parsed.descriptor && parsed.descriptor.template && parsed.descriptor.template.ast;
  const elements = [];
  if (ast) {
    vueNodeCount = 0;
    walkVueTree(ast, 0, elements);
  }
  return { result: { path, elements } };
}

// ---------------- Babel / JSX AST 遍历 ----------------

function jsxText(node) {
  if (!node) return '';
  let s = '';
  for (const c of node.children || []) {
    if (!c) continue;
    if (c.type === 'JSXText') s += c.value || '';
    else if (c.type === 'JSXElement') s += jsxText(c);
    else if (c.type === 'JSXExpressionContainer') {
      const e = c.expression;
      if (e && e.type === 'StringLiteral') s += e.value;
    }
  }
  return s;
}

let babelNodeCount = 0;

function jsxTagName(name) {
  if (!name) return 'Component';
  if (name.type === 'JSXIdentifier') return name.name;
  if (name.type === 'JSXMemberExpression') {
    return jsxTagName(name.object) + '.' + jsxTagName(name.property);
  }
  if (name.type === 'JSXNamespacedName') return name.namespace.name + ':' + name.name.name;
  return 'Component';
}

function jsxAttrValue(attr) {
  if (!attr.value) return true;
  if (attr.value.type === 'StringLiteral') return attr.value.value;
  if (attr.value.type === 'JSXExpressionContainer') {
    const ex = attr.value.expression;
    if (!ex) return '';
    if (ex.type === 'StringLiteral') return ex.value;
    if (ex.type === 'TemplateLiteral' && ex.quasis && ex.quasis[0]) return ex.quasis[0].value.cooked || '';
    if (ex.name) return '{' + ex.name + '}';
    if (ex.type === 'MemberExpression' && ex.property) return '{' + ex.property.name + '}';
    return '{...}';
  }
  return String(attr.value.value !== undefined ? attr.value.value : '');
}

function walkBabelTree(node, depth, out) {
  if (!node || depth > MAX_DEPTH) return;
  babelNodeCount += 1;
  if (babelNodeCount > MAX_AST_NODES) return;

  if (node.type === 'JSXElement') {
    const open = node.openingElement;
    if (!open) return;
    const tag = jsxTagName(open.name);
    const props = {};
    for (const attr of open.attributes || []) {
      if (!attr || attr.type === 'JSXSpreadAttribute') continue;
      if (!attr.name || !attr.name.name) continue;
      const rawName = String(attr.name.name);
      props[normalizePropName(rawName)] = String(jsxAttrValue(attr));
    }
    const text = jsxText(node).replace(/\s+/g, ' ').trim();
    if (out.length < MAX_ELEMENTS) {
      out.push({
        tag,
        name: tag,
        props,
        text,
        line: node.loc && node.loc.start ? node.loc.start.line : 0,
        depth,
      });
      for (const c of node.children || []) walkBabelTree(c, depth + 1, out);
    }
    return;
  }

  for (const key of Object.keys(node)) {
    if (key === 'loc' || key === 'start' || key === 'end' || key === 'leadingComments' || key === 'trailingComments' || key === 'extra' || key === 'errors') continue;
    const v = node[key];
    if (Array.isArray(v)) {
      for (const c of v) {
        if (c && typeof c.type === 'string') walkBabelTree(c, depth, out);
      }
    } else if (v && typeof v.type === 'string') {
      walkBabelTree(v, depth, out);
    }
  }
}

function parseBabel(path, content) {
  if (!ensureBabel()) return { error: '@babel/parser 不可用: ' + babelLoadError };
  const plugins = [];
  if (path.endsWith('.tsx')) {
    plugins.push('typescript', 'jsx');
  } else if (path.endsWith('.ts')) {
    plugins.push('typescript');
  } else {
    plugins.push('jsx');
  }
  let ast;
  try {
    ast = babelParser.parse(content, {
      sourceType: 'unambiguous',
      plugins,
      errorRecovery: true,
      allowReturnOutsideFunction: true,
    });
  } catch (e) {
    return { error: 'JS 解析失败: ' + ((e && e.message) || e) };
  }
  const elements = [];
  babelNodeCount = 0;
  walkBabelTree(ast.program || ast, 0, elements);
  return { result: { path, elements } };
}

function parseFile(params) {
  const path = (params && params.path) || 'unknown';
  const content = (params && params.content) || '';
  if (path.endsWith('.vue')) return parseVue(path, content);
  if (/\.(jsx|tsx|js|ts|mjs|cjs)$/.test(path)) return parseBabel(path, content);
  // html 及其他类型：暂不支持，返回空元素列表
  return { result: { path, elements: [] } };
}

// ---------------- JSON-RPC 主循环 ----------------

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on('line', (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch (e) {
    return;
  }
  const id = msg.id;
  const method = msg.method;
  const params = msg.params || {};
  let resp;
  try {
    if (method === 'ping') {
      resp = { id, ok: true, result: 'pong' };
    } else if (method === 'parse_file') {
      const r = parseFile(params);
      if (r.error) resp = { id, ok: false, error: r.error };
      else resp = { id, ok: true, result: r.result };
    } else {
      resp = { id, ok: false, error: '未知方法: ' + method };
    }
  } catch (e) {
    resp = { id, ok: false, error: String((e && e.message) || e) };
  }
  process.stdout.write(JSON.stringify(resp) + '\n');
});
