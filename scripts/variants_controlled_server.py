"""Loopback-only controlled provider/storage for built-app stream proof.

Never imported by production. Uses real Catalogue bytes and FastAPI authorities.
Only synthetic Capture photos are accepted by the tests; no credentials or network.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from threading import Event, Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import Body
import uvicorn
from api.capture_auth import SupabaseAuth
from api.main import create_app
from api.provider import MODEL_ID, ProviderReply, ProviderCallError
from backend_tests.capture_transport import ControlledSupabase


class ControlledProvider:
    def __init__(self):
        self.mode = 'normal'
        self.release = Event()
        self.release_a = Event()
        self.calls = []
        self.lock = Lock()

    def generate(self, **kwargs):
        prompt = json.loads(kwargs['prompt_text'])
        dynamic = [json.loads(b['text']) for m in kwargs.get('conversation', []) if m['role']=='user'
                   for b in m['content'] if b['type']=='text']
        label = next((m['variant'] for m in reversed(dynamic) if 'variant' in m), 'A')
        with self.lock:
            self.calls.append({'variant':label,'roomType':prompt['roomType']})
        active_mode = self.mode
        gate = self.release_a if label == 'A' else self.release
        if (active_mode == 'staged' and label in ('A', 'B')) or (active_mode == 'hold' and label == 'B'):
            if not gate.wait(60):
                raise ProviderCallError('timeout','Controlled hold expired.')
        if self.mode == 'partial' and label=='B':
            raise ProviderCallError('transport-error','Controlled later failure.')
        if self.mode == 'no-fit':
            return ProviderReply({'intents':[]}, MODEL_ID, 'end_turn', None, 1)
        products = prompt['eligibleCatalogue']
        if prompt['roomType']=='bedroom':
            bed_id = {'A':'bed-prudence-tufted-queen-natural','B':'bed-rivet-jonathan-queen-walnut','C':'bed-alkove-hayes-double-wild-oak'}[label]
            bed = next(p for p in products if p['id']==bed_id)
            wall = 'wall-north'
            intents = [dict(id='anchor-bed',productId=bed['id'],kind='against',wallId=wall,face='back')]
        else:
            sofa = 'sofa-stone-beam-hillman-ivory' if label=='B' else 'sofa-stone-beam-westport-linen'
            table = 'table-rivet-modern-pine'
            zone = max(prompt['offeredZones'],key=lambda z:(z['bounds']['maxX']-z['bounds']['minX'])*(z['bounds']['maxZ']-z['bounds']['minZ']))
            anchor = dict(id='anchor-sofa',productId=sofa,kind='in_zone',zoneId=zone['id'])
            if label=='C':
                anchor = dict(id='anchor-sofa',productId=sofa,kind='centred_on',wallId='wall-north',face='back')
            intents = [anchor,dict(id='anchor-table',productId=table,kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=.85),
                       dict(id='anchor-chair',productId='chair-rivet-slade-swivel-graphite',kind='adjacent_to',referenceId='anchor-table' if label=='C' else 'anchor-sofa',side='left',gapM=.85 if label=='C' else .65)]
        return ProviderReply({'intents':intents},MODEL_ID,'end_turn',None,1)


def controlled_app():
    provider = ControlledProvider()
    storage = ControlledSupabase()
    app = create_app(generation_provider=provider, capture_repository=storage.repository,
                     capture_auth=SupabaseAuth(storage.settings, storage.client))

    @app.post('/__variants/mode')
    def mode(body: dict = Body()):
        provider.release.set()
        provider.release_a.set()
        provider.mode = body['mode']
        provider.release = Event()
        provider.release_a = Event()
        provider.calls = []
        return {'kind':'CONTROLLED-LOCAL-NO-PAID-CALLS'}

    @app.post('/__variants/release')
    def release():
        provider.release.set()
        provider.release_a.set()
        return {'released':True}

    @app.post('/__variants/release-a')
    def release_a():
        provider.release_a.set()
        return {'releasedA':True}

    @app.get('/__variants/state')
    def state():
        return {'calls':provider.calls,'leases':len(storage.leases)}

    @app.post('/__variants/invalidate/{capture_id}')
    def invalidate(capture_id: str):
        storage.revoke(storage.rows[capture_id])
        return {'invalidated':True}

    # The fixture-only controls precede the existing safe SPA fallback.
    controls = [r for r in app.router.routes if getattr(r,'path','').startswith('/__variants/')]
    app.router.routes = [*controls,*[r for r in app.router.routes if r not in controls]]
    return app


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,required=True)
    args=parser.parse_args()
    uvicorn.run(controlled_app(),host='127.0.0.1',port=args.port,access_log=False)
