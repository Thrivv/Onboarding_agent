#!/usr/bin/env node
/**
 * Undefined-identifier check for the React app — a standalone `no-undef`.
 *
 * Why this exists
 * ---------------
 * Stage B6 rewrote 63 inline API calls into named wrappers. Several call sites
 * looked like this:
 *
 *     const encodedEmail = encodeURIComponent(user.email);
 *     ... api.get(`/documentupload/document-status/${encodedEmail}`)
 *
 * The rewrite substituted a bare `email` — a variable that never existed in
 * those scopes — and then deleted the `encodedEmail` line as "now unused".
 * Eight call sites referenced an undefined name. Every static check in
 * backend/tests/contract_check.py was green: the module graph resolved, the
 * named exports resolved, the endpoint paths resolved. None of them knew what
 * a JavaScript scope is.
 *
 * CRA runs ESLint during `npm run build` and catches this — but only inside a
 * Docker build that takes ~75 seconds to reach the failure. This runs in about
 * a second, outside the container.
 *
 * Requires @babel/parser, which react-scripts already depends on:
 *     node frontend/scripts/check-undefined.cjs
 *
 * Exit code 0 = clean, 1 = undefined identifiers found.
 */

const fs = require('fs');
const path = require('path');

/**
 * Locate @babel/parser.
 *
 * A plain `require('@babel/parser')` is not enough: npm does not always hoist
 * it to the top of node_modules, and when it lives under
 * `node_modules/@babel/core/node_modules/@babel/parser` Node's resolution from
 * this script never reaches it. So: try normal resolution first, then look in
 * the places it actually turns up, then do a shallow scan of nested copies.
 */
function findParser() {
  const FE = path.resolve(__dirname, '..');
  const candidates = [
    '@babel/parser',
    path.join(FE, 'node_modules', '@babel', 'parser'),
    path.join(FE, 'node_modules', '@babel', 'core', 'node_modules', '@babel', 'parser'),
    path.join(FE, 'node_modules', 'babel-preset-react-app', 'node_modules', '@babel', 'parser'),
    path.join(FE, 'node_modules', 'react-scripts', 'node_modules', '@babel', 'parser'),
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* keep looking */ }
  }
  // Last resort: scan one level of nested node_modules for a copy.
  const root = path.join(FE, 'node_modules');
  try {
    for (const pkg of fs.readdirSync(root)) {
      const nested = path.join(root, pkg, 'node_modules', '@babel', 'parser');
      if (fs.existsSync(nested)) {
        try { return require(nested); } catch (e) { /* keep looking */ }
      }
    }
  } catch (e) { /* no node_modules at all */ }
  return null;
}

const parser = findParser();
if (!parser) {
  console.error('Could not locate @babel/parser.\n');
  console.error('It is a transitive dependency of react-scripts, but npm does not always');
  console.error('hoist it somewhere this script can reach. Install a local copy — it is');
  console.error('small, and --no-save keeps it out of package.json:\n');
  console.error('    cd frontend && npm install --no-save @babel/parser\n');
  console.error('Then re-run:  node scripts/check-undefined.cjs');
  process.exit(2);
}

const SRC = path.resolve(__dirname, '..', 'src');

// Globals the browser/React/CRA environment provides. Anything not bound in an
// enclosing scope and not listed here is reported.
const GLOBALS = new Set([
  'window', 'document', 'console', 'navigator', 'location', 'history', 'screen',
  'localStorage', 'sessionStorage', 'fetch', 'Headers', 'Request', 'Response',
  'FormData', 'Blob', 'File', 'FileReader', 'URL', 'URLSearchParams', 'AbortController',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'requestAnimationFrame',
  'cancelAnimationFrame', 'queueMicrotask', 'structuredClone', 'alert', 'confirm', 'prompt',
  'Math', 'JSON', 'Object', 'Array', 'String', 'Number', 'Boolean', 'Date', 'RegExp',
  'Error', 'TypeError', 'RangeError', 'SyntaxError', 'Promise', 'Symbol', 'Map', 'Set',
  'WeakMap', 'WeakSet', 'Proxy', 'Reflect', 'BigInt', 'Intl', 'ArrayBuffer', 'DataView',
  'Uint8Array', 'Int8Array', 'Float32Array', 'Float64Array', 'isNaN', 'isFinite',
  'parseInt', 'parseFloat', 'encodeURIComponent', 'decodeURIComponent', 'encodeURI',
  'decodeURI', 'globalThis', 'undefined', 'NaN', 'Infinity',
  'process', 'module', 'require', 'exports', '__dirname', '__filename',
  'Image', 'Audio', 'Event', 'CustomEvent', 'MutationObserver', 'IntersectionObserver',
  'ResizeObserver', 'WebSocket', 'Worker', 'crypto', 'performance', 'atob', 'btoa',
  'HTMLElement', 'Node', 'Element', 'DOMParser', 'XMLHttpRequest', 'AbortSignal',
  'arguments', 'this', 'super',
]);

function walkFiles(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walkFiles(p, out);
    else if (/\.(js|jsx)$/.test(e.name)) out.push(p);
  }
  return out;
}

const PLUGINS = ['jsx', 'optionalChaining', 'nullishCoalescingOperator',
  'classProperties', 'objectRestSpread', 'dynamicImport'];

/** Collect every name a pattern binds (destructuring, defaults, rest). */
function bindPattern(node, add) {
  if (!node) return;
  switch (node.type) {
    case 'Identifier': add(node.name); break;
    case 'ObjectPattern':
      for (const p of node.properties) {
        if (p.type === 'RestElement') bindPattern(p.argument, add);
        else bindPattern(p.value, add);
      }
      break;
    case 'ArrayPattern':
      for (const el of node.elements) if (el) bindPattern(el, add);
      break;
    case 'AssignmentPattern': bindPattern(node.left, add); break;
    case 'RestElement': bindPattern(node.argument, add); break;
    default: break;
  }
}

const problems = [];

function checkFile(file) {
  const code = fs.readFileSync(file, 'utf8');
  let ast;
  try {
    ast = parser.parse(code, { sourceType: 'module', plugins: PLUGINS });
  } catch (e) {
    problems.push({ file, line: e.loc ? e.loc.line : 0, name: `PARSE ERROR: ${e.message}` });
    return;
  }

  // Scope chain: each frame is a Set of names bound in it.
  const scopes = [new Set()];
  const declare = (n) => scopes[scopes.length - 1].add(n);
  const isBound = (n) => scopes.some((s) => s.has(n)) || GLOBALS.has(n);

  // Hoist: collect ALL bindings of a scope body before walking it, so a
  // function referenced before its declaration is not a false positive.
  function hoist(body) {
    for (const n of body || []) collectDecls(n, declare);
  }

  function collectDecls(node, add) {
    if (!node || typeof node.type !== 'string') return;
    switch (node.type) {
      case 'VariableDeclaration':
        for (const d of node.declarations) bindPattern(d.id, add);
        break;
      case 'FunctionDeclaration':
      case 'ClassDeclaration':
        if (node.id) add(node.id.name);
        break;
      case 'ImportDeclaration':
        for (const s of node.specifiers) add(s.local.name);
        break;
      case 'ExportNamedDeclaration':
      case 'ExportDefaultDeclaration':
        if (node.declaration) collectDecls(node.declaration, add);
        break;
      case 'IfStatement':
        collectDecls(node.consequent, add); collectDecls(node.alternate, add); break;
      case 'BlockStatement':
        for (const s of node.body) collectDecls(s, add); break;
      case 'TryStatement':
        collectDecls(node.block, add);
        if (node.handler) collectDecls(node.handler.body, add);
        collectDecls(node.finalizer, add);
        break;
      case 'ForStatement': case 'ForInStatement': case 'ForOfStatement':
      case 'WhileStatement': case 'DoWhileStatement': case 'LabeledStatement':
        collectDecls(node.body, add); break;
      case 'SwitchStatement':
        for (const c of node.cases) for (const s of c.consequent) collectDecls(s, add);
        break;
      default: break;
    }
  }

  function walk(node, parent) {
    if (!node || typeof node.type !== 'string') return;

    switch (node.type) {
      case 'Identifier': {
        // Only flag identifiers in a *read* position.
        if (!parent) return;
        const p = parent;
        if (p.type === 'MemberExpression' && p.property === node && !p.computed) return;
        if (p.type === 'OptionalMemberExpression' && p.property === node && !p.computed) return;
        if (p.type === 'ObjectProperty' && p.key === node && !p.computed) return;
        if (p.type === 'ObjectMethod' && p.key === node && !p.computed) return;
        if (p.type === 'ClassMethod' && p.key === node && !p.computed) return;
        if (p.type === 'JSXAttribute' && p.name === node) return;
        if (p.type === 'ImportSpecifier' && p.imported === node) return;
        if (p.type === 'ExportSpecifier') return;
        if (p.type === 'LabeledStatement' || p.type === 'BreakStatement' ||
            p.type === 'ContinueStatement') return;
        if (!isBound(node.name)) {
          problems.push({ file, line: node.loc.start.line, name: node.name });
        }
        return;
      }
      case 'JSXIdentifier': {
        // <div> is intrinsic; <Foo> must resolve.
        if (parent && parent.type === 'JSXAttribute') return;
        if (parent && parent.type === 'JSXMemberExpression' && parent.property === node) return;
        if (/^[a-z]/.test(node.name)) return;
        if (!isBound(node.name)) {
          problems.push({ file, line: node.loc.start.line, name: `<${node.name}>` });
        }
        return;
      }
      case 'FunctionDeclaration':
      case 'FunctionExpression':
      case 'ArrowFunctionExpression':
      case 'ObjectMethod':
      case 'ClassMethod': {
        if (node.type === 'FunctionDeclaration' && node.id) declare(node.id.name);
        if (node.key && node.computed) walk(node.key, node);
        scopes.push(new Set());
        if (node.id && node.type !== 'FunctionDeclaration') declare(node.id.name);
        for (const p of node.params || []) bindPattern(p, declare);
        for (const p of node.params || []) {
          if (p.type === 'AssignmentPattern') walk(p.right, p);
        }
        if (node.body && node.body.type === 'BlockStatement') hoist(node.body.body);
        walk(node.body, node);
        scopes.pop();
        return;
      }
      case 'BlockStatement': {
        scopes.push(new Set());
        hoist(node.body);
        for (const s of node.body) walk(s, node);
        scopes.pop();
        return;
      }
      case 'CatchClause': {
        scopes.push(new Set());
        if (node.param) bindPattern(node.param, declare);
        hoist(node.body.body);
        for (const s of node.body.body) walk(s, node);
        scopes.pop();
        return;
      }
      case 'ForStatement': case 'ForInStatement': case 'ForOfStatement': {
        scopes.push(new Set());
        for (const key of ['init', 'left']) {
          const n = node[key];
          if (n && n.type === 'VariableDeclaration') {
            for (const d of n.declarations) bindPattern(d.id, declare);
          }
        }
        for (const key of ['init', 'test', 'update', 'left', 'right', 'body']) {
          if (node[key]) walk(node[key], node);
        }
        scopes.pop();
        return;
      }
      case 'VariableDeclarator': {
        bindPattern(node.id, declare);
        if (node.init) walk(node.init, node);
        // walk computed keys / defaults inside the pattern
        return;
      }
      case 'ClassDeclaration': case 'ClassExpression': {
        if (node.id) declare(node.id.name);
        if (node.superClass) walk(node.superClass, node);
        scopes.push(new Set());
        walk(node.body, node);
        scopes.pop();
        return;
      }
      case 'ClassProperty': case 'PropertyDefinition': {
        // `handleReload = () => {...}` is a class FIELD, reached only via
        // `this.handleReload`. The left side binds nothing in lexical scope, so
        // walking it as an identifier read reports a phantom undefined name —
        // which is exactly what the first version of this script did on
        // ErrorBoundary.jsx.
        if (node.computed && node.key) walk(node.key, node);
        if (node.value) walk(node.value, node);
        return;
      }
      case 'ImportDeclaration': {
        for (const s of node.specifiers) declare(s.local.name);
        return;
      }
      case 'MemberExpression': case 'OptionalMemberExpression': {
        walk(node.object, node);
        if (node.computed) walk(node.property, node);
        return;
      }
      default: break;
    }

    for (const key of Object.keys(node)) {
      if (key === 'loc' || key === 'start' || key === 'end' || key === 'leadingComments' ||
          key === 'trailingComments' || key === 'innerComments') continue;
      const child = node[key];
      if (Array.isArray(child)) for (const c of child) walk(c, node);
      else if (child && typeof child.type === 'string') walk(child, node);
    }
  }

  hoist(ast.program.body);
  for (const n of ast.program.body) walk(n, ast.program);
}

/**
 * Second pass: an imported name shadowed by a local declaration.
 *
 * Not an undefined-variable bug — the name IS defined, which is precisely why
 * nothing catches it. B6 rewrote `api.post('/auth/login', …)` into
 * `login(…)` inside AuthContext.jsx, a file that already defined its own
 * `const login = useCallback(...)`. The local const shadowed the import, so
 * `login()` called ITSELF: infinite recursion, no network request, and a
 * generic "Login failed" in the UI. Signup worked, login did not.
 *
 * ESLint's no-undef cannot see this. Neither can a module graph or an export
 * check. It needs exactly this comparison.
 */
function checkShadowedImports(file) {
  const code = fs.readFileSync(file, 'utf8');
  let ast;
  try {
    ast = parser.parse(code, { sourceType: 'module', plugins: PLUGINS });
  } catch (e) {
    return;
  }
  const imported = new Map();
  for (const n of ast.program.body) {
    if (n.type === 'ImportDeclaration') {
      for (const s of n.specifiers) imported.set(s.local.name, n.source.value);
    }
  }
  if (!imported.size) return;

  (function scan(node) {
    if (!node || typeof node.type !== 'string') return;
    const id =
      node.type === 'VariableDeclarator' && node.id.type === 'Identifier' ? node.id :
      (node.type === 'FunctionDeclaration' || node.type === 'ClassDeclaration') && node.id ? node.id :
      null;
    if (id && imported.has(id.name)) {
      shadowed.push({
        file,
        line: id.loc.start.line,
        name: id.name,
        from: imported.get(id.name),
      });
    }
    for (const k of Object.keys(node)) {
      if (k === 'loc' || k === 'start' || k === 'end') continue;
      const c = node[k];
      if (Array.isArray(c)) c.forEach(scan);
      else if (c && typeof c.type === 'string') scan(c);
    }
  })(ast.program);
}

const shadowed = [];
const files = walkFiles(SRC).sort();
for (const f of files) {
  checkFile(f);
  checkShadowedImports(f);
}

const ROOT = path.resolve(__dirname, '..', '..');
let failed = false;

if (problems.length) {
  failed = true;
  console.log(`UNDEFINED IDENTIFIERS — ${problems.length} problem(s):\n`);
  let last = null;
  for (const p of problems) {
    const rel = path.relative(ROOT, p.file);
    if (rel !== last) { console.log(`  ${rel}`); last = rel; }
    console.log(`      line ${p.line}: '${p.name}' is not defined`);
  }
  console.log(`\nThese will fail 'npm run build' (CRA runs ESLint no-undef).\n`);
}

if (shadowed.length) {
  failed = true;
  console.log(`SHADOWED IMPORTS — ${shadowed.length} problem(s):\n`);
  let last = null;
  for (const s of shadowed) {
    const rel = path.relative(ROOT, s.file);
    if (rel !== last) { console.log(`  ${rel}`); last = rel; }
    console.log(`      line ${s.line}: local '${s.name}' shadows the import from '${s.from}'`);
  }
  console.log(
    `\nThe imported function is unreachable in this file. This does NOT fail the\n` +
    `build — it fails silently at runtime. Alias the import, e.g.\n` +
    `    import { login as loginRequest } from '../api/auth';\n`
  );
}

if (failed) process.exit(1);
console.log(`OK — ${files.length} modules, no undefined identifiers, no shadowed imports`);
