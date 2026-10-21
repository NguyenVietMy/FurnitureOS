"""Controlled geometry expectations are hand-calculated, never solver snapshots."""
from copy import deepcopy
import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from api.catalogue import catalogue
from api.catalogue.contract import CatalogueEntry, CatalogueQuery
from api.catalogue.static import StaticCatalogue
from api.domain import rectangular_room_shell, l_shaped_room_shell, footprint_of, resolve_design
from api.live_generation import LiveGenerationRequest, generate_for_room, frozen_generation_configuration
from api.main import create_app
from api.models import AccessRegion, Dimensions, RoomShell, DesignRequest
from api.provider import ProviderCallError, ProviderReply, MODEL_ID
from api.room_policy import LIVING_POLICY
from api.zones import derive_zones


def controlled_catalogue():
    # Deliberately synthetic footprints; actual new Mesh integration is separate.
    template = catalogue.get('chair-rivet-slade-swivel-graphite')
    entries = []
    for pid, cat, w, h, d, rooms in [
        ('controlled-sofa', 'sofa', 2, .9, 1, ('living-room',)),
        ('controlled-sofa-other', 'sofa', 2, .9, 1, ('living-room',)),
        ('controlled-wrong-room-sofa', 'sofa', 2, .9, 1, ('bedroom',)),
        ('controlled-table', 'table', 1, .4, .5, ('living-room',)),
        ('controlled-table-other', 'table', 1, .4, .5, ('living-room',)),
        ('controlled-chair', 'chair', .8, 1, .8, ('living-room',)),
        ('controlled-chair-other', 'chair', .8, 1, .8, ('living-room',)),
        ('controlled-chair-extra', 'chair', .8, 1, .8, ('living-room',)),
        ('controlled-wrong-room-chair', 'chair', .8, 1, .8, ('bedroom',)),
        ('controlled-rug', 'rug', 2, .02, 2, ('living-room',)),
        ('controlled-lamp', 'lamp', .3, 1.5, .3, ('living-room',)),
    ]:
        p = template.model_copy(update=dict(id=pid, category=cat, roomTypes=rooms,
            dimensionsM=Dimensions(widthM=w, heightM=h, depthM=d),
            placementClass='floor-covering' if cat == 'rug' else 'floor-standing',
            wallContactFaces=('back',) if cat in ('sofa', 'chair') else (),
            accessRegions=(AccessRegion(face='front',depthM=.6,required=True,purpose='approach'),) if cat in ('sofa','table','chair') else ()))
        entries.append(CatalogueEntry(p, ('style-01',)))
    return StaticCatalogue('CONTROLLED-synthetic-living-v1', entries)


class ControlledProvider:
    def __init__(self, outcomes=None, *, floating=True, gap=.8):
        self.calls = []
        self.outcomes = outcomes
        self.floating = floating
        self.gap = gap

    def generate(self, **kwargs):
        context = json.loads(kwargs['prompt_text'])
        self.calls.append(context)
        if self.outcomes is not None:
            result = self.outcomes[min(len(self.calls)-1,len(self.outcomes)-1)]
            if isinstance(result, Exception):
                raise result
            return result if isinstance(result, ProviderReply) else ProviderReply(payload=deepcopy(result),model=MODEL_ID,stop_reason='end_turn',usage=None,latency_ms=1)
        sofa = dict(id='anchor-sofa',productId='controlled-sofa',kind='in_zone',zoneId=max(context['offeredZones'],key=lambda z:(z['bounds']['maxX']-z['bounds']['minX'])*(z['bounds']['maxZ']-z['bounds']['minZ']))['id']) if self.floating else dict(id='anchor-sofa',productId='controlled-sofa',kind='centred_on',wallId='wall-north',face='back')
        return ProviderReply(payload={'intents':[sofa,dict(id='anchor-table',productId='controlled-table',kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=self.gap),chair_intent()]},model=MODEL_ID,stop_reason='end_turn',usage=None,latency_ms=1)


def chair_intent():
    return dict(id='anchor-chair',productId='controlled-chair',kind='adjacent_to',referenceId='anchor-sofa',side='left',gapM=.6)


def run(provider, room=None, source=None):
    return generate_for_room(source or controlled_catalogue(), LiveGenerationRequest(roomType='living-room',referenceId='ref-01'), room=room or rectangular_room_shell('hand-living',8,8,2.7), provider=provider)


def test_hand_calculated_seating_zone_identity_and_floating_poses():
    room = rectangular_room_shell('hand-living',8,8,2.7)
    offer = derive_zones(room,'living-room')
    assert len(offer.zones) == 1
    assert offer.zones[0].id == 'seating-v1-' + sha256(b'seating-v1|hand-living|-4,-4,4,4').hexdigest()[:12]
    assert offer.zones[0].bounds.model_dump() == dict(minX=-4,minZ=-4,maxX=4,maxZ=4)
    provider = ControlledProvider()
    result = run(provider,room)
    assert result.status == 'solved', result
    sofa, table, chair = result.design.placements
    assert sofa.position == (0,0,0) and sofa.yaw == 0 and not sofa.wallContacts
    assert table.position == pytest.approx((0,0,1.55)) and table.yaw == 0 and not table.wallContacts
    assert chair.position == pytest.approx((-2,0,0)) and chair.yaw == 0 and not chair.wallContacts
    assert min(p[1] for p in footprint_of(controlled_catalogue().get('controlled-table'),(table.position[0],table.position[2]),table.yaw).corners) == pytest.approx(1.3)
    assert result.design.circulation.status == 'clear'
    assert result.roomType == 'living-room'
    assert 'bed' not in json.dumps(provider.calls[0]).lower()


def test_wall_backed_group_uses_same_access_and_circulation():
    result = run(ControlledProvider(floating=False))
    assert result.status == 'solved',result
    sofa, table, chair = result.design.placements
    assert sofa.position == pytest.approx((0,0,-3.5))
    assert table.position == pytest.approx((0,0,-1.95))
    assert sofa.wallContact.wallId == 'wall-north'
    assert result.design.circulation.status == 'clear'


def test_predeclared_six_metre_trio_oracle_and_access_rejection_keep_required_chair():
    entries=[]
    for product in controlled_catalogue().list():
        if product.category=='sofa':product=product.model_copy(update={'dimensionsM':Dimensions(widthM=2,heightM=.9,depthM=.9)})
        if product.category=='table':product=product.model_copy(update={'dimensionsM':Dimensions(widthM=1,heightM=.4,depthM=.6)})
        entries.append(CatalogueEntry(product,('style-01',)))
    source=StaticCatalogue('CONTROLLED-predeclared-six-metre-trio',entries)
    room=rectangular_room_shell('predeclared-six-metre-trio',6,6,2.7)
    result=run(ControlledProvider(gap=.6),room,source)
    assert result.status=='solved',result
    poses={p.instanceId:p for p in result.design.placements}
    for identity,expected in {'anchor-sofa':(0,0,0),'anchor-table':(0,0,1.35),'anchor-chair':(-2,0,0)}.items():
        assert poses[identity].position==pytest.approx(expected)
        assert poses[identity].yaw==0 and not poses[identity].wallContacts
    assert result.design.circulation.status=='clear'
    provider=ControlledProvider(gap=.59)
    failure=run(provider,room,source)
    assert failure.status=='failed' and failure.code=='no-valid-design' and failure.providerCalls==3
    assert failure.designFailure is not None
    assert all(not a.droppedRequestIds for a in failure.designFailure.arrangementHistory.attempts)
    assert all('anchor-chair' in {r['requestId'] for r in c['rules']['selectionScope']['required']} for c in provider.calls)


def test_flanking_optional_partner_cannot_drop_the_required_chair():
    source=controlled_catalogue()
    entries=[CatalogueEntry(p.model_copy(update={'dimensionsM':Dimensions(widthM=20,heightM=1,depthM=20)}) if p.id=='controlled-chair-extra' else p,('style-01',)) for p in source.list()]
    room=rectangular_room_shell('required-flanking-chair',8,8,2.7)
    payload={'intents':[
        dict(id='anchor-sofa',productId='controlled-sofa',kind='in_zone',zoneId=derive_zones(room,'living-room').zones[0].id),
        dict(id='anchor-table',productId='controlled-table',kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=.8),
        dict(id='anchor-chair',productId='controlled-chair',kind='flanking',referenceId='anchor-sofa',side='left',gapM=.6),
        dict(id='optional-chair',productId='controlled-chair-extra',kind='flanking',referenceId='anchor-sofa',side='right',gapM=.6)]}
    failure=run(ControlledProvider([payload]),room,StaticCatalogue('CONTROLLED-protected-flanking',entries))
    assert failure.status=='failed' and failure.code=='no-valid-design' and failure.providerCalls==3
    history=failure.designFailure.arrangementHistory.attempts
    assert [a.stage for a in history[:3]]==['initial','repair','repair']
    assert not any(a.stage=='drop' for a in history)
    skipped=[a for a in history if a.stage=='skipped-drop']
    assert len(skipped)==1 and skipped[0].droppedRequestIds==('anchor-chair','optional-chair')
    assert skipped[0].outcome=='skipped' and skipped[0].attemptedCandidates==0
    assert 'anchor-chair' in skipped[0].detail


def test_missing_matching_chair_style_prevents_provider_transport():
    source=StaticCatalogue('CONTROLLED-mismatched-chair-style',[CatalogueEntry(p,('style-02',) if p.category=='chair' else ('style-01',)) for p in controlled_catalogue().list()])
    provider=ControlledProvider()
    failure=run(provider,source=source)
    assert failure.status=='failed' and failure.code=='eligible-catalogue-error' and not provider.calls


def test_sofa_window_exclusion_uses_hand_placed_wall_contact():
    data=rectangular_room_shell('window',8,8,2.7).model_dump(mode='json')
    data['openings']=[dict(id='low-window',kind='window',wallId='wall-north',offsetAlongWallM=0,widthM=2,bottomM=.2,heightM=1,clearanceDepthM=.5)]
    request=DesignRequest(room=RoomShell.model_validate(data),intents=[dict(id='sofa',productId='controlled-sofa',kind='centred_on',wallId='wall-north',face='back')])
    result=resolve_design(controlled_catalogue(),request)
    assert result.status=='failed' and result.reason=='opening-exclusion'
    assert 'low-window' in result.detail


def test_access_safe_gap_can_still_fail_complete_door_circulation():
    from api.design import object_intent_fixture_room
    provider=ControlledProvider(gap=.6)
    r=run(provider,object_intent_fixture_room())
    assert r.status=='failed' and r.code=='no-valid-design'
    assert r.designFailure.limitingConstraint.code=='CIRCULATION_BLOCKED'
    assert r.designFailure.limitingConstraint.exhaustive is False
    assert all(not a.droppedRequestIds for a in r.designFailure.arrangementHistory.attempts)


@pytest.mark.parametrize('wall,sofa_expected,table_expected,yaw', [
    ('wall-north',(0,0,-3.5),(0,0,-1.95),0),
    ('wall-south',(0,0,3.5),(0,0,1.95),3.141592653589793),
    ('wall-east',(3.5,0,0),(1.95,0,0),-1.5707963267948966),
    ('wall-west',(-3.5,0,0),(-1.95,0,0),1.5707963267948966),
])
def test_cardinal_front_is_target_local_and_keeps_required_access(wall,sofa_expected,table_expected,yaw):
    payload={'intents':[dict(id='anchor-sofa',productId='controlled-sofa',kind='centred_on',wallId=wall,face='back'),dict(id='anchor-table',productId='controlled-table',kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=.8),chair_intent()]}
    result=run(ControlledProvider([payload]))
    assert result.status=='solved',result
    assert result.design.placements[0].position==pytest.approx(sofa_expected)
    assert result.design.placements[1].position==pytest.approx(table_expected)
    assert abs(abs(result.design.placements[0].yaw)-abs(yaw))<1e-8


def test_optional_drop_order_is_rug_lamp_chair_despite_request_id_order():
    source=controlled_catalogue()
    entries=[]
    for p in source.list():
        if p.id in ('controlled-rug','controlled-lamp','controlled-chair-extra'):
            p=p.model_copy(update={'dimensionsM':Dimensions(widthM=20,heightM=1,depthM=20)})
        entries.append(CatalogueEntry(p,('style-01',)))
    source=StaticCatalogue('CONTROLLED-drop-order',entries)
    room=rectangular_room_shell('drop',8,8,2.7)
    zone=derive_zones(room,'living-room').zones[0].id
    payload={'intents':[dict(id='anchor-sofa',productId='controlled-sofa',kind='in_zone',zoneId=zone),dict(id='anchor-table',productId='controlled-table',kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=.8),chair_intent(),*[dict(id=i,productId=p,kind='in_zone',zoneId=zone) for i,p in [('z-rug','controlled-rug'),('a-lamp','controlled-lamp'),('b-chair','controlled-chair-extra')]]]}
    r=run(ControlledProvider([payload]),room,source)
    assert r.status=='solved',r
    history=r.design.arrangementHistory.attempts
    assert [a.stage for a in history[:3]]==['initial','repair','repair']
    assert [a.droppedRequestIds for a in history[3:]]==[('z-rug',),('a-lamp','z-rug'),('a-lamp','b-chair','z-rug')]
    assert {p.instanceId for p in r.design.placements}==LIVING_POLICY.anchor_ids


@pytest.mark.parametrize('mutation', ['missing-sofa','missing-table','missing-chair','duplicate','coordinate','unknown-zone','wrong-room','third-chair','unknown-product','anchor-category'])
def test_selection_rejections_have_three_call_ceiling_without_drops(mutation):
    room=rectangular_room_shell('hand-living',8,8,2.7)
    payload={'intents':[dict(id='anchor-sofa',productId='controlled-sofa',kind='in_zone',zoneId=derive_zones(room,'living-room').zones[0].id),dict(id='anchor-table',productId='controlled-table',kind='adjacent_to',referenceId='anchor-sofa',side='front',gapM=.6),chair_intent()]}
    if mutation=='missing-sofa':payload['intents'].pop(0)
    if mutation=='missing-table':payload['intents'].pop(1)
    if mutation=='missing-chair':payload['intents'].pop(2)
    if mutation=='duplicate':payload['intents'].append(payload['intents'][0])
    if mutation=='coordinate':payload['intents'][0]['position']=[0,0,0]
    if mutation=='unknown-zone':payload['intents'][0]['zoneId']='invented'
    if mutation=='wrong-room':payload['intents'].append(dict(id='chair',productId='controlled-wrong-room-chair',kind='in_zone',zoneId=derive_zones(room,'living-room').zones[0].id))
    if mutation=='third-chair':payload['intents'] += [dict(id=f'chair-{i}',productId='controlled-chair',kind='in_zone',zoneId=derive_zones(room,'living-room').zones[0].id) for i in range(2)]
    if mutation=='unknown-product':payload['intents'][0]['productId']='invented'
    if mutation=='anchor-category':payload['intents'][1]['productId']='controlled-chair'
    p=ControlledProvider([payload]);r=run(p,room)
    assert r.status=='failed' and r.code=='selection-correction-exhausted' and r.providerCalls==3
    assert len(r.selectionRejections)==3
    assert r.designFailure is None


@pytest.mark.parametrize('gap',[.59,0,-.1])
def test_front_access_is_not_reduced_to_force_fit(gap):
    r=run(ControlledProvider(gap=gap))
    assert r.status=='failed' and r.providerCalls==3
    if gap < 0:
        assert r.code=='selection-correction-exhausted' and r.designFailure is None
    else:
        assert r.code=='no-valid-design'
        assert all(not a.droppedRequestIds for a in r.designFailure.arrangementHistory.attempts)


@pytest.mark.parametrize('index,replacement', [(0,'controlled-sofa-other'),(1,'controlled-table-other'),(2,'controlled-chair-other')])
def test_required_anchor_identity_stays_locked_through_repairs(index,replacement):
    p=ControlledProvider(gap=0)
    class Replacement(ControlledProvider):
        def generate(self,**kwargs):
            reply=p.generate(**kwargs)
            self.calls=p.calls
            if len(p.calls)>1: reply.payload['intents'][index]['productId']=replacement
            return reply
    r=run(Replacement())
    assert r.code=='selection-correction-exhausted'
    assert [e.code for e in r.selectionRejections]==['repair-anchor-error']*2
    assert 'requiredAnchors' in p.calls[1]['immutableRepairContract']
    assert 'bed' not in json.dumps(p.calls[1]).lower()


@pytest.mark.parametrize('room',[rectangular_room_shell('small',1,1,2.7),l_shaped_room_shell('tiny-l',2,2,1,1,2.7)])
def test_small_rectangle_and_concave_room_report_no_fit_with_all_three_anchors(room):
    r=run(ControlledProvider(),room)
    assert r.status=='failed' and r.code=='no-valid-design'
    assert r.providerCalls==3 and not any(a.droppedRequestIds for a in r.designFailure.arrangementHistory.attempts)


def test_unpromoted_production_and_wrong_style_make_zero_provider_calls(monkeypatch, tmp_path):
    from api.catalogue.providers.abo import abo_entries, catalogue_version
    from api.catalogue.providers import living
    monkeypatch.setattr(living, 'REVIEWED_PATH', tmp_path/'ABSENT-reviewed.json')
    base = abo_entries()
    absent = living.reviewed_entries(base)
    assert absent == base and len(absent) == 20
    unpromoted = StaticCatalogue(catalogue_version(), absent)
    for source,ref in [(unpromoted,'ref-01'),(controlled_catalogue(),'ref-02')]:
        p=ControlledProvider()
        r=generate_for_room(source,LiveGenerationRequest(roomType='living-room',referenceId=ref),room=rectangular_room_shell('room',8,8,2.7),provider=p)
        assert r.status=='failed' and r.code=='eligible-catalogue-error' and not p.calls


def test_reused_product_style_tags_are_scoped_to_matching_room_type():
    chair=catalogue.get('chair-rivet-slade-swivel-graphite').model_copy(update={'roomTypes':('bedroom','living-room')})
    source=StaticCatalogue('CONTROLLED-room-scoped-tags',[CatalogueEntry(chair,('style-01','style-03'),(('bedroom',('style-01',)),('living-room',('style-03',))))])
    assert source.list(CatalogueQuery(room_type='bedroom',private_style_id='style-01'))==(chair,)
    assert source.list(CatalogueQuery(room_type='living-room',private_style_id='style-03'))==(chair,)
    assert source.list(CatalogueQuery(private_style_id='style-03'))==(chair,)
    assert not source.list(CatalogueQuery(room_type='living-room',private_style_id='style-01'))
    assert not source.list(CatalogueQuery(room_type='bedroom',private_style_id='style-03'))


def test_shared_http_explicit_type_legacy_boundary_and_wrong_room_swap():
    p=ControlledProvider()
    with TestClient(create_app(catalogue_source=controlled_catalogue(),generation_provider=p)) as client:
        for body in ({'referenceId':'ref-01'},{'roomType':'office','referenceId':'ref-01'}):
            assert client.post('/api/live-design/generate',json=body).status_code==422
        assert client.post('/api/live-bedroom/generate',json={'roomType':'living-room','referenceId':'ref-01'}).status_code==422
        r=client.post('/api/live-design/generate',json={'roomType':'living-room','referenceId':'ref-01'}).json()
        assert r['status']=='solved' and r['roomType']=='living-room'
        session=r['design']['swap']['sessionId']
        swapped=client.post('/api/swaps',json=dict(sessionId=session,expectedVersion=1,instanceId='anchor-sofa',replacementProductId='controlled-wrong-room-sofa')).json()
        assert swapped['status']=='rejected' and swapped['code']=='room-type-incompatible'
        candidates=client.get(f'/api/swaps/{session}/candidates?expectedVersion=1&instanceId=anchor-sofa').json()
        assert all(e['product']['id']!='controlled-wrong-room-sofa' for e in candidates['candidates'])
        region=client.get(f'/api/nudges/{session}/region?expectedVersion=1&instanceId=anchor-table').json()
        assert region['status'] in ('available','unavailable'),region
        version=1
        if region['status']=='available':
            vertex=max(region['polygon'],key=lambda p:p[0]*p[0]+p[1]*p[1])
            target=[region['origin'][i]+vertex[i]*.05 for i in (0,1)]
            nudged=client.post('/api/nudges',json=dict(sessionId=session,expectedVersion=1,instanceId='anchor-table',regionId=region['regionId'],target=target)).json()
            assert nudged['status']=='accepted' and nudged['design']['circulation']['status']=='clear'
            version=2
        else:
            assert region['detail'] and client.get(f'/api/swaps/{session}').json()['version']==1
        changed=client.post('/api/swaps',json=dict(sessionId=session,expectedVersion=version,instanceId='anchor-sofa',replacementProductId='controlled-sofa-other')).json()
        assert changed['status']=='accepted' and changed['design']['circulation']['status']=='clear'
        assert client.get('/api/live-design/config').status_code==422
        assert client.get('/api/live-design/config?roomType=living-room').json()['roomType']=='living-room'
    config=frozen_generation_configuration(controlled_catalogue(),'living-room')
    assert config['protectedAnchorIds']==['anchor-chair','anchor-sofa','anchor-table']
    assert config['provider']['selectionScope']['maximumRequests']==6
    assert config['provider']['selectionCorrectionCalls']==3
    assert config['provider']['overallDeadlineSeconds']>0
    assert config['solver']['maxCandidatesPerSolve']==256
    assert config['providerOutputSchemaSha256'] and config['promptContractSha256ByReference']
    assert 'bed' not in json.dumps(config['provider']).lower()
