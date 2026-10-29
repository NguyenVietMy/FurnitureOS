"""Saved resource contracts at the accepted HTTP/SQL authority boundary."""
from fastapi.testclient import TestClient
from api.main import create_app
from backend_tests.local_saved_database import LocalSupabase
from backend_tests.local_saved_database import sql, literal
import pytest
from concurrent.futures import ThreadPoolExecutor
from api.catalogue import catalogue
from api.swaps import DesignSessionStore
from backend_tests.test_captures import ControlledProvider
from backend_tests.test_captures import png
import json
import base64


def fixture_save(client, boundary, key='logical-save-key'):
    design = client.post('/api/design-resolution', json={'fixtureId': 'against-wall'}).json()
    body = {'sessionId': design['swap']['sessionId'], 'expectedVersion': 1, 'idempotencyKey': key, 'consent': True}
    response = client.post('/api/saved-designs', headers=boundary.headers(), json=body)
    assert response.status_code == 200, response.text
    return design, body, response.json()


def test_saved_activation_is_closed_independently_of_capture():
    with TestClient(create_app()) as client:
        config = client.get('/api/saved-designs/config')
        assert config.status_code == 200
        assert config.json()['ready'] is False
        assert client.get('/api/saved-designs').status_code == 503


def test_anonymous_save_retry_and_fresh_process_restore():
    boundary = LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        design = client.post('/api/design-resolution', json={'fixtureId': 'against-wall', 'maxCandidates': 128}).json()
        session = design['swap']
        body = {'sessionId': session['sessionId'], 'expectedVersion': 1, 'idempotencyKey': 'first-logical-save', 'consent': True}
        saved = client.post('/api/saved-designs', headers=boundary.headers(), json=body)
        assert saved.status_code == 200, saved.text
        receipt = saved.json()
        assert receipt['status'] == 'saved'
        assert client.post('/api/saved-designs', headers=boundary.headers(), json=body).json() == receipt
    # Fresh app/store; only durable PostgreSQL survives.
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        assert client.post('/api/saved-designs', headers=boundary.headers(), json=body).json() == receipt
        restored = client.get('/api/saved-designs/' + receipt['id'], headers=boundary.headers())
        assert restored.status_code == 200, restored.text
        assert restored.json()['design']['placements'] == design['placements']
        assert restored.json()['design']['swap']['sessionId'] != session['sessionId']


@pytest.mark.parametrize(('field', 'value', 'code'), [
    ('schemaVersion', '2', 'unsupported-schema'),
    ('catalogueVersion', '"missing-catalogue"', 'catalogue-changed'),
    ('clearanceWidthM', '0.01', 'corrupt-snapshot'),
    ('swap', '{"status":"available","sessionId":"forged"}', 'corrupt-snapshot'),
])
def test_invalid_archive_never_renders_or_grants_a_session(field, value, code):
    boundary = LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        design = client.post('/api/design-resolution', json={'fixtureId': 'against-wall'}).json()
        body = {'sessionId': design['swap']['sessionId'], 'expectedVersion': 1, 'idempotencyKey': 'invalid-archive-key', 'consent': True}
        receipt = client.post('/api/saved-designs', headers=boundary.headers(), json=body).json()
        sql(f"update public.saved_designs set snapshot=jsonb_set(snapshot, '{{{field}}}', {literal(value)}::jsonb) where id={literal(receipt['id'])};")
        restored = client.get('/api/saved-designs/' + receipt['id'], headers=boundary.headers())
        assert restored.status_code == 422
        assert restored.json()['detail']['code'] == code
        assert 'design' not in restored.json()


@pytest.mark.parametrize('other_anonymous', [True, False])
def test_cross_owner_denial_and_durable_deletion_revoke_every_restored_operation(other_anonymous):
    boundary = LocalSupabase()
    other = boundary.add_owner(other_anonymous)
    app = create_app(saved_repository=boundary.saved_repository)
    with TestClient(app) as first, TestClient(create_app(saved_repository=boundary.saved_repository)) as second:
        _, body, receipt = fixture_save(first, boundary)
        url = '/api/saved-designs/' + receipt['id']
        restored = second.get(url, headers=boundary.headers()).json()['design']
        session = restored['swap']['sessionId']; instance = restored['placements'][0]['instanceId']
        assert second.get(url, headers=boundary.headers(other)).status_code == 404
        assert second.get('/api/saved-designs', headers=boundary.headers(other)).json()['items'] == []
        assert second.get('/api/swaps/' + session, headers=boundary.headers(other)).json()['status'] == 'unknown-session'
        assert second.get('/api/swaps/' + session).json()['status'] == 'unknown-session'
        assert first.delete(url, headers=boundary.headers(other)).status_code == 204
        assert second.get('/api/swaps/' + session, headers=boundary.headers()).json()['status'] == 'current'
        assert first.delete(url, headers=boundary.headers()).status_code == 204
        assert first.delete(url, headers=boundary.headers()).status_code == 204
        for path in [f'/api/swaps/{session}', f'/api/swaps/{session}/candidates?expectedVersion=1&instanceId={instance}', f'/api/nudges/{session}/region?expectedVersion=1&instanceId={instance}']:
            assert second.get(path, headers=boundary.headers()).json()['status'] == 'unknown-session'
        for path, request in [('/api/swaps', {'sessionId':session,'expectedVersion':1,'instanceId':instance,'replacementProductId':'bed-rivet-jonathan-queen-walnut'}),
                              ('/api/nudges', {'sessionId':session,'expectedVersion':1,'instanceId':instance,'regionId':'deleted-region','target':[0,0]})]:
            assert second.post(path, json=request, headers=boundary.headers()).json()['status'] == 'unknown-session'
        assert first.post('/api/saved-designs', json=body, headers=boundary.headers()).status_code == 410
        mismatch = {**body, 'sessionId': 'different-session'}
        assert first.post('/api/saved-designs', json=mismatch, headers=boundary.headers()).status_code == 409
        row = __import__('json').loads(sql(f"select to_jsonb(s) from public.saved_designs s where id={literal(receipt['id'])};").stdout)
        assert {k for k,v in row.items() if v is not None} == {'id','owner_id','idempotency_key','request_hash','created_at','deleted_at','purge_at'}


def test_same_uuid_link_requires_refreshed_signed_claims_and_keeps_capture_and_save():
    boundary = LocalSupabase(); provider = ControlledProvider()
    with TestClient(create_app(capture_repository=boundary.capture_repository, saved_repository=boundary.saved_repository, generation_provider=provider)) as client:
        capture = client.post('/api/captures', json={'consent':True}, headers=boundary.headers()).json()
        _, body, receipt = fixture_save(client, boundary)
        old_headers = boundary.headers()
        sql(f'update auth.users set is_anonymous=false where id={literal(boundary.owner)};')
        boundary.profiles[boundary.owner] = False
        assert client.get('/api/saved-designs', headers=old_headers).status_code == 401
        assert client.get('/api/captures/'+capture['id'], headers=old_headers).status_code == 401
        assert client.get('/api/captures/'+capture['id'], headers=boundary.headers()).status_code == 200
        assert client.post('/api/saved-designs', json=body, headers=boundary.headers()).json() == receipt
        assert client.get('/api/saved-designs/'+receipt['id'], headers=boundary.headers()).status_code == 200
        # The refreshed permanent owner also retains the current upload and
        # confirmation service authority, not just metadata SELECT.
        permanent_capture=confirmed_local(client,boundary)
        permanent_generation=client.post(f"/api/captures/{permanent_capture['id']}/generate",json={'expectedRevision':permanent_capture['revision'],'referenceId':'ref-01'},headers=boundary.headers())
        assert permanent_generation.status_code==200,permanent_generation.text
        assert permanent_generation.json()['result']['status']=='solved'


def test_selected_current_swap_and_nudge_are_saved_and_replayed_after_hard_session_cap():
    boundary = LocalSupabase(); clock = [0.0]
    store = DesignSessionStore(catalogue, clock=lambda:clock[0], ttl_seconds=999999)
    with TestClient(create_app(saved_repository=boundary.saved_repository, swap_store=store)) as client:
        original = client.post('/api/design-resolution', json={'fixtureId':'against-wall'}).json()
        session = original['swap']['sessionId']; instance = original['placements'][0]['instanceId']
        candidates = client.get(f'/api/swaps/{session}/candidates',params={'expectedVersion':1,'instanceId':instance}).json()
        changed = client.post('/api/swaps',json={'sessionId':session,'expectedVersion':1,'instanceId':instance,'replacementProductId':candidates['candidates'][0]['product']['id']}).json()
        assert changed['status'] == 'accepted'
        region = client.get(f'/api/nudges/{session}/region',params={'expectedVersion':2,'instanceId':instance}).json()
        target = [region['origin'][0], region['origin'][1]+0.05]
        nudged = client.post('/api/nudges',json={'sessionId':session,'expectedVersion':2,'instanceId':instance,'regionId':region['regionId'],'target':target}).json()
        assert nudged['status'] == 'accepted'
        body = {'sessionId':session,'expectedVersion':3,'idempotencyKey':'mutated-selection','consent':True}
        stale = client.post('/api/saved-designs',json={**body,'expectedVersion':2},headers=boundary.headers())
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'stale-version'
        receipt = client.post('/api/saved-designs',json=body,headers=boundary.headers()).json()
        clock[0] = 1801
        assert client.get('/api/swaps/'+session).json()['status'] == 'expired-session'
        assert client.post('/api/saved-designs',json=body,headers=boundary.headers()).json() == receipt
        assert client.post('/api/saved-designs',json={**body,'idempotencyKey':'new-expired-save'},headers=boundary.headers()).status_code == 409
        restored = client.get('/api/saved-designs/'+receipt['id'],headers=boundary.headers()).json()['design']
        assert restored['placements'] == nudged['design']['placements']
        assert restored['intents'] == nudged['design']['intents']


def test_concurrent_idempotency_conflicts_body_and_list_bounds():
    boundary = LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        _, body, receipt = fixture_save(client, boundary)
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:client.post('/api/saved-designs',json=body,headers=boundary.headers()),range(8)))
        assert all(response.json() == receipt for response in results)
        another = client.post('/api/design-resolution',json={'fixtureId':'against-wall'}).json()
        assert client.post('/api/saved-designs',json={**body,'sessionId':another['swap']['sessionId']},headers=boundary.headers()).status_code == 409
        assert client.post('/api/saved-designs',json={**body,'ownerId':boundary.owner},headers=boundary.headers()).status_code == 422
        assert client.post('/api/saved-designs',content=b'x'*32769,headers={**boundary.headers(),'Content-Type':'application/json'}).status_code == 413
        assert client.get('/api/saved-designs?cursor=corrupt',headers=boundary.headers()).status_code == 422
        assert client.get('/api/saved-designs',headers=boundary.headers()).headers['cache-control'] == 'private, no-store'


def confirmed_local(client, boundary, *, room_type='bedroom', width=6, depth=4):
    headers=boundary.headers()
    current=client.post('/api/captures',json={'consent':True},headers=headers).json()
    for index,wall in enumerate(['wall-north','wall-east','wall-south','wall-west']):
        data=png(index)
        response=client.post(f"/api/captures/{current['id']}/photos",json={'expectedRevision':current['revision'],'declaredBytes':len(data),'primaryWallId':wall},headers=headers)
        assert response.status_code==200,response.text
        current=response.json();photo=current['photos'][-1]
        response=client.post(f"/api/captures/{current['id']}/photos/{photo['id']}/content?expectedRevision={current['revision']}",content=data,headers={**headers,'Content-Type':'image/png'})
        assert response.status_code==200,response.text
        current=response.json()
    draft={**current['draft'],'roomType':room_type,'topology':'rectangle','widthM':width,'depthM':depth,'heightM':2.5,'dimensionsConfirmed':True,'wallReviews':['wall-north','wall-east','wall-south','wall-west'],'furnitureAcknowledged':True}
    for _ in range(2):
        response=client.patch(f"/api/captures/{current['id']}/draft",json={'expectedRevision':current['revision'],'draft':draft},headers=headers)
        assert response.status_code==200,response.text
        current=response.json()
    response=client.post(f"/api/captures/{current['id']}/confirm",json={'expectedRevision':current['revision']},headers=headers)
    assert response.status_code==200 and response.json()['status']=='confirmed',response.text
    return response.json()['capture']


@pytest.mark.parametrize('cleanup',['manual','expiry'])
def test_original_capture_cleanup_is_independent_and_saved_mutations_need_no_upload_activation(cleanup):
    boundary=LocalSupabase();provider=ControlledProvider()
    with TestClient(create_app(capture_repository=boundary.capture_repository,saved_repository=boundary.saved_repository,generation_provider=provider)) as client:
        capture=confirmed_local(client,boundary)
        generated=client.post(f"/api/captures/{capture['id']}/generate",json={'expectedRevision':capture['revision'],'referenceId':'ref-01'},headers=boundary.headers())
        assert generated.status_code==200,generated.text
        design=generated.json()['result']['design']
        body={'sessionId':design['swap']['sessionId'],'expectedVersion':1,'idempotencyKey':'saved-capture-copy','consent':True}
        receipt=client.post('/api/saved-designs',json=body,headers=boundary.headers())
        assert receipt.status_code==200,receipt.text
        receipt=receipt.json()
        snapshot=sql(f"select snapshot::text from public.saved_designs where id={literal(receipt['id'])};").stdout
        for forbidden in ('sessionId','swap','access_token','refresh_token','certificate','lease','expiresAt','photoId','object_key','semantics','canonicalBytes'):
            assert forbidden not in snapshot
        # Link this actual captured save, retaining its UUID and association.
        before_link=boundary.headers()
        sql(f'update auth.users set is_anonymous=false where id={literal(boundary.owner)};')
        boundary.profiles[boundary.owner]=False
        assert client.get('/api/saved-designs/'+receipt['id'],headers=before_link).status_code==401
        linked=client.get('/api/saved-designs/'+receipt['id'],headers=boundary.headers()).json()
        assert linked['capture']=={'id':capture['id'],'confirmedRevision':capture['revision'],'roomHash':capture['roomHash']}
        assert linked['design']['placements']==design['placements']
        if cleanup=='manual':
            assert client.request('DELETE','/api/captures/'+capture['id'],json={'expectedRevision':capture['revision']},headers=boundary.headers()).status_code==200
        else:
            sql(f"update public.captures set created_at=now()-interval '25 hours',expires_at=now()-interval '1 hour' where id={literal(capture['id'])};")
        # Actual cleanup RPCs, with byte deletion controlled at the external Storage boundary.
        job=None
        # The real worker returns at most ten jobs. Earlier disposable tests can
        # leave unrelated jobs ahead of this Capture; consume bounded batches.
        for _ in range(32):
            claimed=json.loads(sql("begin; set local role service_role; select public.capture_cleanup('claim'); commit;").stdout)
            job=next((job for job in claimed if job['capture_id']==capture['id']),None)
            if job is not None:break
        assert job is not None, 'the owned Capture cleanup job was not claimed within 32 worker batches'
        for key in job['keys']:
            boundary.objects.pop(key,None)
            sql('begin; set local role service_role; select public.capture_cleanup(\'progress\','+literal(json.dumps({'id':job['id'],'lease':job['lease_token'],'key':key}))+"::jsonb); commit;")
        sql('begin; set local role service_role; select public.capture_cleanup(\'finish\','+literal(json.dumps({'id':job['id'],'lease':job['lease_token']}))+"::jsonb); commit;")
        assert sql(f"select count(*) from public.captures where id={literal(capture['id'])};").stdout.strip()=='0'
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as restored_client:
        assert restored_client.get('/api/captures/config').json()['storageReady'] is False
        assert len(restored_client.get('/api/saved-designs',headers=boundary.headers()).json()['items'])==1
        restored=restored_client.get('/api/saved-designs/'+receipt['id'],headers=boundary.headers())
        assert restored.status_code==200,restored.text
        assert restored.json()['capture']['id']==capture['id']
        restored_design=restored.json()['design']
        assert restored_design['placements']==design['placements']
        assert restored_client.get('/api/swaps/'+restored_design['swap']['sessionId'],headers=boundary.headers()).json()['status']=='current'
        # A restored save can create an independent new saved copy after original cleanup.
        copy={**body,'sessionId':restored_design['swap']['sessionId'],'idempotencyKey':'independent-saved-copy'}
        assert restored_client.post('/api/saved-designs',json=copy,headers=boundary.headers()).status_code==200


def test_original_expired_source_cannot_resurrect_a_deleted_save_after_tombstone_purge():
    boundary=LocalSupabase();clock=[0.0];store=DesignSessionStore(catalogue,clock=lambda:clock[0],ttl_seconds=999999)
    with TestClient(create_app(saved_repository=boundary.saved_repository,swap_store=store)) as client:
        _,body,receipt=fixture_save(client,boundary)
        client.delete('/api/saved-designs/'+receipt['id'],headers=boundary.headers())
        sql(f"update public.saved_designs set created_at=now()-interval '26 hours',deleted_at=now()-interval '25 hours',purge_at=now() where id={literal(receipt['id'])};")
        clock[0]=1801
        _,_,fresh=fixture_save(client,boundary,'new-source-new-save')
        assert fresh['id']!=receipt['id']
        assert client.post('/api/saved-designs',json=body,headers=boundary.headers()).status_code==409
        assert sql(f"select count(*) from public.saved_designs where id={literal(receipt['id'])};").stdout.strip()=='0'


def test_selected_a_b_c_are_independent_immutable_saves_with_historical_fields():
    from backend_tests.test_live_generation import TranscriptProvider
    from backend_tests.test_living_generation import controlled_catalogue
    from backend_tests.test_variants import selection
    source=controlled_catalogue();boundary=LocalSupabase()
    provider=TranscriptProvider([selection(wall) for wall in ('wall-north','wall-east','wall-south')])
    with TestClient(create_app(catalogue_source=source,generation_provider=provider,saved_repository=boundary.saved_repository,capture_repository=boundary.capture_repository)) as client:
        capture=confirmed_local(client,boundary,room_type='living-room',width=8,depth=8)
        response=client.post(f"/api/captures/{capture['id']}/variants",json={'expectedRevision':capture['revision'],'referenceId':'ref-01'},headers=boundary.headers())
        events=[json.loads(line) for line in response.text.splitlines()]
        variants=[event for event in events if event['type']=='variant']
        assert [event['variant'] for event in variants]==['A','B','C']
        for variant in variants:
            design=variant['result']['design']
            body={'sessionId':design['swap']['sessionId'],'expectedVersion':1,'idempotencyKey':'variant-save-'+variant['variant'],'consent':True}
            saved=client.post('/api/saved-designs',json=body,headers=boundary.headers())
            assert saved.status_code==200,saved.text
            restored=client.get('/api/saved-designs/'+saved.json()['id'],headers=boundary.headers()).json()['design']
            assert restored['placements']==design['placements'] and restored['zones']==design['zones']
            assert restored['search']==design['search'] and restored['arrangementHistory']==design['arrangementHistory']


def test_corrupt_intent_references_are_rejected_even_with_a_matching_digest():
    from hashlib import sha256
    boundary=LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        _,_,receipt=fixture_save(client,boundary)
        row=json.loads(sql(f"select to_jsonb(s) from public.saved_designs s where id={literal(receipt['id'])};").stdout)
        value=row['snapshot'];value['intents'][0]['referenceId']='absent-instance'
        canonical=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        digest=sha256(canonical.encode()).hexdigest()
        fingerprint=sha256(f"{row['request_hash']}:{digest}:1:{value['catalogueVersion']}".encode()).hexdigest()
        sql(f"update public.saved_designs set snapshot={literal(canonical)}::jsonb,snapshot_sha256={literal(digest)},fingerprint={literal(fingerprint)} where id={literal(receipt['id'])};")
        response=client.get('/api/saved-designs/'+receipt['id'],headers=boundary.headers())
        assert response.status_code==422 and response.json()['detail']['code']=='corrupt-snapshot'


@pytest.mark.parametrize('consent',[1,'true',False])
def test_save_requires_literal_retention_consent(consent):
    boundary=LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        design=client.post('/api/design-resolution',json={'fixtureId':'against-wall'}).json()
        response=client.post('/api/saved-designs',json={'sessionId':design['swap']['sessionId'],'expectedVersion':1,'idempotencyKey':'strict-consent-key','consent':consent},headers=boundary.headers())
        assert response.status_code==422


@pytest.mark.parametrize('operation',['read','candidates','swap','region','nudge'])
def test_delete_during_saved_operation_blocks_late_publication(operation):
    boundary=LocalSupabase()
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        _,_,receipt=fixture_save(client,boundary)
        design=client.get('/api/saved-designs/'+receipt['id'],headers=boundary.headers()).json()['design']
        session=design['swap']['sessionId'];instance=design['placements'][0]['instanceId']
        region=client.get(f'/api/nudges/{session}/region',params={'expectedVersion':1,'instanceId':instance},headers=boundary.headers()).json()
        candidates=client.get(f'/api/swaps/{session}/candidates',params={'expectedVersion':1,'instanceId':instance},headers=boundary.headers()).json()
        def concurrent_delete(function,payload):
            if function=='saved_design_user' and payload['p_action']=='read':
                boundary.after_rpc=None
                sql('begin; '+f"set local role authenticated; set local request.jwt.claim.sub={literal(boundary.owner)}; set local request.jwt.claims='{{\"is_anonymous\":true}}'; select public.saved_design_user('delete',{literal(receipt['id'])}); commit;")
        boundary.after_rpc=concurrent_delete
        if operation=='swap':
            response=client.post('/api/swaps',json={'sessionId':session,'expectedVersion':1,'instanceId':instance,'replacementProductId':candidates['candidates'][0]['product']['id']},headers=boundary.headers())
        elif operation=='nudge':
            response=client.post('/api/nudges',json={'sessionId':session,'expectedVersion':1,'instanceId':instance,'regionId':region['regionId'],'target':[region['origin'][0],region['origin'][1]+.05]},headers=boundary.headers())
        else:
            path=f'/api/swaps/{session}' if operation=='read' else f'/api/swaps/{session}/candidates' if operation=='candidates' else f'/api/nudges/{session}/region'
            response=client.get(path,params={'expectedVersion':1,'instanceId':instance},headers=boundary.headers())
        assert response.status_code==200 and response.json()['status']=='unknown-session'
        assert 'design' not in response.json()
        assert client.get('/api/swaps/'+session,headers=boundary.headers()).json()['status']=='unknown-session'


@pytest.mark.parametrize('claim',[None,'true',1,False])
def test_signed_anonymity_must_be_an_exact_current_top_level_boolean(claim):
    boundary=LocalSupabase()
    claims={'sub':boundary.owner,'user_metadata':{'is_anonymous':True}}
    if claim is not None:claims['is_anonymous']=claim
    token='local.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.controlled'
    with TestClient(create_app(saved_repository=boundary.saved_repository)) as client:
        response=client.get('/api/saved-designs',headers={'Authorization':'Bearer '+token})
        assert response.status_code==401
