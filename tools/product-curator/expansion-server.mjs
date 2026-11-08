// Read-only loopback Mesh workbench. Decisions/evidence are explicit CLI imports.
import http from 'node:http';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { readFile, mkdir } from 'node:fs/promises';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { Expansion, args } from './expansion.mjs';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { ownedPath, hashFile } from './safety.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const mime = (f) => ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.gltf':'model/gltf+json','.bin':'application/octet-stream','.ktx2':'image/ktx2','.jpg':'image/jpeg','.wasm':'application/wasm','.woff2':'font/woff2'})[path.extname(f)] ?? 'application/octet-stream';
export async function createExpansionServer(options) {
  const engine = await Expansion.open(options);
  let server;
  try {
    const ui = await ownedPath(engine.root,'launches',randomUUID(),'ui'); await mkdir(path.dirname(ui),{recursive:true});
    const env = process.env.NODE_ENV;
    try { await build({configFile:false,envDir:false,root:HERE,publicDir:false,plugins:[react()],base:'/',logLevel:'warn',build:{outDir:ui,emptyOutDir:false,rollupOptions:{input:path.join(HERE,'expansion.html')}}}); }
    finally { if(env === undefined) delete process.env.NODE_ENV; else process.env.NODE_ENV = env; }
    let origin;
    server = http.createServer(async(req,res) => {
      const send = (status,bytes,type='application/json') => { res.writeHead(status,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Cross-Origin-Resource-Policy':'same-origin','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}); res.end(Buffer.isBuffer(bytes) || typeof bytes === 'string' ? bytes : JSON.stringify(bytes)); };
      try {
        assert.equal(req.headers.host,new URL(origin).host,'Exact loopback Host required');
        assert(!req.headers.origin || req.headers.origin === origin,'Cross-origin rejected');
        assert(!req.headers['sec-fetch-site'] || ['same-origin','none'].includes(req.headers['sec-fetch-site']),'Cross-site rejected');
        assert(req.method === 'GET','Read-only review server');
        assert(!req.url.includes('\\') && !/%2f|%5c|%2e/i.test(req.url),'Unsafe URL');
        const u = new URL(req.url,origin); assert.equal(u.origin,origin);
        if(u.pathname === '/api/expansion') {
          const candidates = [];
          for(const c of engine.state.candidates) {
            const p = engine.source(c.productId);
            const prepared = c.preparation ? await engine.verifyPreparation(c) : null;
            candidates.push({...c,proposal:p,dimensions:prepared?.manifest.normalization.bounds.size,previewUrl:prepared ? `/mesh/${c.productId}/${c.preparation.result.sha256}/lod0.gltf` : null});
          }
          send(200,{...engine.report(),candidates,references:engine.state.freeze.references,sourceAuthority:'Proposal titles/categories are metadata only. Review Style, role, orientation, dimensions and access explicitly.'}); return;
        }
        const m = u.pathname.match(/^\/mesh\/([a-z0-9-]+)\/([a-f0-9]{64})\/(.+)$/);
        if(m) {
          const c = engine.state.candidates.find((c) => c.productId === m[1]); assert(c?.preparation?.result.sha256 === m[2]);
          const f = c.preparation.files.find((f) => f.file === m[3]); assert(f,'File outside closed Mesh inventory');
          const file = await ownedPath(engine.root,'attempts',c.preparation.id,'output',f.file); assert.deepEqual(await hashFile(file),{bytes:f.bytes,sha256:f.sha256}); send(200,await readFile(file),mime(file)); return;
        }
        const reference = engine.state.freeze.references.images.find((r) => u.pathname === `/references/${r.sha256}/${r.fileName}`);
        if(reference) { const file = path.join(REPO_ROOT,'public/style-references',reference.fileName); assert.deepEqual(await hashFile(file),{bytes:reference.bytes,sha256:reference.sha256}); send(200,await readFile(file),'image/jpeg'); return; }
        const decoder = u.pathname.match(/^\/decoders\/basis\/(basis_transcoder\.(?:js|wasm))$/);
        if(decoder) { send(200,await readFile(path.join(REPO_ROOT,'node_modules/three/examples/jsm/libs/basis',decoder[1])),mime(decoder[1])); return; }
        if(u.pathname === '/') { send(200,await readFile(path.join(ui,'expansion.html')),'text/html'); return; }
        if(/^\/assets\/[a-zA-Z0-9_.-]+\.(?:js|css|woff2)$/.test(u.pathname)) { send(200,await readFile(path.join(ui,u.pathname.slice(1))),mime(u.pathname)); return; }
        send(404,{error:'Unknown local review route'});
      } catch(e) { send(e.code === 'ENOENT' ? 404 : 400,{error:e.message}); }
    });
    server.requestTimeout = 15_000; server.headersTimeout = 10_000;
    await new Promise((resolve,reject) => { server.once('error',reject); server.listen(options.port ?? 4313,'127.0.0.1',resolve); });
    origin = `http://127.0.0.1:${server.address().port}`;
    return {origin,engine,close:async()=> { server.closeAllConnections(); await new Promise((r) => server.close(r)); await engine.close(); }};
  } catch(e) { server?.close(); await engine.close(); throw e; }
}
if(process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {command,options} = args(process.argv.slice(2)); assert.equal(command,'serve'); assert(Number.isInteger(options.port) && options.port > 0 && options.port <= 65535,'Explicit --port required');
  const app = await createExpansionServer(options); console.log(`Expansion Mesh review: ${app.origin}\nRead-only. Stop server before observe/review/promote CLI commands; state writer is exclusive.`);
  for(const signal of ['SIGINT','SIGTERM']) process.once(signal,async()=>{await app.close(); process.exit(0);});
}
