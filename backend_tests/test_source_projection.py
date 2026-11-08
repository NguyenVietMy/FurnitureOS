"""Offline external Git object/filter tests. No commits or real-index mutations."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from scripts.source_projection import ROOT,ATTRS,attrs,canonical,eol_parity,freeze,git,index_pin,pin,projection_args,read_projection,verify_raw,verify_tree


def parity_fixture(tmp_path,with_attributes=True):
    out=tmp_path/'projection';(out/'raw/api/catalogue/providers/expansion').mkdir(parents=True)
    attr=(ROOT/'.gitattributes').read_bytes() if with_attributes else b'* text=auto\n'
    (out/'raw/.gitattributes').write_bytes(attr)
    # Serialization fixture only, not Product/reviewer/hosted evidence.
    batch=canonical(dict(scope='CONTROLLED EOL serialization fixture',label='caf\u00e9',note='line one\nline two'))
    digest=hashlib.sha256(batch).hexdigest()
    data={f'api/catalogue/providers/expansion/{digest}.json':batch,'api/catalogue/providers/expansion/index.json':canonical(dict(schemaVersion=1,policyVersion='catalogue-expansion-index-v1',baseVersion='CONTROLLED-NOT-PUBLISHED',batches=[digest]))+b'\n'}
    for p,b in data.items():
        (out/'raw'/p).write_bytes(b)
        deployment=out/'deployment'/p;deployment.parent.mkdir(parents=True,exist_ok=True);deployment.write_bytes(b)
    git(out,'init','--bare',str(out/'objects.git'),external=True)
    cfg={'core.autocrlf':'true','core.eol':None,'core.safecrlf':None,'core.filemode':'false'};a=projection_args(out,cfg);rules=attrs(out,list(data),a);records=[]
    for p,b in data.items():
        oid=git(out,*a,'hash-object','-w',f'--path={p}','--stdin',input=b,external=True).decode().strip()
        records.append(dict(path=p,status='added',raw=pin(b),deployment=pin(b),attributes=rules[p],expectedBlobOid=oid))
    return out,cfg,records


def test_content_addressed_expansion_and_index_survive_windows_and_linux_git_checkout_filters(tmp_path):
    out,cfg,records=parity_fixture(tmp_path)
    result=eol_parity(out,records,cfg)
    assert result['status']=='PARITY_VERIFIED' and len(result['records'])==2
    assert all(r['views']['windows']==r['views']['linux'] for r in result['records'])
    assert not (out/'objects.git/index').exists()


def test_missing_raw_attributes_really_change_index_bytes_on_windows_and_fail_closed(tmp_path):
    out,cfg,records=parity_fixture(tmp_path,False)
    index=next(r for r in records if r['path'].endswith('/index.json'))
    windows=git(out,*projection_args(out,cfg,checkout=True,windows=True),'cat-file','--filters',f'--path={index["path"]}',index['expectedBlobOid'],external=True)
    assert pin(windows)!=index['raw']
    assert hashlib.sha256(canonical(json.loads(windows))).hexdigest()==hashlib.sha256(canonical(json.loads((out/'raw'/index['path']).read_bytes()))).hexdigest()
    with pytest.raises(AssertionError,match='-text'):eol_parity(out,records,cfg)


def test_tree_verification_accounts_for_exact_paths_bytes_modes_and_intended_deletions(tmp_path):
    # Existing authorized baseline is read only. No fixture commit is created.
    tree_rows={}
    for row in git(ROOT,'ls-tree','-r','-z','--full-tree','HEAD').split(b'\0'):
        if row:
            h,p=row.split(b'\t',1);mode,kind,oid=h.decode().split();tree_rows[p.decode()]=(mode,oid)
    records=[]
    from scripts.source_projection import blobs
    names=sorted(tree_rows);data=blobs(ROOT,[tree_rows[p][1] for p in names])
    for p,b in zip(names,data,strict=True):records.append(dict(path=p,status='present',mode=tree_rows[p][0],expectedBlobOid=tree_rows[p][1],cleanBlob=pin(b),deployment=pin(b),attributes={'text':'unspecified','eol':'unspecified'}))
    records.append(dict(path='CONTROLLED-intended-deletion.txt',status='deleted'))
    assert verify_tree(ROOT,'HEAD',{'records':records})['deletions']==1
    missing=deepcopy(records);missing.pop(0)
    with pytest.raises(AssertionError,match='path set'):verify_tree(ROOT,'HEAD',{'records':missing})
    deleted=deepcopy(records);deleted[0]['status']='deleted'
    with pytest.raises(AssertionError,match='path set'):verify_tree(ROOT,'HEAD',{'records':deleted})
    changed=deepcopy(records);changed[0]['expectedBlobOid']='0'*40
    with pytest.raises(AssertionError,match='blob/mode'):verify_tree(ROOT,'HEAD',{'records':changed})
    changed_mode=deepcopy(records);changed_mode[0]['mode']='100755' if changed_mode[0]['mode']=='100644' else '100644'
    with pytest.raises(AssertionError,match='blob/mode'):verify_tree(ROOT,'HEAD',{'records':changed_mode})
    assert not (tmp_path/'commit').exists()


def test_current_complete_raw_and_clean_projection_preserves_real_index_and_detects_drift(tmp_path):
    before=index_pin(ROOT);out=tmp_path/'complete-projection';record=freeze(ROOT,out);file=out/'PROJECTION.json';digest=hashlib.sha256(file.read_bytes()).hexdigest()
    assert index_pin(ROOT)==before and record['realIndexBefore']==record['realIndexAfter']
    assert len(record['records'])>800 and all(r.get('expectedBlobOid') for r in record['records'] if r['status']!='deleted')
    assert verify_raw(file,digest)['status']=='RAW_VIEW_UNCHANGED'
    r=next(r for r in record['records'] if r['path']=='package.json');(out/'deployment'/r['path']).write_bytes(b'CONTROLLED-CORRUPTION')
    with pytest.raises(AssertionError,match='Frozen deployment'):read_projection(file,digest)
    assert index_pin(ROOT)==before and not (out/'objects.git/index').exists()
