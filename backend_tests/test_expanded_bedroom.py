"""Controlled policy/authority proof, never provider aesthetics or curation."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from api.catalogue import catalogue, CatalogueEntry, StaticCatalogue
from api.domain import rectangular_room_shell, l_shaped_room_shell
from api.live_generation import generate_for_room, LiveGenerationRequest, candidate_window, _validated_selection, SelectionRejected, _wall_capability_map
from api.room_policy import BEDROOM_POLICY
from api.zones import derive_zones
from backend_tests.test_live_generation import TranscriptProvider, selection
from backend_tests.test_captures import A, collect, save_reviewed
from backend_tests.test_l_shaped import collect_l, confirm_l
from backend_tests.capture_transport import ControlledSupabase
from api.capture_auth import SupabaseAuth
from api.main import create_app
from backend_tests.catalogue_fixtures import original_published_catalogue


@pytest.mark.parametrize('room_type', ['bedroom', 'living-room'])
def test_candidate_window_diagnostic_describes_v2_pair_preference_without_new_authority(room_type):
    from api.live_generation import frozen_generation_configuration
    window = frozen_generation_configuration(catalogue, room_type=room_type)['candidateWindow']
    assert window['version'] == 'room-style-category-window-v2-24'
    assert window['maximumProducts'] == 24 and window['fullCatalogueForSwaps'] is True
    assert 'category round-robin' in window['ordering']
    assert 'lowest combined footprint bed pair' in window['ordering']
    assert 'centimetre-rounded depth' in window['ordering']
    assert 'remaining beds and other categories by sorted Product identity' in window['ordering']


def source():
    # Actual published Mesh dimensions, explicit controlled eligibility override.
    return StaticCatalogue('CONTROLLED-published-mesh-bedroom-policy', [CatalogueEntry(p,('style-01',)) for p in original_published_catalogue().list() if 'bedroom' in p.roomTypes])


def furnished():
    return selection(
        dict(id='anchor-bed',productId='bed-prudence-tufted-queen-natural',kind='centred_on',wallId='wall-north',face='back'),
        dict(id='left',productId='nightstand-alkove-hayes-wild-oak',kind='flanking',referenceId='anchor-bed',side='left',gapM=.7),
        dict(id='right',productId='nightstand-alkove-hayes-wild-oak',kind='flanking',referenceId='anchor-bed',side='right',gapM=.7),
        dict(id='chair',productId='chair-stone-beam-deco-wingback-walnut',kind='facing',referenceId='anchor-bed',gapM=.8),
        dict(id='rug',productId='rug-rivet-arrow-black-ivory',kind='adjacent_to',referenceId='anchor-bed',side='front',gapM=-1.6),
        dict(id='lamp',productId='lamp-rivet-harper-brass',kind='adjacent_to',referenceId='left',side='left',gapM=.4),
        dict(id='dresser',productId='dresser-stylistics-campaign-white',kind='centred_on',wallId='wall-south',face='back'),
        dict(id='wardrobe',productId='wardrobe-ravenna-verona-mirror-white',kind='centred_on',wallId='wall-east',face='back'),
    )


@pytest.mark.parametrize('topology',['rectangle','L-shaped'])
def test_confirmed_capture_uses_expanded_policy_and_actual_meshes(topology):
    # Confirmed Capture -> normal generator/solver/circulation -> private session.
    storage=ControlledSupabase()
    request=furnished()
    wardrobe=next(p.id for p in source().list() if p.category=='wardrobe')
    request['intents'][-1]['productId']=wardrobe
    provider=TranscriptProvider([request,request,request])
    with TestClient(create_app(catalogue_source=source(),generation_provider=provider,capture_repository=storage.repository,capture_auth=SupabaseAuth(storage.settings,storage.client))) as client:
        if topology=='L-shaped':
            c=confirm_l(client,collect_l(client),widthM=10,depthM=10,notchWidthM=2,notchDepthM=2)
        else:
            c=collect(client)
            draft={**c['draft'],'roomType':'bedroom','topology':'rectangle','widthM':10,'depthM':10,'heightM':2.7,'dimensionsConfirmed':True,'wallReviews':['wall-north','wall-east','wall-south','wall-west'],'furnitureAcknowledged':True}
            c=save_reviewed(client,c,draft)
            c=client.post(f"/api/captures/{c['id']}/confirm",json={'expectedRevision':c['revision']},headers=A).json()['capture']
        result=client.post(f"/api/captures/{c['id']}/generate",json={'expectedRevision':c['revision'],'referenceId':'ref-01'},headers=A).json()
        assert result['status']=='generated' and result['result']['status']=='solved',result
        design=result['result']['design']
        assert design['room']==c['room'] and design['circulation']['status']=='clear'
        assert {p['category'] for p in design['products']} >= {'bed','nightstand','chair','lamp','rug'}
        assert len(design['placements']) <= 8
        assert next(p for p in design['placements'] if p['instanceId']=='anchor-bed')['productId']=='bed-prudence-tufted-queen-natural'
        prompt=json.loads(provider.calls[0]['prompt_text'])
        assert prompt['rules']['selectionScope']['version']=='furnished-bedroom-v1'
        assert len(prompt['eligibleCatalogue']) <= 24
        assert design['swap']['sessionId']


def test_candidate_window_is_balanced_deterministic_and_keeps_full_catalogue():
    entries=[]
    for p in source().list():
        for n in range(15):
            entries.append(CatalogueEntry(p.model_copy(update={'id':f'{p.category}-{n:02}-{p.id}'}),('style-01',)))
    expanded=StaticCatalogue('CONTROLLED-300-plus-candidates',entries)
    eligible=expanded.list(); window=candidate_window(eligible,BEDROOM_POLICY)
    assert len(window)==24 and len(eligible)>=300
    assert {p.category for p in window}==BEDROOM_POLICY.categories
    assert all(sum(p.category==category for p in window)>=2 for category in BEDROOM_POLICY.categories)
    assert candidate_window(tuple(reversed(eligible)),BEDROOM_POLICY)==window
    assert len(expanded.list())==len(eligible)


def test_provider_guesses_outside_the_offered_window_are_rejected_before_solving():
    entries=[]
    for p in source().list():
        for n in range(15):
            entries.append(CatalogueEntry(p.model_copy(update={'id':f'{p.category}-{n:02}-{p.id}'}),('style-01',)))
    expanded=StaticCatalogue('CONTROLLED-window-rejection',entries)
    offered={p.id for p in candidate_window(expanded.list(),BEDROOM_POLICY)}
    excluded=next(p for p in expanded.list() if p.category=='bed' and p.id not in offered)
    draft=selection(dict(id='anchor-bed',productId=excluded.id,kind='against',wallId='wall-north',face='back'))
    provider=TranscriptProvider([draft,draft,draft])
    result=generate_for_room(expanded,LiveGenerationRequest(roomType='bedroom',referenceId='ref-01'),room=rectangular_room_shell('window-room',8,8,2.7),provider=provider)
    assert result.status=='failed' and result.code=='selection-correction-exhausted'
    assert result.providerCalls==3 and result.designFailure is None
    assert [r.code for r in result.selectionRejections]==['ineligible-product-error']*3
    assert all(excluded.id not in {p['id'] for p in json.loads(call['prompt_text'])['eligibleCatalogue']} for call in provider.calls)


def test_category_caps_and_anchor_repair_lock_apply_to_expanded_drafts():
    s=source(); room=rectangular_room_shell('policy-test',10,10,2.7); offer=derive_zones(room); eligible=s.list(); caps=_wall_capability_map(room,eligible)
    draft=furnished();draft['intents'][-1]['productId']=next(p.id for p in eligible if p.category=='wardrobe')
    initial=_validated_selection(draft,room=room,eligible=eligible,zone_offer=offer,capabilities=caps,selection_id='initial',initial=None,enforce_live_scope=True)
    over=deepcopy(draft);over['intents'].append(dict(id='extra-chair',productId='chair-stone-beam-deco-wingback-walnut',kind='facing',referenceId='anchor-bed',gapM=1))
    with pytest.raises(SelectionRejected,match='limits'):
        _validated_selection(over,room=room,eligible=eligible,zone_offer=offer,capabilities=caps,selection_id='too-many',initial=None,enforce_live_scope=True)
    repair=deepcopy(draft);repair['intents'][0]['productId']='bed-rivet-york-queen-grey'
    with pytest.raises(SelectionRejected,match='identity'):
        _validated_selection(repair,room=room,eligible=eligible,zone_offer=offer,capabilities=caps,selection_id='repair',initial=initial,enforce_live_scope=True)
