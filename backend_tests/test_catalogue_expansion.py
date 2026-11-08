"""Synthetic publication records in temporary roots; no curation evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
from api.catalogue.providers.abo import seed_catalogue, ROOT
from api.catalogue.providers.expansion import expanded_entries, canonical, CatalogueExpansionError, ExpansionEntry


@pytest.fixture
def publication(tmp_path):
    r=next(r for r in seed_catalogue().products if r.category=='nightstand')
    record=r.model_dump(mode='json',exclude={'listingDimensions'})
    record['accessRegions']=[dict(face='front',depthM=.6,required=True,purpose='Controlled fixture drawer access')]
    source=ROOT/'public/products'/r.productId
    dest=tmp_path/'public/products'/r.productId
    shutil.copytree(source,dest)
    files=[dict(file=f.relative_to(source).as_posix(),bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in sorted(source.rglob('*')) if f.is_file()]
    batch=dict(schemaVersion=1,profile='catalogue-expansion-v1',batchId='controlled-loader-fixture',intakeSha256='0'*64,metadataSha256='660f4d01bf817802c4fc664e848af12b72246efdb15324ad1d0d2bce33f54fe9',review=dict(actor='agent',reviewerIdentity='automated-fixture-NOT-review',purpose='Controlled loader contract only',evidenceKind='genuine-agent-curation',evidenceSha256='0'*64),curatedOn='2026-10-29',entries=[dict(record=record,rooms=['bedroom'],files=files,reviewSha256='0'*64,conversionSha256='0'*64)])
    directory=tmp_path/'api/catalogue/providers/expansion';directory.mkdir(parents=True)
    def install(batch):
        raw=canonical(batch).encode();h=hashlib.sha256(raw).hexdigest();(directory/f'{h}.json').write_bytes(raw)
        (directory/'index.json').write_text(json.dumps(dict(schemaVersion=1,policyVersion='catalogue-expansion-index-v1',baseVersion='controlled-base',batches=[h])),encoding='utf-8')
        return h
    h=install(batch)
    return tmp_path,directory,batch,h,install


def test_runtime_and_packaged_union_have_the_same_version_and_dimensions(publication):
    root,directory,batch,h,_=publication
    entries,version=expanded_entries((),'controlled-base',(),root=root)
    assert len(entries)==1 and entries[0].product.id==batch['entries'][0]['record']['productId']
    expected='controlled-base+expansion-'+hashlib.sha256(canonical(json.loads((directory/'index.json').read_bytes())).encode()).hexdigest()
    assert version==expected
    p=entries[0].product.id
    packaged=root/'api/catalogue/providers/manifests';packaged.mkdir()
    shutil.copyfile(root/'public/products'/p/'asset-manifest.json',packaged/f'{p}.json')
    (root/'public/products'/p).rename(root/'retained-unpackaged-product')
    assert expanded_entries((),'controlled-base',(),root=root)==(entries,version)
    (packaged/f'{p}.json').write_text('{}')
    with pytest.raises(CatalogueExpansionError,match='bytes changed'):
        expanded_entries((),'controlled-base',(),root=root)


@pytest.mark.parametrize('change',['index','batch','asset','base','duplicate','missing'])
def test_configured_expansion_fails_closed(publication,change):
    root,directory,batch,h,install=publication
    if change=='index':(directory/'index.json').write_text('{}')
    elif change=='batch':(directory/f'{h}.json').write_text('{}')
    elif change=='asset':(root/'public/products'/batch['entries'][0]['record']['productId']/'lod0.bin').write_bytes(b'corrupt')
    elif change=='base':
        with pytest.raises(CatalogueExpansionError):expanded_entries((),'wrong-base',(),root=root)
        return
    elif change=='duplicate':batch['entries'].append(deepcopy(batch['entries'][0]));install(batch)
    else:(directory/f'{h}.json').rename(directory/'retained-missing-batch.json')
    with pytest.raises(CatalogueExpansionError):expanded_entries((),'controlled-base',(),root=root)


def test_absent_index_preserves_base_and_orphan_batch_is_unadvertised(publication):
    root,directory,*_=publication
    (directory/'index.json').rename(directory/'retained-index.json')
    assert expanded_entries((),'controlled-base',(),root=root)==((),'controlled-base')


@pytest.mark.parametrize('change',['rug-overlap','missing-access','access-wall','unknown-style','wrong-room','short-access'])
def test_review_contract_rejects_unsafe_metadata(publication,change):
    _,_,batch,_,_=publication
    e=deepcopy(batch['entries'][0]);r=e['record']
    if change=='rug-overlap':r['placementClass']='floor-covering'
    elif change=='missing-access':r['accessRegions']=[]
    elif change=='access-wall':r['wallContactFaces']=['front']
    elif change=='unknown-style':r['privateStyleIds']=['style-99']
    elif change=='wrong-room':e['rooms']=['living-room']
    else:r['accessRegions'][0]['depthM']=.1
    with pytest.raises(ValueError):ExpansionEntry.model_validate(e)
