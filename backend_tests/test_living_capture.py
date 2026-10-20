"""Synthetic photos with the real HTTP save/review/confirm/session authority."""
import pytest
from fastapi.testclient import TestClient
from api.capture_auth import SupabaseAuth
from api.main import create_app
from backend_tests.capture_transport import ControlledSupabase
from backend_tests.test_captures import A, B, collect, save_reviewed
from backend_tests.test_l_shaped import collect_l, confirm_l
from backend_tests.test_living_generation import controlled_catalogue, ControlledProvider


@pytest.fixture
def living_capture():
    storage=ControlledSupabase()
    provider=ControlledProvider()
    with TestClient(create_app(catalogue_source=controlled_catalogue(),generation_provider=provider,
        capture_repository=storage.repository,capture_auth=SupabaseAuth(storage.settings,storage.client))) as client:
        yield storage,provider,client


def confirm_living(client,topology):
    if topology=='L-shaped':
        return confirm_l(client,collect_l(client),roomType='living-room',widthM=8,depthM=8,notchWidthM=2,notchDepthM=2)
    c=collect(client)
    draft={**c['draft'],'roomType':'living-room','topology':'rectangle','widthM':8,'depthM':8,'heightM':2.7,'dimensionsConfirmed':True,'wallReviews':['wall-north','wall-east','wall-south','wall-west'],'furnitureAcknowledged':True}
    c=save_reviewed(client,c,draft)
    r=client.post(f"/api/captures/{c['id']}/confirm",json={'expectedRevision':c['revision']},headers=A)
    assert r.json()['status']=='confirmed',r.text
    return r.json()['capture']


@pytest.mark.parametrize('topology',['rectangle','L-shaped'])
def test_declared_type_reaches_generation_session_and_revision_revokes_it(living_capture,topology):
    _,provider,client=living_capture
    c=confirm_living(client,topology)
    assert c['draft']['roomType']=='living-room'
    body={'expectedRevision':c['revision'],'referenceId':'ref-01'}
    assert client.post(f"/api/captures/{c['id']}/generate",json={**body,'roomType':'bedroom'},headers=A).status_code==422
    r=client.post(f"/api/captures/{c['id']}/generate",json=body,headers=A).json()
    assert r['status']=='generated' and r['result']['status']=='solved',r
    result=r['result'];design=result['design']
    assert {p['instanceId'] for p in design['placements']}=={'anchor-sofa','anchor-table','anchor-chair'}
    assert result['roomType']=='living-room' and provider.calls[-1]['roomType']=='living-room'
    assert design['room']==c['room'] and len(design['room']['walls'])==(6 if topology=='L-shaped' else 4)
    session=design['swap']['sessionId']
    candidates=client.get(f'/api/swaps/{session}/candidates?expectedVersion=1&instanceId=anchor-sofa',headers=A).json()
    assert candidates['status']=='candidates'
    assert all('living-room' in e['product']['roomTypes'] for e in candidates['candidates'])
    assert client.get(f'/api/swaps/{session}',headers=B).json()['status']=='unknown-session'
    changed=client.patch(f"/api/captures/{c['id']}/draft",json={'expectedRevision':c['revision'],'draft':{**c['draft'],'roomType':'bedroom'}},headers=A).json()
    assert changed['revision']>c['revision'] and changed['confirmedRevision'] is None and changed['room'] is None
    assert client.get(f'/api/swaps/{session}',headers=A).json()['status']=='unknown-session'


def test_late_cross_type_response_cannot_publish_a_private_session(living_capture):
    storage,provider,client=living_capture
    c=confirm_living(client,'rectangle')
    original=provider.generate
    def delayed(**kwargs):
        reply=original(**kwargs)
        row=storage.rows[c['id']]
        row['draft']['roomType']='bedroom'
        storage.revoke(row)
        return reply
    provider.generate=delayed
    r=client.post(f"/api/captures/{c['id']}/generate",json={'expectedRevision':c['revision'],'referenceId':'ref-01'},headers=A)
    assert r.status_code==409 and 'design' not in r.json()
