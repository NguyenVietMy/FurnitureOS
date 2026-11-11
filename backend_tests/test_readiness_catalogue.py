"""Actual activated Catalogue/authority integration; no Style overrides or paid calls."""
import json
import pytest
from api.catalogue import catalogue, CatalogueQuery
from api.domain import rectangular_room_shell, l_shaped_room_shell
from api.live_generation import generate_for_room, generate_live_bedroom, LiveGenerationRequest, candidate_window
from api.room_policy import LEGACY_BEDROOM_POLICY
from api.provider import MODEL_ID, ProviderReply


def test_bounded_bed_proposals_retain_an_actual_mutable_design_in_existing_public_room():
    from api.design import intent_fixture_room
    from api.domain import resolve_design
    from api.models import DesignRequest
    from api.room_policy import BEDROOM_POLICY
    from api.swaps import DesignSessionStore, validate_fixed_pose_design
    room = intent_fixture_room()
    eligible = catalogue.list(CatalogueQuery(room_type='bedroom', private_style_id='style-01'))
    offered = candidate_window(eligible, BEDROOM_POLICY)
    offered_beds = {p.id for p in offered if p.category == 'bed'}
    assert len(offered) <= 24
    for product_id in sorted(offered_beds):
        result = resolve_design(catalogue, DesignRequest.model_validate({
            'room': room.model_dump(mode='json'), 'intents': [{'id': 'anchor-bed', 'productId': product_id, 'kind': 'against', 'wallId': 'wall-north', 'face': 'back'}], 'maxCandidates': 256}))
        if result.status != 'solved':
            continue
        valid, failure = validate_fixed_pose_design(catalogue, result, .6)
        if valid is None:
            continue
        store = DesignSessionStore(catalogue)
        registered = store.register(valid, 'bedroom')
        choices = store.candidates(registered.swap.sessionId, 1, 'anchor-bed')
        if choices.status == 'candidates' and any(c.product.id in offered_beds for c in choices.candidates):
            assert all(catalogue.get(c.product.id) == c.product for c in choices.candidates)
            return
    pytest.fail('The bounded proposals lost every actual fitting, mutable offered bed pair in the unchanged public Room')


class OfferedProductsProvider:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        c = json.loads(kwargs['prompt_text']); self.calls.append(c)
        def pick(category):
            rows = [p for p in c['eligibleCatalogue'] if p['category'] == category]
            return min(rows, key=lambda p: (not p['id'].startswith('abo-'), p['dimensionsM']['widthM'] * p['dimensionsM']['depthM'], p['id'])) if rows else None
        def wall(i, p, w):
            return dict(id=i, productId=p['id'], kind='centred_on', wallId=w, face='back')
        if c.get('immutableRepairContract') and c.get('previousSelection'):
            intents = c['previousSelection']['intents']
        elif c['roomType'] == 'bedroom':
            intents = [wall('anchor-bed', pick('bed'), 'wall-north')]
            for category, side, gap in [('nightstand', 'right', .8), ('lamp', 'left', 2.4)]:
                if p := pick(category):
                    intents.append(dict(id=category, productId=p['id'], kind='adjacent_to', referenceId='anchor-bed', side=side, gapM=gap))
            if p := pick('chair'):
                intents.append(dict(id='chair', productId=p['id'], kind='facing', referenceId='anchor-bed', gapM=1.5))
            for category, w in [('dresser', 'wall-south'), ('wardrobe', 'wall-east')]:
                if (p := pick(category)) and 'back' in p['wallContactFaces']:
                    intents.append(wall(category, p, w))
        else:
            intents = [wall('anchor-sofa', pick('sofa'), 'wall-north'),
                       dict(id='anchor-table', productId=pick('table')['id'], kind='adjacent_to', referenceId='anchor-sofa', side='front', gapM=.85),
                       dict(id='anchor-chair', productId=pick('chair')['id'], kind='adjacent_to', referenceId='anchor-table', side='left', gapM=1)]
        return ProviderReply(payload={'intents': intents}, model=MODEL_ID, stop_reason='end_turn', usage=None, latency_ms=1)


@pytest.mark.parametrize('room_type', ['bedroom', 'living-room'])
@pytest.mark.parametrize('shape', ['rectangle', 'L-shaped'])
def test_actual_activated_products_solve_both_room_types_without_tag_overrides(room_type, shape):
    assert len(catalogue.list()) >= 300
    room = rectangular_room_shell('actual-catalogue', 10, 10, 3) if shape == 'rectangle' else l_shaped_room_shell('actual-catalogue', 10, 10, 2, 2, 3)
    provider = OfferedProductsProvider()
    result = generate_for_room(catalogue, LiveGenerationRequest(roomType=room_type, referenceId='ref-01'), room=room, provider=provider)
    assert result.status == 'solved', result
    retained = {p.productId for p in result.design.placements}
    products = [p for p in result.design.products if p.id in retained]
    required = {'bed', 'nightstand', 'chair', 'lamp'} if room_type == 'bedroom' else {'sofa', 'table', 'chair'}
    assert required <= {p.category for p in products}
    assert len([p for p in products if p.id.startswith('abo-')]) >= len(required)
    assert result.design.circulation.status == 'clear'
    assert all(len(c['eligibleCatalogue']) <= 24 for c in provider.calls)


def test_legacy_entry_rejects_unoffered_style_eligible_ids_without_key_error():
    eligible = catalogue.list(CatalogueQuery(room_type='bedroom', private_style_id='style-01'))
    offered = candidate_window(tuple(p for p in eligible if p.category in LEGACY_BEDROOM_POLICY.categories), LEGACY_BEDROOM_POLICY)
    ids = {p.id for p in offered}
    excluded = next(p for p in eligible if p.category in LEGACY_BEDROOM_POLICY.categories and p.id not in ids)
    bed = next(p for p in offered if p.category == 'bed')
    intents = [dict(id='anchor-bed', productId=excluded.id if excluded.category == 'bed' else bed.id, kind='centred_on', wallId='wall-north', face='back')]
    if excluded.category == 'rug':
        intents.append(dict(id='rug', productId=excluded.id, kind='adjacent_to', referenceId='anchor-bed', side='front', gapM=1))
    class Repeating:
        def generate(self, **kwargs):
            return ProviderReply(payload={'intents': intents}, model=MODEL_ID, stop_reason='end_turn', usage=None, latency_ms=1)
    result = generate_live_bedroom(catalogue, LiveGenerationRequest(roomType='bedroom', referenceId='ref-01'), provider=Repeating())
    assert result.status == 'failed' and result.code == 'selection-correction-exhausted'
    assert result.providerCalls == 3
    assert [r.code for r in result.selectionRejections] == ['ineligible-product-error'] * 3
    assert result.designFailure is None
