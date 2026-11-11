"""Raw/clean/deployment freeze without staging or committing the real repository.

Only an external, fresh Git object store is written. Custom filters, encodings,
ident expansion, symlinks, submodules and unsafe paths fail closed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
ATTRS=('text','eol','filter','working-tree-encoding','ident')
SCHEMA='furnitureos-source-projection-v1'

def canonical(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def pin(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def safe_path(p):
    assert isinstance(p,str) and p and not p.startswith('/') and '\\' not in p and ':' not in p and '\n' not in p and '\r' not in p
    assert all(x not in ('','..','.','.git') for x in p.split('/'))
    return p
def no_links(p):
    p=Path(p).absolute()
    for f in (p,*p.parents):
        assert not f.is_symlink() and not (hasattr(f,'is_junction') and f.is_junction()),f'Linked path: {f}'
    return p
def git_context(root,args,external=False):
    env=os.environ.copy()
    for k in list(env):
        if k.startswith('GIT_'):env.pop(k)
    if external:env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_ATTR_NOSYSTEM='1')
    # cat-file filters resolve attributes from the working-directory context.
    # Run all projected path operations at the explicit external worktree root.
    cwd=Path(args[args.index('--work-tree')+1]) if external and '--work-tree' in args else root
    args=list(args)
    if external:
        # Windows Git checks the literal GIT_DIR length before core.longpaths
        # can help. Use equivalent short paths from the owned external cwd.
        for option in ('--git-dir','--work-tree'):
            if option in args:
                i=args.index(option)+1;args[i]=os.path.relpath(args[i],cwd)
        if args[:2]==['init','--bare']:
            args[-1]=os.path.relpath(args[-1],cwd)
    command=['git',*(['-c','core.longpaths=true'] if external else []),*args]
    return command,cwd,env

def git(root,*args,input=None,external=False,check=True):
    command,cwd,env=git_context(root,args,external)
    r=subprocess.run(command,cwd=cwd,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if check and r.returncode:raise RuntimeError(f'Git {args[0]} exit {r.returncode}: {r.stderr.decode("utf-8",errors="replace")}')
    return r.stdout if check else r
def config(root):
    result={}
    for k in ('core.autocrlf','core.eol','core.safecrlf','core.filemode'):
        r=git(root,'config','--get',k,check=False);assert r.returncode in (0,1);result[k]=r.stdout.decode().strip() if r.returncode==0 else None
    return result
def paths(root):
    return sorted(set(git(root,'ls-files','--cached','--others','--exclude-standard','-z').decode().strip('\0').split('\0'))-{''})
def tree(root,reference):
    rows={}
    for row in git(root,'ls-tree','-r','-z','--full-tree',reference).split(b'\0'):
        if not row:continue
        header,p=row.split(b'\t',1);mode,kind,oid=header.decode().split();p=safe_path(p.decode('utf-8'))
        assert kind=='blob' and mode in ('100644','100755'),'Unsupported gitlink/symlink in source tree'
        rows[p]=dict(mode=mode,oid=oid)
    return rows
def attrs(root,files,external_args=None):
    if not files:return {}
    data=b'\0'.join(p.encode('utf-8') for p in files)+b'\0'
    a=git(root,*(external_args or []),'check-attr','-z',*ATTRS,'--stdin',input=data,external=bool(external_args)).decode().split('\0')
    result={p:{} for p in files}
    for i in range(0,len(a)-1,3):result[a[i]][a[i+1]]=a[i+2]
    for p,v in result.items():
        assert set(v)==set(ATTRS)
        assert all(v[k] in ('unspecified','unset') for k in ('filter','working-tree-encoding','ident')),f'Unsupported clean/smudge rule: {p}'
        assert v['text'] in ('unspecified','unset','set','auto') and v['eol'] in ('unspecified','unset','lf','crlf'),f'Unknown EOL rule: {p}'
    return result
def index_pin(root):
    value=git(root,'rev-parse','--git-path','index').decode().strip();p=Path(value);p=p if p.is_absolute() else root/p
    return dict(path=str(p),**pin(p.read_bytes())) if p.exists() else dict(path=str(p),absent=True)
def projection_args(out,configuration,checkout=False,windows=False):
    a=['--git-dir',str(out/'objects.git'),'--work-tree',str(out/'raw'),'-c','core.bare=false']
    values=dict(configuration)
    if checkout:values.update({'core.autocrlf':'true' if windows else 'false','core.eol':'crlf' if windows else 'lf'})
    for k,v in values.items():
        if v is not None:a.extend(['-c',f'{k}={v}'])
    return a
def iter_blobs(root,oids,external_args=None):
    # One request/response at a time bounds memory to one blob, even for the
    # expanded catalogue. No whole-catalogue stdout buffer or real index writes.
    a=external_args or []
    command,cwd,env=git_context(root,[*a,'cat-file','--batch'],bool(a))
    process=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for expected in oids:
            process.stdin.write((expected+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().decode().split();assert len(header)==3 and header[0]==expected and header[1]=='blob'
            size=int(header[2]);assert 0<=size<=2_000_000_000,'Blob service bound'
            b=process.stdout.read(size);assert len(b)==size and process.stdout.read(1)==b'\n';yield b
        process.stdin.close();error=process.stderr.read();assert process.wait()==0,error.decode('utf-8',errors='replace')
    finally:
        if process.poll() is None:process.kill();process.wait()
        process.stdout.close();process.stderr.close()
        if not process.stdin.closed:process.stdin.close()

def blobs(root,oids,external_args=None):return list(iter_blobs(root,oids,external_args))
def eol_parity(out,records,configuration):
    selected=[r for r in records if r['status']!='deleted' and r['path'].startswith('api/catalogue/providers/expansion/') and r['path'].endswith('.json')]
    by_path={r['path']:r for r in selected};facts=[]
    for r in selected:
        assert r['attributes']['text']=='unset','Raw-pinned expansion metadata requires -text'
        views={}
        for name,windows in (('windows',True),('linux',False)):
            b=git(out,*projection_args(out,configuration,checkout=True,windows=windows),'cat-file','--filters',f'--path={r["path"]}',r['expectedBlobOid'],external=True)
            assert pin(b)==r['raw']==r['deployment'],f'Raw expansion digest changed in {name}: {r["path"]}'
            views[name]=dict(**pin(b),canonicalParsedSha256=hashlib.sha256(canonical(json.loads(b))).hexdigest())
        assert views['windows']==views['linux'];facts.append(dict(path=r['path'],views=views))
        name=Path(r['path']).name
        if name!='index.json':assert name==r['raw']['sha256']+'.json','Content-addressed batch filename drift'
    index='api/catalogue/providers/expansion/index.json'
    if index in by_path:
        value=json.loads((out/'deployment'/index).read_bytes())
        assert value['schemaVersion']==1 and value['policyVersion']=='catalogue-expansion-index-v1'
        assert len(set(value['batches']))==len(value['batches'])
        for digest in value['batches']:
            assert isinstance(digest,str) and len(digest)==64 and all(c in '0123456789abcdef' for c in digest)
            p=f'api/catalogue/providers/expansion/{digest}.json';assert p in by_path and by_path[p]['raw']['sha256']==digest
    return dict(status='PARITY_VERIFIED' if selected else 'UNCONFIGURED_NO_EXPANSION_METADATA',scope='Git clean blob and simulated Windows/Linux checkout filters; no real OS build or Product acceptance',records=facts)

def freeze(source,out):
    source=no_links(source).resolve();out=no_links(out)
    assert source!=out and source not in out.parents and out not in source.parents,'Projection must be external'
    for p in (out,*out.parents):assert not (p/'.git').exists(),'Projection output must be outside every checkout'
    out.mkdir(parents=True,exist_ok=False)
    (out/'OWNER.json').write_bytes(canonical(dict(kind=SCHEMA,source=str(source))))
    before=index_pin(source);configuration=config(source);head=git(source,'rev-parse','HEAD').decode().strip();baseline=tree(source,'HEAD');files=paths(source)
    assert not git(source,'ls-files','--unmerged'), 'Cannot project an unresolved index'
    all_paths=sorted(set(files)|set(baseline));rules=attrs(source,[p for p in all_paths if (source/p).exists()])
    raw_size=sum((source/p).stat().st_size for p in all_paths if (source/p).exists())
    assert raw_size<=2_000_000_000 and len(all_paths)<=30_000,'Projection input service bound'
    assert shutil.disk_usage(out).free>=raw_size*4+100_000_000,'Insufficient external disk for two views and object store'
    (out/'raw').mkdir();(out/'deployment').mkdir();records=[]
    mode_by_index={}
    for row in git(source,'ls-files','--stage','-z').split(b'\0'):
        if row:
            h,p=row.split(b'\t',1);mode,_,stage=h.decode().split();assert stage=='0';mode_by_index[p.decode()]=mode
    for p in all_paths:
        safe_path(p);file=no_links(source/p)
        if not file.exists():records.append(dict(path=p,status='deleted',baseline=baseline.get(p),raw=None,deployment=None,expectedBlobOid=None));continue
        assert file.is_file();b=file.read_bytes();dest=out/'raw'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
        mode=mode_by_index.get(p,'100644')
        if configuration['core.filemode'] not in ('false','0','no','off'):mode='100755' if file.stat().st_mode & 0o111 else '100644'
        assert mode in ('100644','100755')
        records.append(dict(path=p,status='present' if p in baseline else 'added',mode=mode,baseline=baseline.get(p),raw=pin(b),attributes=rules[p]))
    fmt=git(source,'rev-parse','--show-object-format').decode().strip();assert fmt in ('sha1','sha256')
    git(out,'init','--bare',f'--object-format={fmt}',str(out/'objects.git'),external=True)
    a=projection_args(out,configuration)
    external_rules=attrs(out,[r['path'] for r in records if r['status']!='deleted'],a)
    assert external_rules==rules,'Unsupported global/info attribute context differs from the source tree'
    present=[r for r in records if r['status']!='deleted']
    # Git applies each path's real clean filter in one bounded process. Quoted
    # UTF-8 paths preserve whitespace; no shell or real index is involved.
    names=''.join(json.dumps(r['path'],ensure_ascii=False)+'\n' for r in present).encode('utf-8')
    oids=git(out,*a,'hash-object','-w','--stdin-paths',input=names,external=True).decode().splitlines()
    assert len(oids)==len(present),'Incomplete clean blob inventory'
    for r,oid in zip(present,oids,strict=True):
        assert len(oid)==(40 if fmt=='sha1' else 64) and all(c in '0123456789abcdef' for c in oid)
        r['expectedBlobOid']=oid
    clean=iter_blobs(out,[r['expectedBlobOid'] for r in present],a) if present else []
    for r,b in zip(present,clean,strict=True):
        r['cleanBlob']=pin(b)
        # Linux deployment uses core.autocrlf=false/core.eol=lf. Explicit crlf
        # attributes still win; use Git's actual smudge implementation for those.
        if r['attributes']['eol']=='crlf' and r['attributes']['text']!='unset':b=git(out,*projection_args(out,configuration,checkout=True),'cat-file','--filters',f'--path={r["path"]}',r['expectedBlobOid'],external=True)
        r['deployment']=pin(b);r['normalizationChanged']=r['raw']!=r['deployment'];dest=out/'deployment'/r['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
        if r['path'].startswith('api/catalogue/providers/expansion/') and r['path'].endswith('.json'):
            r['canonicalParsedSha256']=hashlib.sha256(canonical(json.loads(b))).hexdigest()
    assert paths(source)==files and config(source)==configuration,'Source/config changed during projection'
    assert attrs(source,list(rules))==rules
    for r in present:assert pin((source/r['path']).read_bytes())==r['raw'],'Source bytes changed during projection'
    assert index_pin(source)==before,'Real index changed during projection'
    record=dict(schemaVersion=SCHEMA,createdAt=datetime.now(timezone.utc).isoformat(),sourceRoot=str(source),baselineCommit=head,objectFormat=fmt,configuration=configuration,realIndexBefore=before,realIndexAfter=index_pin(source),deploymentConfiguration={'core.autocrlf':'false','core.eol':'lf'},scope='Raw working bytes and exact expected Git clean/deployment bytes, not a commit/inspection/deployment',records=records,eolParity=eol_parity(out,records,configuration),commitStatus='UNRUN_AUTHORIZATION_REQUIRED')
    (out/'PROJECTION.json').write_bytes(canonical(record)+b'\n');return record

def read_projection(file,digest):
    raw=no_links(file).read_bytes();assert hashlib.sha256(raw).hexdigest()==digest,'Projection receipt SHA256 changed';r=json.loads(raw);assert r['schemaVersion']==SCHEMA
    for v in r['records']:
        safe_path(v['path'])
        if v['status']!='deleted':
            assert pin(no_links(file.parent/'raw'/v['path']).read_bytes())==v['raw'],'Frozen raw projection changed'
            assert pin(no_links(file.parent/'deployment'/v['path']).read_bytes())==v['deployment'],'Frozen deployment projection changed'
    return r
def verify_raw(file,digest):
    r=read_projection(file,digest);source=Path(r['sourceRoot']);assert config(source)==r['configuration']
    assert sorted(set(paths(source))|set(tree(source,'HEAD')))==[v['path'] for v in r['records']]
    assert git(source,'rev-parse','HEAD').decode().strip()==r['baselineCommit']
    for v in r['records']:
        p=no_links(source/safe_path(v['path']))
        if v['status']=='deleted':assert not p.exists()
        else:assert pin(p.read_bytes())==v['raw']
    assert attrs(source,[v['path'] for v in r['records'] if v['status']!='deleted'])=={v['path']:v['attributes'] for v in r['records'] if v['status']!='deleted'}
    return dict(status='RAW_VIEW_UNCHANGED',sourceRoot=str(source),records=len(r['records']))
def verify_tree(root,reference,record):
    actual=tree(root,reference);expected={r['path']:r for r in record['records'] if r['status']!='deleted'}
    assert set(actual)==set(expected),'Committed path set differs: missing/unexpected files or ignored deletions'
    for p,e in expected.items():assert actual[p]==dict(mode=e['mode'],oid=e['expectedBlobOid']),f'Committed blob/mode changed: {p}'
    data=iter_blobs(root,[actual[p]['oid'] for p in sorted(actual)])
    for p,b in zip(sorted(actual),data,strict=True):
        e=expected[p];assert pin(b)==e['cleanBlob'],f'Committed blob bytes changed: {p}'
        # Explicit crlf checkout paths use recorded deployment bytes; all other
        # supported paths deploy exactly their committed clean blob.
        if e['attributes']['eol']!='crlf' or e['attributes']['text']=='unset':assert pin(b)==e['deployment'],f'Deployment bytes changed: {p}'
    return dict(status='EXACT_COMMITTED_TREE_PARITY',paths=len(actual),deletions=sum(r['status']=='deleted' for r in record['records']))
def verify_commit(file,digest,commit):
    r=read_projection(file,digest);source=Path(r['sourceRoot']);assert len(commit)==(40 if r['objectFormat']=='sha1' else 64) and all(c in '0123456789abcdef' for c in commit)
    assert config(source)==r['configuration'],'Source EOL configuration changed after the freeze'
    expected_present={v['path'] for v in r['records'] if v['status']!='deleted'}
    assert set(paths(source))==expected_present,'Current source path set changed after the freeze'
    for v in r['records']:
        p=no_links(source/v['path'])
        if v['status']=='deleted':assert not p.exists()
        else:assert pin(p.read_bytes())==v['raw'],'Current raw source changed after the freeze'
    assert attrs(source,sorted(expected_present))=={v['path']:v['attributes'] for v in r['records'] if v['status']!='deleted'},'Source attributes changed after the freeze'
    assert git(source,'cat-file','-t',commit).decode().strip()=='commit'
    result=verify_tree(source,commit,r);out=file.parent
    # Reconstruct exact source blobs from the actual committed tree in a fresh
    # external directory. No checkout or real-index write is performed.
    import uuid
    destination=out/f'committed-{commit}-{uuid.uuid4().hex[:8]}';destination.mkdir()
    actual=tree(source,commit)
    expected={v['path']:v for v in r['records'] if v['status']!='deleted'}
    for p,b in zip(sorted(actual),iter_blobs(source,[actual[p]['oid'] for p in sorted(actual)]),strict=True):
        f=destination/'clean'/safe_path(p);f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
        e=expected[p]
        if e['attributes']['eol']=='crlf' and e['attributes']['text']!='unset':
            b=git(out,*projection_args(out,r['configuration'],checkout=True),'cat-file','--filters',f'--path={p}',actual[p]['oid'],external=True)
        assert pin(b)==e['deployment'],f'Actual commit deployment reconstruction changed: {p}'
        f=destination/'deployment'/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(b)
    # Actual committed blob OIDs/bytes were compared above with the pinned
    # external object store; parity is therefore bound to those exact blobs.
    parity=eol_parity(out,r['records'],r['configuration'])
    return {**result,'commitSha':commit,'treeSha':git(source,'rev-parse',f'{commit}^{{tree}}').decode().strip(),'reconstructed':str(destination),'eolParity':parity,'hostedAcceptance':'UNRUN','independentInspection':'NOT_ASSERTED'}

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    f=s.add_parser('freeze');f.add_argument('--out',type=Path,required=True)
    for command in ('verify-raw','verify-commit'):
        v=s.add_parser(command);v.add_argument('--projection',type=Path,required=True);v.add_argument('--projection-sha256',required=True)
        if command=='verify-commit':v.add_argument('--commit',required=True)
    a=p.parse_args()
    if a.command=='freeze':
        r=freeze(ROOT,a.out);result=dict(path=str(a.out/'PROJECTION.json'),**pin((a.out/'PROJECTION.json').read_bytes()),records=len(r['records']),normalizationDifferences=sum(v.get('normalizationChanged',False) for v in r['records']),eolParity=r['eolParity']['status'],realIndexUnchanged=r['realIndexBefore']==r['realIndexAfter'],commit='NOT_CREATED')
    else:
        assert read_projection(a.projection,a.projection_sha256)['sourceRoot']==str(ROOT.resolve()),'Projection targets another worktree'
        result=verify_raw(a.projection,a.projection_sha256) if a.command=='verify-raw' else verify_commit(a.projection,a.projection_sha256,a.commit)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
