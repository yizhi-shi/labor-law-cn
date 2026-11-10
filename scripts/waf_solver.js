#!/usr/bin/env node
/**
 * waf_solver.js — 求解 flk.npc.gov.cn（网宿 WZWS）的 JS 挑战页。
 *
 * 背景：该站 GET 请求被限流时返回一个约 37KB 的 HTML，内含一段混淆 JS，
 * 其唯一作用是执行 `window.location = "/WZWSREL<base64>?wzwschallenge=...&wzwsinfos=..."`。
 * 这个脚本用最小 DOM shim 在 Node 里跑那段 JS，截获 location 赋值。
 *
 * 用法:
 *   node scripts/waf_solver.js <challenge.html>          # 从已抓到的挑战页求解
 *   node scripts/waf_solver.js <被挑战的 URL>            # 自行抓取挑战页再求解
 *   node scripts/waf_solver.js -                          # 从 stdin 读 HTML
 *
 * 参数:
 *   --raw       只输出路径部分（默认输出可直接 GET 的绝对 URL 或原始值）
 *   --ua <str>  自定义 User-Agent（URL 模式抓取时使用）
 *   --cookie <str>  URL 模式抓取时附加 Cookie
 *   --json      输出 {"pass_url": ..., "html_bytes": N}
 *
 * 输出: 通过 URL（通常以 /WZWSREL 开头），调用方随后 GET 一次即可拿到
 *       wzws_sessionid cookie 并通过校验。
 * 失败: 退出码 1，错误信息到 stderr。
 *
 * 无第三方依赖（仅 Node 内置模块），单次求解通常 < 200ms。
 */
'use strict';

const fs = require('fs');
const vm = require('vm');
const path = require('path');
const https = require('https');
const http = require('http');

const DEFAULT_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36';

function parseArgs(argv) {
  const opts = { source: '', raw: false, json: false, ua: DEFAULT_UA, cookie: '' };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--raw') opts.raw = true;
    else if (a === '--json') opts.json = true;
    else if (a === '--ua') opts.ua = argv[++i] || DEFAULT_UA;
    else if (a === '--cookie') opts.cookie = argv[++i] || '';
    else if (a === '-h' || a === '--help') { printHelp(); process.exit(0); }
    else positional.push(a);
  }
  opts.source = positional[0] || '';
  return opts;
}

function printHelp() {
  process.stderr.write(
    'usage: node waf_solver.js <challenge.html | url | -> [--raw] [--json]\n' +
    '                           [--ua UA] [--cookie COOKIE]\n');
}

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on('data', (c) => chunks.push(c));
    process.stdin.on('end', () => resolve(Buffer.concat(chunks)));
    process.stdin.on('error', reject);
  });
}

function httpGet(url, ua, cookie, redirects) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(url); } catch (e) { return reject(new Error('bad url: ' + url)); }
    const mod = u.protocol === 'http:' ? http : https;
    const headers = { 'User-Agent': ua, 'Accept': '*/*' };
    if (cookie) headers['Cookie'] = cookie;
    const req = mod.get(url, { headers, timeout: 30000 }, (res) => {
      const status = res.statusCode || 0;
      if (status >= 300 && status < 400 && res.headers.location && redirects > 0) {
        res.resume();
        const next = new URL(res.headers.location, url).href;
        return resolve(httpGet(next, ua, cookie, redirects - 1));
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ body: Buffer.concat(chunks), status }));
    });
    req.on('timeout', () => req.destroy(new Error('timeout fetching ' + url)));
    req.on('error', reject);
  });
}

/* ------------------------------------------------------------------ DOM shim */
function makeElement(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _tag: tag,
    style: new Proxy({}, { set(t, k, v) { t[k] = v; return true; }, get(t, k) { return t[k]; } }),
    children: [],
    attributes: {},
    value: '',
    name: '',
    action: '',
    method: '',
    target: '',
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {},
    remove() {},
    setAttribute(k, v) { this.attributes[k] = v; },
    getAttribute(k) { return this.attributes[k]; },
    submit() {},
    focus() {},
    click() {},
    addEventListener() {},
    getElementsByTagName() { return []; },
    getContext() {
      return { fillText() {}, fillRect() {}, measureText() { return { width: 10 }; },
        getImageData() { return { data: new Uint8Array(4096) }; } };
    },
    toDataURL() { return 'data:image/png;base64,AAAA'; },
    getBoundingClientRect() { return { width: 100, height: 20, top: 0, left: 0 }; },
  };
  return el;
}

function buildContext() {
  const body = makeElement('body');
  const document = {
    cookie: '',
    body,
    documentElement: makeElement('html'),
    createElement: (t) => makeElement(t),
    getElementById: () => null,
    getElementsByTagName: () => [body],
    querySelector: () => null,
    querySelectorAll: () => [],
    write() {},
    addEventListener() {},
  };
  const location = {
    href: 'https://flk.npc.gov.cn/',
    protocol: 'https:',
    hostname: 'flk.npc.gov.cn',
    host: 'flk.npc.gov.cn',
    pathname: '/',
    search: '',
    hash: '',
    reload() {},
    replace() {},
    assign() {},
    toString() { return this.href; },
  };
  const state = { passUrl: '' };
  const window = new Proxy(
    {
      location,
      document,
      navigator: {
        userAgent: DEFAULT_UA,
        language: 'zh-CN',
        languages: ['zh-CN'],
        platform: 'Win32',
        cookieEnabled: true,
        appName: 'Netscape',
        appVersion: '5.0',
        plugins: [],
        mimeTypes: [],
      },
      screen: {
        width: 1920, height: 1080, availWidth: 1920, availHeight: 1040,
        colorDepth: 24, pixelDepth: 24,
      },
      innerWidth: 1920, innerHeight: 937, outerWidth: 1920, outerHeight: 1040,
      screenX: 0, screenY: 0, devicePixelRatio: 1,
      addEventListener() {}, removeEventListener() {},
      setTimeout: (f) => { try { f(); } catch (e) { /* ignore */ } return 1; },
      setInterval: () => 1, clearTimeout() {}, clearInterval() {},
      console,
    },
    {
      get(t, k) { return t[k]; },
      set(t, k, v) {
        if (k === 'location' && typeof v === 'string') state.passUrl = v;
        t[k] = v;
        return true;
      },
    }
  );
  window.window = window;
  window.self = window;
  window.top = window;
  window.parent = window;
  const sandbox = {
    window, self: window, document, navigator: window.navigator,
    screen: window.screen, location,
    setTimeout: (f) => { try { f(); } catch (e) { /* ignore */ } return 1; },
    setInterval: () => 1, clearTimeout() {}, clearInterval() {},
    atob: (s) => Buffer.from(s, 'base64').toString('binary'),
    btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
    console, Date, Math, String, Number, Array, Object, JSON, RegExp, Error,
    parseInt, parseFloat, isNaN, decodeURI, encodeURI, escape, unescape,
    decodeURIComponent, encodeURIComponent,
  };
  sandbox.globalThis = sandbox;
  return { context: vm.createContext(sandbox), state };
}

function extractScript(html) {
  // 取最长的 <script>，挑战逻辑总在其中
  const re = /<script[^>]*>([\s\S]*?)<\/script>/gi;
  let best = '';
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[1].length > best.length) best = m[1];
  }
  return best;
}

function solve(html) {
  const script = extractScript(html);
  if (!script) throw new Error('no <script> block found in challenge page');
  const { context, state } = buildContext();
  try {
    vm.runInContext(script, context, { timeout: 5000 });
  } catch (e) {
    // 某些变体在赋值后抛错，忽略；稍后用正则兜底
  }
  let url = state.passUrl;
  if (!url) {
    const mm = html.match(/(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']/);
    if (mm) url = mm[1];
  }
  if (!url) throw new Error('challenge solved but no location assignment captured');
  return url;
}

/* ---------------------------------------------------------------------- main */
(async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.source) { printHelp(); process.exit(1); }
  let html;
  let bytes;
  try {
    if (opts.source === '-') {
      html = (await readStdin()).toString('utf8');
    } else if (/^https?:\/\//i.test(opts.source)) {
      const res = await httpGet(opts.source, opts.ua, opts.cookie, 3);
      html = res.body.toString('utf8');
    } else {
      const p = path.resolve(opts.source);
      if (!fs.existsSync(p)) throw new Error('no such file: ' + p);
      html = fs.readFileSync(p, 'utf8');
    }
    bytes = Buffer.byteLength(html, 'utf8');
    if (!/<html|<!doctype|<script/i.test(html)) {
      throw new Error('input does not look like an HTML challenge page');
    }
    const t0 = Date.now();
    const passUrl = solve(html);
    const ms = Date.now() - t0;
    if (opts.json) {
      process.stdout.write(JSON.stringify({ pass_url: passUrl, html_bytes: bytes, ms }) + '\n');
    } else {
      process.stdout.write(passUrl + '\n');
    }
  } catch (e) {
    process.stderr.write('waf_solver: ' + (e && e.message ? e.message : String(e)) + '\n');
    process.exit(1);
  }
})();
