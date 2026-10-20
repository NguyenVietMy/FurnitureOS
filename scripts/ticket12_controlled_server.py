"""Standalone OFFLINE HTTP fixture; never imported by api.main/index.

Uses only create_app's existing injection seams. No production env switch,
credentials, provider transport or owner evidence is enabled by this helper.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
import uvicorn
from api.catalogue import catalogue
from api.catalogue.contract import CatalogueEntry
from api.catalogue.static import StaticCatalogue
from api.capture_auth import SupabaseAuth
from api.main import create_app
from api.models import Product
from api.provider import ProviderReply, MODEL_ID
from backend_tests.capture_transport import ControlledSupabase


class ControlledMode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str


class ControlledProvider:
    mode = 'normal'

    def __init__(self, log: Path):
        self.log = log

    def generate(self, **kwargs):
        context = json.loads(kwargs['prompt_text'])
        mode = self.mode
        if mode == 'delay':
            time.sleep(2)
        with self.log.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'kind':'CONTROLLED-NO-PAID-TRANSPORT','mode':mode,'context':context})+'\n')
        products = context['eligibleCatalogue']
        sofas = [p for p in products if p['category']=='sofa']
        tables = [p for p in products if p['category']=='table']
        chairs = [p for p in products if p['category']=='chair']
        # Deterministic fixture alternatives must survive insertion of real
        # publications into the base Catalogue. Only server-eligible IDs are
        # ordered; the actual published-seed proof has no rejected table.
        sofa_order = ['sofa-stone-beam-westport-linen','sofa-stone-beam-hillman-ivory']
        table_order = ['table-rivet-industrial-walnut','table-rivet-modern-pine']
        sofas.sort(key=lambda p:(sofa_order.index(p['id']) if p['id'] in sofa_order else len(sofa_order),p['id']))
        tables.sort(key=lambda p:(table_order.index(p['id']) if p['id'] in table_order else len(table_order),p['id']))
        if sofas:
            index = 1 if mode == 'alternate' else 0
            sofa, table = sofas[index % len(sofas)], tables[index % len(tables)]
            zone = max(context['offeredZones'], key=lambda z:(z['bounds']['maxX']-z['bounds']['minX'])*(z['bounds']['maxZ']-z['bounds']['minZ']))
            anchor = dict(id='anchor-sofa',productId=sofa['id'],kind='in_zone',zoneId=zone['id'])
            if mode == 'wall':
                anchor = dict(id='anchor-sofa',productId=sofa['id'],kind='centred_on',wallId='wall-north',face='back')
            chair = next((p for p in chairs if p['id']=='chair-rivet-slade-swivel-graphite'),chairs[0])
            chair_intent = dict(id='anchor-chair',productId=chair['id'],kind='adjacent_to',referenceId='anchor-sofa',side='left',gapM=.65)
            if mode == 'wall':
                chair_intent = dict(id='anchor-chair',productId=chair['id'],kind='adjacent_to',referenceId='anchor-table',side='left',gapM=.85)
            intents = [anchor,dict(id='anchor-table',productId=table['id'],kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=0 if mode=='no-fit' else .85),chair_intent]
            if mode == 'malformed':
                intents.pop()
        else:
            bed = next(p for p in products if p['category']=='bed')
            intents = [dict(id='anchor-bed',productId=bed['id'],kind='centred_on',wallId='wall-north',face='back')]
        return ProviderReply(payload={'intents':intents},model=MODEL_ID,stop_reason='end_turn',usage=None,latency_ms=1)


def controlled_app(runtime_root: Path):
    proof = json.loads((runtime_root/'CONTROLLED-CATALOGUE.json').read_text())
    assert proof['kind']=='CONTROLLED-NOT-OWNER-NOT-PRODUCTION'
    entries = {p.id: CatalogueEntry(p, catalogue.private_style_ids(p.id)) for p in catalogue.list()}
    entries.update({e['product']['id']:CatalogueEntry(Product.model_validate(e['product']),tuple(e['privateStyleIds'])) for e in proof['entries']})
    source = StaticCatalogue('CONTROLLED-TICKET12-NOT-OWNER', entries.values())
    provider = ControlledProvider(runtime_root/'provider-calls.jsonl')
    storage = ControlledSupabase()
    application = create_app(root=runtime_root, catalogue_source=source, generation_provider=provider,
        capture_repository=storage.repository, capture_auth=SupabaseAuth(storage.settings,storage.client))

    # Insert before the normal SPA fallback in this explicit fixture only.
    @application.post('/__controlled/mode')
    def change_mode(body: ControlledMode):
        if body.mode not in {'normal','alternate','wall','no-fit','malformed','delay'}:
            raise HTTPException(422, 'Unknown controlled mode')
        provider.mode=body.mode
        return {'kind':'CONTROLLED-NOT-OWNER','mode':provider.mode}
    application.router.routes.insert(0, application.router.routes.pop())
    return application


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime-root',required=True,type=Path)
    parser.add_argument('--port',required=True,type=int)
    args=parser.parse_args()
    uvicorn.run(controlled_app(args.runtime_root),host='127.0.0.1',port=args.port)
