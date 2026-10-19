import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { readFile, mkdir } from 'node:fs/promises';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { Engine, HttpError } from './engine.mjs';
import { assertLocalContext, ownedPath } from './safety.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const mime = (file) => ({ '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.gltf': 'model/gltf+json', '.bin': 'application/octet-stream', '.ktx2': 'image/ktx2', '.wasm': 'application/wasm', '.woff2': 'font/woff2' })[path.extname(file)] ?? 'application/octet-stream';
export async function buildUI(root) {
  const output = await ownedPath(root, 'launches', randomUUID(), 'ui');
  await mkdir(path.dirname(output), { recursive: true });
  const previousNodeEnv = process.env.NODE_ENV;
  try { await build({
    configFile: false, envDir: false, root: HERE, publicDir: false,
    plugins: [react()], base: '/', logLevel: 'warn',
    build: { outDir: output, emptyOutDir: false, sourcemap: false },
  }); } finally {
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
  }
  return output;
}
function equalToken(actual, expected) {
  if (typeof actual !== 'string') return false;
  const a = Buffer.from(actual), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
async function jsonBody(request) {
  let size = 0, pieces = [];
  for await (const piece of request) {
    size += piece.length;
    if (size > 16_384) throw new HttpError(413, 'JSON body exceeds 16 KiB');
    pieces.push(piece);
  }
  try { return JSON.parse(Buffer.concat(pieces).toString('utf8')); }
  catch { throw new HttpError(400, 'Malformed JSON'); }
}
export async function createCurator({ stateDir, actor = 'owner', port = 0, controlled = false, runner, uiDir, clock } = {}) {
  assertLocalContext();
  const engine = await Engine.open({ stateDir, actor, controlled, runner, clock });
  let staticRoot;
  try { staticRoot = uiDir ?? await buildUI(engine.root); }
  catch (error) { await engine.close(); throw error; }
  const token = randomBytes(32).toString('hex');
  let origin;
  const server = http.createServer(async (request, response) => {
    const send = (status, bytes, type = 'application/json') => {
      response.writeHead(status, {
        'Content-Type': type, 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
        // Three's shipped BasisU/Emscripten worker uses new Function. This local
        // CSP permits that decoder while all fetched code stays same-origin.
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; style-src 'self'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        'Referrer-Policy': 'no-referrer',
      });
      response.end(typeof bytes === 'object' && !Buffer.isBuffer(bytes) ? JSON.stringify(bytes) : bytes);
    };
    try {
      if (request.headers.host !== new URL(origin).host) throw new HttpError(403, 'Exact loopback Host required');
      if (request.headers.origin && request.headers.origin !== origin) throw new HttpError(403, 'Cross-origin request rejected');
      if (request.headers['sec-fetch-site'] && !['same-origin', 'none'].includes(request.headers['sec-fetch-site'])) throw new HttpError(403, 'Cross-site request rejected');
      const url = new URL(request.url, origin);
      if (url.origin !== origin || request.url.includes('\\') || /%2f|%5c|%2e/i.test(request.url)) throw new HttpError(400, 'Unsafe request path');
      if (engine.fatal || engine.store.poisoned) throw new HttpError(503, 'Durable state failure. Stop and inspect retained journal/attempt bytes before restart.');
      if (request.method === 'POST' && url.pathname === '/api/mutate') {
        if (request.headers.origin !== origin || request.headers['content-type'] !== 'application/json' || !equalToken(request.headers['x-curator-token'], token)) throw new HttpError(403, 'Mutation requires same Origin, application/json and per-launch token');
        send(200, await engine.mutate(await jsonBody(request)));
        return;
      }
      if (request.method !== 'GET') throw new HttpError(405, 'Only GET and explicit JSON mutations are supported');
      // A synchronous snapshot cannot interleave with a committed transition.
      // It stays responsive while an asynchronous commit validator is running.
      if (url.pathname === '/api/state') { send(200, { ...engine.view(), token }); return; }
      if (url.pathname === '/api/report') {
        const report = await engine.serialize(() => engine.report());
        // Before Start and while paused export only the frozen UNRUN protocol.
        if (!engine.canRead()) { delete report.candidates; delete report.attempts; delete report.history; }
        send(200, report); return;
      }
      if (url.pathname === '/api/catalogue') {
        const query = Object.fromEntries(url.searchParams);
        send(200, await engine.serialize(() => engine.entries(query))); return;
      }
      const original = url.pathname.match(/^\/mesh\/original\/([a-f0-9]{64})\/([a-z0-9-]+)\/(.+)$/);
      const attempt = url.pathname.match(/^\/mesh\/attempt\/([a-f0-9-]{36})\/(.+)$/);
      if (original || attempt) {
        const file = original ? original[3] : attempt[2];
        const bytes = await engine.serialize(() => original ? engine.mesh('original', original[1], original[2], file) : engine.mesh('attempt', attempt[1], null, file));
        send(200, bytes, mime(file)); return;
      }
      if (url.pathname.startsWith('/decoders/basis/')) {
        const file = url.pathname.slice('/decoders/basis/'.length);
        if (!['basis_transcoder.js', 'basis_transcoder.wasm'].includes(file)) throw new HttpError(404, 'Unknown decoder');
        const bytes = await engine.serialize(async () => { engine.requireRead(); return readFile(path.join(REPO_ROOT, 'node_modules/three/examples/jsm/libs/basis', file)); });
        send(200, bytes, mime(file)); return;
      }
      // No Vite dev server, /@fs, source, seed, publicDir, stable products route
      // or general filesystem mount exists at this boundary.
      if (url.pathname === '/') { send(200, await readFile(path.join(staticRoot, 'index.html')), mime('index.html')); return; }
      if (/^\/assets\/[a-zA-Z0-9_.-]+\.(?:js|css|woff2)$/.test(url.pathname)) {
        send(200, await readFile(path.join(staticRoot, url.pathname.slice(1))), mime(url.pathname)); return;
      }
      throw new HttpError(404, 'Local route not found');
    } catch (error) {
      const status = error.status ?? (error.code === 'ENOENT' ? 404 : error.name === 'AssertionError' ? 400 : 500);
      send(status, { error: error.message });
    }
  });
  server.requestTimeout = 15_000;
  server.headersTimeout = 10_000;
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', resolve); });
  } catch (error) { await engine.close(); throw error; }
  origin = `http://127.0.0.1:${server.address().port}`;
  return { engine, server, origin, close: async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    await engine.close();
  } };
}
export function parseArgs(args) {
  const options = { actor: 'owner', port: 4311, stateDir: path.join(process.env.LOCALAPPDATA ?? '', 'FurnitureOS', 'product-curator') };
  if (!process.env.LOCALAPPDATA && !args.includes('--state-dir')) throw new Error('Specify an external --state-dir on this platform');
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i], value = args[i + 1];
    if (!value) throw new Error(`Missing value for ${key}`);
    if (key === '--state-dir') options.stateDir = path.resolve(value);
    else if (key === '--actor' && ['owner', 'automated'].includes(value)) options.actor = value;
    else if (key === '--port' && /^\d+$/.test(value) && Number(value) <= 65535) options.port = Number(value);
    else throw new Error(`Unknown/invalid option ${key}; queue size and host cannot be overridden`);
  }
  return options;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const app = await createCurator(parseArgs(process.argv.slice(2)));
  console.log(`FurnitureOS local Product curator: ${app.origin}\nActor: ${app.engine.state.actor}; state: ${app.engine.root}\nOwner sample timing begins only with explicit Start. Shutdown during ACTIVE invalidates it; Pause first after work settles.`);
  let stopping = false;
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, async () => {
    if (stopping) return; stopping = true;
    await app.close(); process.exit(0);
  });
}
