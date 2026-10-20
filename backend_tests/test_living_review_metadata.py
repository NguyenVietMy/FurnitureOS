"""Schema fixtures only: never review journals, decisions or production publications."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from api.catalogue.providers.living import ReviewedLiving

ROOT = Path(__file__).resolve().parents[1]


def schematic_metadata():
    raw = (ROOT/'api/catalogue/providers/abo-living-candidates.json').read_bytes()
    proposal = json.loads(raw)
    files = [dict(file=name, bytes=1, sha256='0'*64) for name in
             ['asset-manifest.json','lod0.gltf','lod0.bin','lod1.gltf','lod1.bin','lod2.gltf','lod2.bin','textures/SCHEMA-ONLY.ktx2']]
    return dict(schemaVersion=1, version='abo-living-reviewed-v1', profileSha256=hashlib.sha256(raw).hexdigest(),
                reviewActor='agent', reviewEvidenceSha256='0'*64,
                entries=[dict(productId=proposal['products'][i]['productId'], rooms=['living-room'], privateStyleIds=['style-01'], files=files) for i in [0,2,4,6,7]])


@pytest.mark.parametrize('actor', ['agent', 'owner'])
def test_python_and_node_accept_the_same_truthful_review_provenance_schema(actor):
    value=schematic_metadata()
    value['reviewActor']=actor
    assert ReviewedLiving.model_validate(value).reviewActor==actor
    node=subprocess.run(['node','--input-type=module','-e',
        "import {validateReviewedLiving} from './scripts/asset-pipeline.config.mjs'; let s=''; for await (const c of process.stdin) s+=c; validateReviewedLiving(JSON.parse(s));"],
        cwd=ROOT,input=json.dumps(value),capture_output=True,text=True)
    assert node.returncode==0,node.stderr


@pytest.mark.parametrize('change', [
    {'reviewActor':'automated'}, {'reviewActor':'controlled'}, {'version':'CONTROLLED-NOT-OWNER-NOT-PRODUCTION'},
    {'reviewEvidenceSha256':'not-a-pin'}, {'ownerEvidenceSha256':'0'*64},
])
def test_python_and_node_reject_controlled_or_mislabelled_review_metadata(change):
    value=deepcopy(schematic_metadata())
    value.update(change)
    with pytest.raises(ValidationError):ReviewedLiving.model_validate(value)
    node=subprocess.run(['node','--input-type=module','-e',
        "import {validateReviewedLiving} from './scripts/asset-pipeline.config.mjs'; let s=''; for await (const c of process.stdin) s+=c; validateReviewedLiving(JSON.parse(s));"],
        cwd=ROOT,input=json.dumps(value),capture_output=True,text=True)
    assert node.returncode!=0


def test_reviewed_seed_requires_common_style_on_chair_as_well_as_sofa_and_table():
    value=schematic_metadata()
    value['entries'][2]['privateStyleIds']=['style-02']
    with pytest.raises(ValidationError,match='three anchors'):ReviewedLiving.model_validate(value)
    node=subprocess.run(['node','--input-type=module','-e',
        "import {validateReviewedLiving} from './scripts/asset-pipeline.config.mjs'; let s=''; for await (const c of process.stdin) s+=c; validateReviewedLiving(JSON.parse(s));"],
        cwd=ROOT,input=json.dumps(value),capture_output=True,text=True)
    assert node.returncode!=0 and 'common supported Style' in node.stderr
