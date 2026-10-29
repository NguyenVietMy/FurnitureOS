"""Controlled continuation, authority and boundary evidence; no paid calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import asyncio
import time
from math import pi

import httpx
import pytest
from fastapi.testclient import TestClient

from api.catalogue import catalogue
from api.catalogue.contract import CatalogueEntry
from api.catalogue.static import StaticCatalogue
from api.capture_auth import SupabaseAuth
from api.domain import rectangular_room_shell
from api.live_generation import LiveGenerationRequest, _output_schema, _usage_summary
from api.main import create_app
from api.models import Dimensions
from api.provider import AnthropicProvider, BudgetLedger, ProviderSettings, ProviderUsage, ProviderCallError
from api.swaps import DesignSessionStore
from api.variants import BatchControl, variant_events, solved_signature, stream_response, ShellEvent, CompleteEvent, DeadlineStreamingResponse, ErrorEvent, VariantEvent, ProgressEvent
from backend_tests.test_captures import confirmed, harness, A, B
from backend_tests.test_live_generation import TranscriptProvider, CONTROLLED_IMAGE_BASE64
from backend_tests.test_living_generation import controlled_catalogue, chair_intent

ROOM = rectangular_room_shell('controlled-variants', 8, 8, 2.7)
REQUEST = LiveGenerationRequest(roomType='living-room', referenceId='ref-01')


def selection(wall='wall-north', optional=False):
    result = {'intents': [dict(id='anchor-sofa', productId='controlled-sofa', kind='centred_on', wallId=wall, face='back'),
        dict(id='anchor-table', productId='controlled-table', kind='adjacent_to', referenceId='anchor-sofa', side='front', gapM=.8), chair_intent()]}
    if optional:
        result['intents'].append(dict(id='optional-rug', productId='controlled-rug', kind='adjacent_to', referenceId='anchor-sofa', side='back', gapM=0))
    return result


def run(outcomes, *, source=None, control=None, store=None):
    source = source or controlled_catalogue()
    provider = outcomes if hasattr(outcomes, 'generate') else TranscriptProvider(outcomes)
    store = store or DesignSessionStore(source)
    return list(variant_events(source, REQUEST, ROOM, store, provider=provider, control=control)), provider, store


def test_three_distinct_actual_designs_order_and_independent_sessions():
    events, provider, store = run([selection(w) for w in ('wall-north','wall-south','wall-east')])
    assert [e.type for e in events] == ['shell','progress','variant','progress','variant','progress','variant','complete']
    variants = [e for e in events if e.type == 'variant']
    assert [v.variant for v in variants] == ['A','B','C']
    assert len({v.signature for v in variants}) == 3
    sessions = [v.result.design.swap.sessionId for v in variants]
    assert len(set(sessions)) == 3 and all(store.current(s).version == 1 for s in sessions)
    # Only A changes; background original solved history remains immutable.
    changed = store.swap(__import__('api.models', fromlist=['SwapRequest']).SwapRequest(
        sessionId=sessions[0], expectedVersion=1, instanceId='anchor-sofa', replacementProductId='controlled-sofa-other'))
    assert changed.status == 'accepted'
    assert [store.current(s).version for s in sessions] == [2,1,1]
    prefix = provider.calls[0]['conversation'][0]
    assert all(c['conversation'][0] == prefix for c in provider.calls)
    assert prefix['content'][-1]['cache_control'] == {'type':'ephemeral'}
    assert not any(k in prefix['content'][-1]['text'] for k in ('providerCallNumber','previousSelection','chronologicalHistory'))
    turns = provider.calls[2]['conversation']
    assert [m['role'] for m in turns].count('assistant') == 2
    feedback = [json.loads(b['text']) for m in turns if m['role']=='user' for b in m['content'] if b['type']=='text']
    solved = [f for f in feedback if 'serverSolvedVariant' in f]
    assert [f['placements'] for f in solved] == [[p.model_dump(mode='json') for p in v.result.design.placements] for v in variants[:2]]


def test_actual_optional_drops_are_in_continued_history_and_five_candidate_fifteen_call_bound():
    base = controlled_catalogue()
    source = StaticCatalogue('controlled-oversize-rug', [CatalogueEntry(p.model_copy(update={'dimensionsM':Dimensions(widthM=20,heightM=.02,depthM=20)}) if p.category=='rug' else p, ('style-01',)) for p in base.list()])
    # A solves after drops. B duplicates A, then becomes distinct. C duplicates B twice.
    walls = ['wall-north','wall-north','wall-south','wall-south','wall-south']
    events, provider, _ = run([selection(w, True) for w in walls for _ in range(3)], source=source)
    assert len(provider.calls) == 15
    assert [e.variant for e in events if e.type=='variant'] == ['A','B']
    assert events[-1].reason == 'duplicate-exhausted' and events[-1].providerCalls == 15
    fourth = provider.calls[3]['conversation']
    feedback = [json.loads(b['text']) for m in fourth if m['role']=='user' for b in m['content'] if b['type']=='text']
    solved = next(f for f in feedback if 'serverSolvedVariant' in f)
    assert solved['removed'] == [{'requestId':'optional-rug','productId':'controlled-rug'}]
    assert len(solved['placements']) == 3 and 'controlled-rug' not in solved['products']
    assert [a['stage'] for a in solved['dropHistory']['attempts']] == ['initial','repair','repair','drop']
    # The exact raw assistant proposals, including the dropped rug, are still present.
    assert sum('controlled-rug' in m['content'][0]['text'] for m in fourth if m['role']=='assistant') == 3


@pytest.mark.parametrize('bad', [
    pytest.param({'intents': [{'id': 'anchor-sofa', 'kind': 'centred_on', 'wallId': 'wall-north', 'face': 'back'}]}, id='missing-product'),
    pytest.param({'intents': [{k: v for k, v in selection()['intents'][0].items() if k != 'id'}]}, id='missing-request'),
    pytest.param({'intents': None}, id='null-intents'),
    pytest.param({'intents': 'invalid'}, id='string-intents'),
    pytest.param({'intents': {'id': 'anchor-sofa'}}, id='mapping-intents'),
    pytest.param({'intents': [None]}, id='null-element'),
    pytest.param({'intents': ['invalid']}, id='string-element'),
    pytest.param({'intents': [[]]}, id='list-element'),
    pytest.param({'intents': [42]}, id='numeric-element'),
    pytest.param({'intents': [{**selection()['intents'][0], 'id': None}]}, id='null-request'),
    pytest.param({'intents': [{**selection()['intents'][0], 'id': ['anchor-sofa']}]}, id='list-request'),
    pytest.param({'intents': [{**selection()['intents'][0], 'productId': None}]}, id='null-product'),
    pytest.param({'intents': [{**selection()['intents'][0], 'productId': {'id': 'controlled-sofa'}}]}, id='mapping-product'),
])
def test_rejected_malformed_turn_is_retained_through_repaired_a_and_distinct_b_c(bad):
    outcomes = [bad, selection(), selection('wall-east'), selection('wall-south')]
    events, provider, _ = run(outcomes)
    variants = [event for event in events if event.type == 'variant']
    assert [event.variant for event in variants] == ['A', 'B', 'C']
    assert len({event.signature for event in variants}) == 3
    assert len(provider.calls) == 4 and events[-1].providerCalls == 4
    assert events[-1].status == 'complete'
    assert [rejection.code for rejection in variants[0].result.selectionRejections] == ['operation-shape-error']
    assert [attempt.stage for attempt in variants[0].result.design.arrangementHistory.attempts] == ['initial']
    correction = json.loads(provider.calls[1]['prompt_text'])
    assert correction['validSelectionNumber'] == 0 and correction['actualPrecedingFeedback'] is None
    prefix = provider.calls[0]['conversation'][0]
    for index, call in enumerate(provider.calls):
        assert call['conversation'][0] == prefix
        raw = [json.loads(message['content'][0]['text']) for message in call['conversation'] if message['role'] == 'assistant']
        assert raw == outcomes[:index]  # Retain the rejected turn in its actual position.
    for index, count in ((2, 1), (3, 2)):
        feedback = [json.loads(block['text']) for message in provider.calls[index]['conversation']
                    if message['role'] == 'user' for block in message['content'] if block['type'] == 'text']
        solved = [item for item in feedback if 'serverSolvedVariant' in item]
        assert [item['serverSolvedVariant'] for item in solved] == ['A', 'B'][:count]
        for item, variant in zip(solved, variants[:count], strict=True):
            design = variant.result.design
            assert item['placements'] == [placement.model_dump(mode='json') for placement in design.placements]
            assert item['products'] == [product.id for product in design.products]
            assert item['dropHistory'] == design.arrangementHistory.model_dump(mode='json')
            assert item['removed'] == []


def test_later_optional_drop_retains_actual_product_after_malformed_rejected_turn():
    base = controlled_catalogue()
    source = StaticCatalogue('controlled-oversize-rug', [CatalogueEntry(p.model_copy(update={'dimensionsM':Dimensions(widthM=20,heightM=.02,depthM=20)}) if p.category=='rug' else p, ('style-01',)) for p in base.list()])
    bad = {'intents': [{'id': 'optional-rug', 'productId': 'controlled-lamp'}, None]}
    outcomes = [bad, selection(), *[selection('wall-east', True) for _ in range(3)], selection('wall-south')]
    events, provider, _ = run(outcomes, source=source)
    variants = [event for event in events if event.type == 'variant']
    assert [event.variant for event in variants] == ['A', 'B', 'C']
    assert [event.result.providerCalls for event in variants] == [2, 3, 1]
    assert len(provider.calls) == 6 and events[-1].providerCalls == 6 and events[-1].status == 'complete'
    turns = provider.calls[5]['conversation']
    assert [json.loads(message['content'][0]['text']) for message in turns if message['role'] == 'assistant'] == outcomes[:5]
    assert all(call['conversation'][0] == provider.calls[0]['conversation'][0] for call in provider.calls)
    feedback = [json.loads(block['text']) for message in turns if message['role'] == 'user'
                for block in message['content'] if block['type'] == 'text']
    solved = [item for item in feedback if 'serverSolvedVariant' in item]
    assert [item['serverSolvedVariant'] for item in solved] == ['A', 'B']
    assert solved[0]['removed'] == []
    assert solved[1]['removed'] == [{'requestId': 'optional-rug', 'productId': 'controlled-rug'}]
    design = variants[1].result.design
    assert 'controlled-rug' not in solved[1]['products'] and len(solved[1]['placements']) == 3
    assert solved[1]['placements'] == [placement.model_dump(mode='json') for placement in design.placements]
    assert solved[1]['dropHistory'] == design.arrangementHistory.model_dump(mode='json')
    assert [attempt.stage for attempt in design.arrangementHistory.attempts] == ['initial', 'repair', 'repair', 'drop']


def test_skipped_protected_drop_preserves_retained_products_in_b_and_c_feedback():
    from api.zones import derive_zones

    base = controlled_catalogue()
    source = StaticCatalogue('controlled-skipped-rug-actual-lamp-drop', [
        CatalogueEntry(product.model_copy(update={'dimensionsM': Dimensions(widthM=20, heightM=1.5, depthM=20)})
                       if product.id == 'controlled-lamp' else product, ('style-01',))
        for product in base.list()])
    zone = derive_zones(ROOM, 'living-room').zones[0].id
    initial = {'intents': [
        dict(id='optional-rug', productId='controlled-rug', kind='in_zone', zoneId=zone),
        dict(id='anchor-sofa', productId='controlled-sofa', kind='adjacent_to', referenceId='optional-rug', side='front', gapM=-1.5),
        dict(id='anchor-table', productId='controlled-table', kind='adjacent_to', referenceId='anchor-sofa', side='front', gapM=.8),
        dict(id='anchor-chair', productId='controlled-chair', kind='adjacent_to', referenceId='anchor-sofa', side='left', gapM=.6),
        dict(id='optional-lamp', productId='controlled-lamp', kind='in_zone', zoneId=zone),
    ]}
    outcomes = [initial] * 3 + [selection('wall-east'), selection('wall-south')]
    events, provider, _ = run(outcomes, source=source)
    variants = [event for event in events if event.type == 'variant']
    assert [event.variant for event in variants] == ['A', 'B', 'C']
    assert len({event.signature for event in variants}) == 3
    assert [event.result.providerCalls for event in variants] == [3, 1, 1]
    assert len(provider.calls) == events[-1].providerCalls == 5 and events[-1].status == 'complete'
    design = variants[0].result.design
    retained = {'anchor-sofa': 'controlled-sofa', 'anchor-table': 'controlled-table',
                'anchor-chair': 'controlled-chair', 'optional-rug': 'controlled-rug'}
    assert {placement.instanceId: placement.productId for placement in design.placements} == retained
    assert {product.id for product in design.products} == set(retained.values())
    assert design.circulation.status == 'clear' and not variants[0].result.selectionRejections
    attempts = design.arrangementHistory.attempts
    assert [(attempt.stage, attempt.outcome) for attempt in attempts] == [
        ('initial', 'placement-failed'), ('repair', 'placement-failed'), ('repair', 'placement-failed'),
        ('skipped-drop', 'skipped'), ('drop', 'solved')]
    assert all(not attempt.droppedRequestIds for attempt in attempts[:3])
    assert attempts[3].droppedRequestIds == tuple(sorted(retained)) and attempts[3].attemptedCandidates == 0
    assert attempts[4].droppedRequestIds == ('optional-lamp',)
    for index, call in enumerate(provider.calls):
        assert call['conversation'][0] == provider.calls[0]['conversation'][0]
        assert [json.loads(message['content'][0]['text']) for message in call['conversation']
                if message['role'] == 'assistant'] == outcomes[:index]
    for index, labels in ((3, ['A']), (4, ['A', 'B'])):
        feedback = [json.loads(block['text']) for message in provider.calls[index]['conversation']
                    if message['role'] == 'user' for block in message['content'] if block['type'] == 'text']
        solved = [item for item in feedback if 'serverSolvedVariant' in item]
        assert [item['serverSolvedVariant'] for item in solved] == labels
        assert solved[0]['removed'] == [{'requestId': 'optional-lamp', 'productId': 'controlled-lamp'}]
        assert solved[0]['dropHistory'] == design.arrangementHistory.model_dump(mode='json')
        assert solved[0]['placements'] == [placement.model_dump(mode='json') for placement in design.placements]
        assert solved[0]['products'] == [product.id for product in design.products]
        if len(solved) == 2:
            assert solved[1]['removed'] == []


def test_duplicate_exhaustion_and_nonduplicate_failure_preserve_a():
    events,p,_ = run([selection()]*3)
    assert len(p.calls)==3 and events[-1].available==('A',) and events[-1].reason=='duplicate-exhausted'
    events,p,_ = run([selection(), ProviderCallError('transport-error','Controlled failure')])
    assert len(p.calls)==2 and events[-1].available==('A',) and events[-1].status=='partial'
    assert next(e for e in events if e.type=='error').code=='transport-error'


def test_session_capacity_never_publishes_an_unmanaged_variant_and_keeps_usable_a():
    source=controlled_catalogue();store=DesignSessionStore(source,capacity=1)
    events,provider,_=run([selection('wall-north'),selection('wall-south'),selection('wall-east')],source=source,store=store)
    variants=[e for e in events if e.type=='variant']
    assert [v.variant for v in variants]==['A'] and len(provider.calls)==2
    assert store.current(variants[0].result.design.swap.sessionId).status=='current'
    assert next(e for e in events if e.type=='error').code=='mutation-session-unavailable'
    assert events[-1].status=='partial' and events[-1].available==('A',)
    # The already-full registry also denies publication of a new batch's A.
    second,provider,_=run([selection()],source=source,store=store)
    assert not any(e.type=='variant' for e in second) and len(provider.calls)==1
    assert second[-1].status=='failed' and second[-1].available==()


def test_request_ceiling_never_emits_a_late_terminal_event():
    now=[0.0];control=BatchControl(clock=lambda:now[0],deadline_at=270,request_deadline_at=300)
    class Request:
        async def is_disconnected(self): return False
    def events():
        yield ShellEvent(generationId=control.generation_id,room=ROOM)
        now[0]=301
        yield CompleteEvent(generationId=control.generation_id,status='failed',available=(),reason='timeout',providerCalls=0,usage={'known':False})
    async def collect():
        response=stream_response(Request(),events,control)
        return [json.loads(line) async for line in response.body_iterator]
    result=asyncio.run(collect())
    assert [e['type'] for e in result]==['shell'] and control.cancelled.is_set()


def test_request_ceiling_also_cancels_a_stalled_asgi_send():
    async def exercise():
        control=BatchControl(request_deadline_at=time.monotonic()+.05)
        async def body(): yield 'pending\n'
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        async def send(_message): await asyncio.sleep(1)
        response=DeadlineStreamingResponse(body(),control=control,media_type='application/x-ndjson')
        started=time.monotonic()
        await response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send)
        assert time.monotonic()-started < .5 and control.cancelled.is_set()
    asyncio.run(exercise())


def test_signature_ignores_instance_identity_order_metadata_and_full_rotations_but_keeps_multiplicity():
    events,_,_ = run([selection()]*3)
    design = next(e.result.design for e in events if e.type=='variant')
    signature = solved_signature(design)
    def changed(placements): return design.model_copy(update={'placements':tuple(placements)})
    shifted_ids = [p.model_copy(update={'instanceId':'other-'+str(i), 'yaw':p.yaw+2*pi}) for i,p in enumerate(reversed(design.placements))]
    assert solved_signature(changed(shifted_ids))==signature
    p = design.placements[0]
    close = p.model_copy(update={'position':(p.position[0]+.004,p.position[1],p.position[2]),'yaw':p.yaw+pi/180*.4})
    assert solved_signature(changed([close,*design.placements[1:]]))==signature
    for next_p in [p.model_copy(update={'position':(p.position[0]+.006,p.position[1],p.position[2])}),p.model_copy(update={'yaw':p.yaw+pi/180*.6}),p.model_copy(update={'productId':'different'})]:
        assert solved_signature(changed([next_p,*design.placements[1:]]))!=signature
    assert solved_signature(changed([*design.placements,p]))!=signature


@pytest.mark.parametrize('finish,expected', [(269.0,1),(270.0,0),(271.0,0)])
def test_work_cutoff_checks_after_provider_and_before_solve_or_publication(finish,expected):
    now=[0.0]
    class ClockProvider(TranscriptProvider):
        def generate(self, **kwargs):
            result=super().generate(**kwargs);now[0]=finish;return result
    control=BatchControl(clock=lambda:now[0],deadline_at=270)
    provider=ClockProvider([selection(),ProviderCallError('timeout','controlled')])
    events,_,store=run(provider,control=control)
    assert len([e for e in events if e.type=='variant'])==expected
    if expected==0:
        assert len(provider.calls)==1 and not store._records
        assert events[-1].reason=='timeout'


def test_cancellation_after_provider_never_solves_or_publishes(monkeypatch):
    import api.live_generation as live
    control=BatchControl()
    class Cancel(TranscriptProvider):
        def generate(self,**kwargs):
            result=super().generate(**kwargs);control.cancelled.set();return result
    original=live.ArrangementSession.submit
    def forbidden(*args): raise AssertionError('solve started after cancellation')
    monkeypatch.setattr(live.ArrangementSession,'submit',forbidden)
    events,p,store=run(Cancel([selection()]),control=control)
    assert len(p.calls)==1 and not store._records and not any(e.type=='variant' for e in events)


@pytest.mark.parametrize('finish', [270,299,301])
def test_registration_overrun_revokes_unpublished_session(finish):
    now=[269.0];control=BatchControl(clock=lambda:now[0],deadline_at=270)
    source=controlled_catalogue()
    class SlowStore(DesignSessionStore):
        def register(self,*args,**kwargs):
            result=super().register(*args,**kwargs);now[0]=finish;return result
    store=SlowStore(source)
    events,_,_=run([selection()],source=source,control=control,store=store)
    assert not store._records and not any(e.type=='variant' for e in events)
    assert events[-1].reason=='timeout'


def test_stopping_after_emitted_a_keeps_its_session():
    source=controlled_catalogue();store=DesignSessionStore(source);control=BatchControl()
    iterator=variant_events(source,REQUEST,ROOM,store,provider=TranscriptProvider([selection()]),control=control)
    while (event:=next(iterator)).type!='variant': pass
    sid=event.result.design.swap.sessionId
    # Resume delivery acknowledgement before cancellation of later work.
    assert next(iterator).type=='progress'
    control.cancelled.set()
    assert list(iterator)==[] and store.current(sid).status=='current'


def test_private_stream_denials_revision_and_authority_expiry_are_sanitized(harness):
    service,provider,client=harness;c=confirmed(client)
    path=f"/api/captures/{c['id']}/variants";body={'expectedRevision':c['revision'],'referenceId':'ref-01'}
    for headers,status in [(B,404),({},401)]:
        assert client.post(path,json=body,headers=headers).status_code==status
    assert client.post(path,json={**body,'expectedRevision':c['revision']-1},headers=A).status_code==409
    releases=[]
    user=service.repository.user
    def track(*args,**kwargs):
        if len(args)>1 and args[1]=='release': releases.append(args)
        return user(*args,**kwargs)
    service.repository.user=track
    provider.after=lambda:service.rows[c['id']].update(expiresAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    response=client.post(path,json=body,headers=A)
    events=[json.loads(line) for line in response.text.splitlines()]
    assert events[0]['type']=='shell' and not any(e['type']=='variant' for e in events)
    assert any(e['type']=='error' and e['invalidated'] for e in events)
    assert 'Controlled failure' not in response.text and len(releases)==1


def test_private_expiry_during_session_registration_prevents_emission(harness,monkeypatch):
    service,provider,client=harness;c=confirmed(client)
    register=DesignSessionStore.register
    registered=[];releases=[];leases=[]
    user=service.repository.user
    def track(principal,action,cid=None,revision=None,payload=None):
        if action=='release': releases.append((cid,revision,payload['lease']))
        result=user(principal,action,cid,revision,payload)
        if action=='lease': leases.append((cid,revision,result['lease']))
        return result
    service.repository.user=track
    def expire(store,*args,**kwargs):
        result=register(store,*args,**kwargs)
        registered.append((store,result.swap.sessionId))
        service.rows[c['id']].update(expiresAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        return result
    monkeypatch.setattr(DesignSessionStore,'register',expire)
    response=client.post(f"/api/captures/{c['id']}/variants",json={'expectedRevision':c['revision'],'referenceId':'ref-01'},headers=A)
    events=[json.loads(line) for line in response.text.splitlines()]
    assert not any(e['type']=='variant' for e in events) and any(e['type']=='error' for e in events)
    assert len(leases)==1 and releases==leases
    assert registered and all(sid not in store._records for store,sid in registered)
    # The existing mock can retain a lease after expired admission rejects release.
    # It is unusable: even the exact owner/revision/token cannot assert authority.
    from api.capture_auth import CaptureError, CapturePrincipal
    principal=CapturePrincipal(owner_id=service.owners[c['id']],token=A['Authorization'][7:])
    with pytest.raises(CaptureError):
        service.repository.assert_lease(principal,c['id'],c['revision'],leases[0][2],c['roomHash'])


@pytest.mark.parametrize('revoked',[False,True])
def test_queued_work_cutoff_revalidates_authority_before_retaining_a(revoked):
    from threading import current_thread
    result=next(e.result for e in run([selection()]*3)[0] if e.type=='variant')
    cutoff=[False];checks=[];invalidations=[]
    def authority():
        if cutoff[0]:
            checks.append(True)
            if revoked: raise RuntimeError('controlled revoked authority')
    control=BatchControl(clock=lambda:270 if cutoff[0] and current_thread().name!='variant-stream' else 0,
                         deadline_at=270,request_deadline_at=300,authority=authority)
    def events():
        yield ShellEvent(generationId=control.generation_id,room=ROOM)
        yield VariantEvent(generationId=control.generation_id,variant='A',signature='a'*64,result=result)
        cutoff[0]=True
        yield ProgressEvent(generationId=control.generation_id,variant='B',stage='selecting')
    class Request:
        async def is_disconnected(self): return False
    async def collect():
        return [json.loads(line) async for line in stream_response(Request(),events,control,invalidate=lambda:invalidations.append(True)).body_iterator]
    output=asyncio.run(collect())
    assert checks
    assert output[-1]['available']==([] if revoked else ['A'])
    assert output[-1]['reason']==('generation-failed' if revoked else 'timeout')
    assert bool(invalidations)==revoked
    assert any(e['type']=='error' and e['invalidated'] for e in output)==revoked


def test_private_structured_error_is_withheld_after_worker_authority_loss():
    from api.live_generation import LiveGenerationFailure
    # Real supported no-fit carries server-derived Zones, not a fabricated field.
    source=controlled_catalogue()
    small=rectangular_room_shell('controlled-private-small',1,1,2.7)
    failure=__import__('api.live_generation',fromlist=['generate_for_room']).generate_for_room(source,REQUEST,room=small,provider=TranscriptProvider([selection()]*3))
    assert isinstance(failure,LiveGenerationFailure) and failure.designFailure.zones
    revoked=[False];checks=[];invalidations=[]
    def authority():
        checks.append(revoked[0])
        if revoked[0]: raise RuntimeError('controlled access loss')
    control=BatchControl(authority=authority)
    def events():
        yield ShellEvent(generationId=control.generation_id,room=small)
        authority();revoked[0]=True
        yield ErrorEvent(generationId=control.generation_id,code=failure.code,detail=failure.detail,failure=failure)
    class Request:
        async def is_disconnected(self): return False
    async def collect():
        return [json.loads(line) async for line in stream_response(Request(),events,control,invalidate=lambda:invalidations.append(True)).body_iterator]
    output=asyncio.run(collect())
    assert any(checks) and invalidations
    assert [e['type'] for e in output]==['shell','error','complete']
    assert output[1]['invalidated'] and output[1]['failure'] is None
    assert output[-1]['available']==[]


def test_private_authority_changes_between_registration_and_wire_delivery(harness,monkeypatch):
    service,provider,client=harness;c=confirmed(client)
    register=DesignSessionStore.register
    registered=[];checks=[]
    def observe(store,*args,**kwargs):
        design=register(store,*args,**kwargs)
        registered.append((store,design.swap.sessionId))
        def expire_at_wire(_service,row):
            checks.append(True)
            if len(checks)==2:
                row.update(expiresAt=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        service.on_assert=expire_at_wire
        return design
    monkeypatch.setattr(DesignSessionStore,'register',observe)
    response=client.post(f"/api/captures/{c['id']}/variants",json={'expectedRevision':c['revision'],'referenceId':'ref-01'},headers=A)
    events=[json.loads(line) for line in response.text.splitlines()]
    assert len(checks)==2 and registered
    assert not any(e['type']=='variant' for e in events)
    assert events[-1]['type']=='complete' and events[-1]['available']==[]
    assert any(e['type']=='error' and e['invalidated'] for e in events)
    assert all(sid not in store._records for store,sid in registered)


def test_cache_transport_counters_cost_reservation_and_unknowns(tmp_path):
    requests=[]
    def handle(request):
        body=json.loads(request.content);requests.append((request.url.path,body))
        if request.url.path.endswith('count_tokens'):
            assert 'max_tokens' not in body
            return httpx.Response(200,json={'input_tokens':100})
        return httpx.Response(200,json={'model':'claude-opus-5','stop_reason':'end_turn',
            'usage':{'input_tokens':10,'output_tokens':5,'cache_creation_input_tokens':100,'cache_read_input_tokens':200},
            'content':[{'type':'text','text':'{"intents":[]}'}]})
    settings=ProviderSettings('controlled','workspace',5,tmp_path/'ledger.json')
    provider=AnthropicProvider(settings,client=httpx.Client(transport=httpx.MockTransport(handle)))
    messages=[{'role':'user','content':[{'type':'text','text':'stable','cache_control':{'type':'ephemeral'}}]}]
    reply=provider.generate(prompt_text='stable',image_media_type='image/jpeg',image_base64=CONTROLLED_IMAGE_BASE64,output_schema=_output_schema(),deadline_at=__import__('time').monotonic()+30,conversation=messages)
    assert all(r[1]['messages']==messages for r in requests)
    assert reply.usage.costUsd==pytest.approx((10+125+20)*5/1e6+5*25/1e6)
    ledger=json.loads(settings.accounting_path.read_text())
    assert ledger['reservations'][0]['maximumUsd']==pytest.approx(1+.2048)
    assert reply.usage.cacheCreationInputTokens==100 and reply.usage.cacheReadInputTokens==200
    assert _usage_summary([reply.usage,None]).known is False
    unknown=provider._usage_from_payload({'usage':{'input_tokens':10,'output_tokens':5}},cache_enabled=True)
    assert unknown.cacheReadInputTokens is None and unknown.costKnown is False
    assert _usage_summary([unknown]).costUsd is None
    reservation,_=provider.ledger.reserve(100,cache_enabled=True)
    before=json.loads(settings.accounting_path.read_text())['committedUsd']
    provider.ledger.settle(reservation,unknown)
    assert json.loads(settings.accounting_path.read_text())['committedUsd']==before
    zero=provider._usage_from_payload({'usage':{'input_tokens':10,'output_tokens':5,'cache_creation_input_tokens':0,'cache_read_input_tokens':0}},cache_enabled=True)
    assert zero.costKnown and _usage_summary([zero]).cacheReadInputTokens==0


def test_cancellation_during_count_tokens_prevents_messages_dispatch(tmp_path):
    from api.generation_context import work_scope
    control=BatchControl();paths=[]
    def handle(request):
        paths.append(request.url.path)
        assert request.url.path.endswith('count_tokens')
        control.cancelled.set()
        return httpx.Response(200,json={'input_tokens':100})
    provider=AnthropicProvider(ProviderSettings('controlled','workspace',5,tmp_path/'ledger.json'),client=httpx.Client(transport=httpx.MockTransport(handle)))
    from api.variants import BatchStopped
    with work_scope(control.check),pytest.raises(BatchStopped):
        provider.generate(prompt_text='controlled',image_media_type='image/jpeg',image_base64=CONTROLLED_IMAGE_BASE64,output_schema=_output_schema(),deadline_at=time.monotonic()+30)
    assert len(paths)==1 and paths[0].endswith('count_tokens')
    assert not provider.settings.accounting_path.exists()
