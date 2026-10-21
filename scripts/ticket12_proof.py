"""Run local proof with native exit codes and fresh external evidence only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/Scripts/python.exe'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--evidence-dir',required=True,type=Path)
    parser.add_argument('--prepared-dir',required=True,type=Path)
    parser.add_argument('--browsers-only',action='store_true')
    args=parser.parse_args()
    evidence=args.evidence_dir.resolve()
    assert ROOT not in evidence.parents and evidence != ROOT
    assert not any((p/'.git').exists() for p in (evidence,*evidence.parents))
    evidence.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'TICKET12_PREPARED_DIR':str(args.prepared_dir.resolve()),'CURATOR_EVIDENCE_DIR':str(evidence/'curator-evidence')}
    def run(name,command,extra=None):
        started=time.time()
        with (evidence/f'{name}.log').open('wb') as log:
            result=subprocess.run([str(x) for x in command],cwd=ROOT,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT)
        record=dict(name=name,command=[str(x) for x in command],cwd=str(ROOT),exit=result.returncode,elapsedSeconds=time.time()-started,logSha256=hashlib.sha256((evidence/f'{name}.log').read_bytes()).hexdigest())
        with (evidence/'commands.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
        print(f'{name}: exit {result.returncode}',flush=True)
        return result.returncode
    if not args.browsers_only:
        checks=[('backend',[PYTHON,'-m','pytest','backend_tests']),('api-types',['npm.cmd','run','api:types']),('typecheck',['npm.cmd','run','typecheck']),('decoders',['node','scripts/copy-decoders.mjs']),('frontend',['npm.cmd','test','--','--run']),('asset-budget',['npm.cmd','run','assets:report']),('build',['npm.cmd','run','build']),('curator-types',['npm.cmd','run','curator:typecheck']),('curator-tests',['npm.cmd','run','curator:test']),('production-exclusion',['node','tools/product-curator/verify-production-exclusion.mjs']),('curator-browser',['npx.cmd','playwright','test','--config','tools/product-curator/playwright.config.ts'])]
        failures=[]
        for name,command in checks:
            if run(name,command): failures.append(name)
        if failures:
            print('Failed checks: '+', '.join(failures),flush=True)
            return 1
    runtime=evidence/'controlled-runtime'
    if run('controlled-runtime',['node','tools/product-curator/controlled-runtime.mjs','--prepared-dir',args.prepared_dir,'--state-dir',runtime]):return 1
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    command=[str(PYTHON),'scripts/ticket12_controlled_server.py','--runtime-root',str(runtime),'--port',str(port)]
    with (evidence/'controlled-server.log').open('wb') as log:
        server=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            origin=f'http://127.0.0.1:{port}'
            for _ in range(120):
                if server.poll() is not None:raise RuntimeError('Controlled server exited; see retained log')
                try:
                    with urllib.request.urlopen(origin+'/api/health',timeout=1) as r:
                        if r.status==200:break
                except OSError:time.sleep(.25)
            else:raise RuntimeError('Controlled server startup deadline')
            code=run('living-browser',['npx.cmd','playwright','test','--config','tools/product-curator/ticket12.playwright.config.ts'],{'E2E_BASE_URL':origin,'CURATOR_EVIDENCE_DIR':str(evidence/'living-browser')})
        finally:
            server.terminate();server.wait(timeout=15)
    return code


if __name__=='__main__':raise SystemExit(main())
