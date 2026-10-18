"""Accepted inspection regressions: actual API/solver, controlled external transport."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from threading import Event
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from api.capture_auth import CaptureError,SupabaseAuth
from api.main import create_app
from api.provider import ProviderReply
from api.swaps import DesignSessionStore
from backend_tests.test_captures import save_reviewed, harness,confirmed,collect,ControlledProvider,A


def test_deletion_poll_is_inaccessible_only_for_genuinely_deleting_rows(harness):
    service,_,client=harness;c=confirmed(client);path=f"/api/captures/{c['id']}/deletion"
    missing=client.get(f"/api/captures/{uuid4()}/deletion",headers=A)
    active=client.get(path,headers=A)
    assert active.status_code==404 and active.json()==missing.json()
    service.rows[c['id']]['expiresAt']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    expired=client.get(path,headers=A)
    assert expired.status_code==404 and expired.json()==missing.json()
    # The durable worker has tombstoned the row; still-stored private data is never polled.
    service.rows[c['id']].update(state='deleting',cleanupStatus='pending')
    for _ in range(2):
        status=client.get(path,headers=A)
        assert status.status_code==200
        assert status.json()=={'id':c['id'],'state':'deleting','inaccessible':True,'cleanupStatus':'pending'}
    del service.rows[c['id']];del service.owners[c['id']]
    assert client.get(path,headers=A).status_code==404


@pytest.mark.parametrize('flag',[False,None,'true',1])
def test_verified_nonanonymous_or_missing_profile_denies_every_private_admission(harness,flag):
    service,provider,client=harness;c=confirmed(client);pid=c['photos'][0]['id']
    profile={'id':service.owners[c['id']],'user_metadata':{'is_anonymous':True}}
    if flag is not None:profile['is_anonymous']=flag
    service.auth_profiles['test-owner-a']=profile
    call_count=len(service.calls)
    for method,path,body in [
        ('POST','/api/captures',{'consent':True}),('GET',f"/api/captures/{c['id']}",None),
        ('GET',f"/api/captures/{c['id']}/deletion",None),
        ('POST',f"/api/captures/{c['id']}/photos",{'expectedRevision':c['revision'],'declaredBytes':1000,'primaryWallId':'wall-north'}),
        ('GET',f"/api/captures/{c['id']}/photos/{pid}/content",None),
        ('POST',f"/api/captures/{c['id']}/generate",{'expectedRevision':c['revision'],'referenceId':'ref-01'})]:
        result=client.request(method,path,json=body,headers=A)
        assert result.status_code==401 and result.json()['detail']['code']=='authentication-required'
    assert all(path=='/auth/v1/user' for _,path,_ in service.calls[call_count:])
    assert not provider.calls


class ReviewProvider(ControlledProvider):
    def __init__(self,hold=None):
        super().__init__();self.hold=hold;self.started=Event();self.release=Event()
    def generate(self,**kwargs):
        vision='assignedWall' in json.loads(kwargs['prompt_text'])
        if self.hold==('vision' if vision else 'generation'):
            self.started.set();assert self.release.wait(15),'controlled provider release timed out'
        if vision:
            self.calls.append(kwargs)
            return ProviderReply(payload={'openings':[{'id':'new-door','wallId':'wall-north','kind':'door',
                'location':'near-start','visibility':'partial','direction':'unknown','angle':'unknown',
                'hingeSide':'unknown','description':'New uncertain evidence'}],'detectedFurniture':'unknown','observation':'partial'},
                model='claude-opus-5',stop_reason='end_turn',usage=None,latency_ms=1)
        return super().generate(**kwargs)


def remote_client(service,provider):
    return TestClient(create_app(capture_repository=service.repository,capture_auth=SupabaseAuth(service.settings,service.client),
        capture_vision_provider=provider,generation_provider=provider))
def generate(client,c):
    return client.post(f"/api/captures/{c['id']}/generate",json={'expectedRevision':c['revision'],'referenceId':'ref-01'},headers=A)
def analyze(client,c):
    return client.post(f"/api/captures/{c['id']}/photos/{c['photos'][0]['id']}/analyze",json={'expectedRevision':c['revision']},headers=A)


def test_post_confirmation_semantics_preserves_corrections_and_revokes_local_and_remote_sessions(harness):
    service,_,_=harness;provider=ReviewProvider();local=remote_client(service,provider);remote=remote_client(service,provider)
    c=confirmed(local)
    draft={**c['draft'],'openings':[{'id':'corrected-window','wallId':'wall-east','kind':'window','distanceFromStartM':1,
        'widthM':.7,'bottomM':1,'heightM':.8,'clearanceDepthM':0,'reviewed':True}]}
    c=local.patch(f"/api/captures/{c['id']}/draft",json={'expectedRevision':c['revision'],'draft':draft},headers=A).json()
    c=local.post(f"/api/captures/{c['id']}/confirm",json={'expectedRevision':c['revision']},headers=A).json()['capture']
    local_design=generate(local,c).json()['result']['design'];remote_design=generate(remote,c).json()['result']['design']
    updated=analyze(local,c).json()
    assert updated['revision']==c['revision']+1 and updated['state']=='draft'
    assert updated['room'] is None and updated['confirmedRevision'] is None and updated['roomHash'] is None
    assert updated['draft']['openings']==c['draft']['openings']
    assert updated['draft']['widthM']==6 and updated['draft']['dimensionsConfirmed'] is True
    assert 'wall-north' not in updated['draft']['wallReviews'] and not updated['draft']['furnitureAcknowledged']
    assert not service.leases # Old vision lease released safely despite revision advancement.
    for client,design in [(local,local_design),(remote,remote_design)]:
        assert client.get(f"/api/swaps/{design['swap']['sessionId']}",headers=A).json()['status']=='unknown-session'
    paid_attempts=len(provider.calls)
    blocked=generate(local,updated).json()
    assert blocked['status']=='blocked' and blocked['providerCalls']==0 and len(provider.calls)==paid_attempts
    renewed={**updated['draft'],'wallReviews':['wall-north','wall-east','wall-south','wall-west'],'furnitureAcknowledged':True}
    updated=local.patch(f"/api/captures/{c['id']}/draft",json={'expectedRevision':updated['revision'],'draft':renewed},headers=A).json()
    updated=local.post(f"/api/captures/{c['id']}/confirm",json={'expectedRevision':updated['revision']},headers=A).json()['capture']
    assert generate(local,updated).json()['result']['status']=='solved'


def test_semantic_commit_invalidates_inflight_remote_generation(harness):
    service,_,client=harness;c=confirmed(client);provider=ReviewProvider('generation');remote=remote_client(service,provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(generate,remote,c)
        try:
            assert provider.started.wait(10)
            updated=analyze(client,c);assert updated.status_code==200
            assert updated.json()['revision']==c['revision']+1
        finally:provider.release.set()
        late=pending.result(timeout=15)
    assert late.status_code==409 and late.json()['detail']['code']=='stale-capture'
    assert not service.leases


def test_semantic_commit_invalidates_inflight_remote_session_read(harness,monkeypatch):
    service,_,client=harness;c=confirmed(client);remote=remote_client(service,ReviewProvider());design=generate(remote,c).json()['result']['design']
    sid=design['swap']['sessionId'];started,release=Event(),Event();original=DesignSessionStore.current
    def waiting_current(store,session_id):
        value=original(store,session_id)
        if session_id==sid:started.set();assert release.wait(15)
        return value
    monkeypatch.setattr(DesignSessionStore,'current',waiting_current)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(remote.get,f'/api/swaps/{sid}',headers=A)
        try:
            assert started.wait(10);assert analyze(client,c).status_code==200
        finally:release.set()
        late=pending.result(timeout=15)
    assert late.json()['status']=='unknown-session' and 'design' not in late.json()


def test_released_late_analysis_cannot_overwrite_subsequent_user_corrections(harness):
    service,_,base=harness;c=confirmed(base);provider=ReviewProvider('vision');client=remote_client(service,provider)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(analyze,client,c)
        try:
            assert provider.started.wait(10)
            principal=SupabaseAuth(service.settings,service.client).verify(A['Authorization'])
            lease=next(key for key,value in service.leases.items() if value[4]=='vision')
            service.repository.user(principal,'release',c['id'],c['revision'],{'lease':lease})
            corrected={**deepcopy(c['draft']),'widthM':7}
            changed=base.patch(f"/api/captures/{c['id']}/draft",json={'expectedRevision':c['revision'],'draft':corrected},headers=A)
            assert changed.status_code==200
        finally:provider.release.set()
        late=pending.result(timeout=15)
    assert late.status_code==409 and late.json()['detail']['code']=='stale-capture'
    current=base.get(f"/api/captures/{c['id']}",headers=A).json()
    assert current['draft']=={**corrected,'dimensionsConfirmed':False,'wallReviews':[]} and current['photos'][0]['semantics'] is None
    assert not service.leases


def semantic_evidence(wall):
    return {'openings':[] if wall=='none' else [{'id':'observed-opening','wallId':wall,'kind':'door',
        'location':'middle','visibility':'partial','direction':'unknown','angle':'unknown','hingeSide':'unknown',
        'description':'Controlled replacement evidence'}],'detectedFurniture':'absent','observation':'partial'}


class ReplacementProvider(ControlledProvider):
    def __init__(self,old,new):
        super().__init__();self.proposals=iter([semantic_evidence(old),semantic_evidence(new)])
    def generate(self,**kwargs):
        if 'assignedWall' not in json.loads(kwargs['prompt_text']):return super().generate(**kwargs)
        self.calls.append(kwargs)
        return ProviderReply(payload=next(self.proposals),model='claude-opus-5',stop_reason='end_turn',usage=None,latency_ms=1)


@pytest.mark.parametrize('old,new,observed,remaining',[
    ('wall-south','none',['wall-east'],['wall-west']),
    ('wall-south','wall-east',[],['wall-west']),
    (None,'wall-east',['wall-east'],[]),
    (None,'none',['wall-east'],[]),
    ('wall-south',None,['wall-east'],[]),
    (None,None,['wall-east'],[]),
],ids=['removed','moved','old-unknown-resolved','old-unknown-empty','new-unknown','both-unknown'])
def test_reanalysis_requires_review_of_prior_and_current_proposal_walls(harness,old,new,observed,remaining):
    service,_,_=harness;provider=ReplacementProvider(old,new);client=remote_client(service,provider)
    c=collect(client)
    c=client.patch(f"/api/captures/{c['id']}/draft",headers=A,json={'expectedRevision':c['revision'],'draft':{**c['draft'],'topology':'rectangle'}}).json()
    pid=c['photos'][0]['id']
    c=client.patch(f"/api/captures/{c['id']}/photos/{pid}",headers=A,
        json={'expectedRevision':c['revision'],'primaryWallId':'wall-north','observedWallIds':observed}).json()
    first=analyze(client,c);assert first.status_code==200
    c=first.json();assert c['photos'][0]['semantics']==semantic_evidence(old)
    reference=client.post(f"/api/captures/{c['id']}/calibrate",headers=A,json={
        'expectedRevision':c['revision'],'photoId':pid,'photoHash':c['photos'][0]['sha256'],
        'referenceType':'measured','referenceWidthM':2,'referenceHeightM':2,'plane':'floor',
        'perspective1x':True,'coplanar':True,'visible':True,'dimensionsReviewed':True,'marksReviewed':True,
        'corners':[[50,50],[150,50],[150,150],[50,150]],
        'segments':[{'field':'widthM','start':[50,200],'end':[350,200]}]})
    assert reference.status_code==200 and reference.json()['status']=='provisional',reference.text
    c=client.get(f"/api/captures/{c['id']}",headers=A).json()
    assert len(c['calibrations'])==1
    all_walls=['wall-north','wall-east','wall-south','wall-west']
    corrected={**c['draft'],'roomType':'bedroom','topology':'rectangle','widthM':6.4,'depthM':4.2,'heightM':2.5,
        'dimensionsConfirmed':True,'wallReviews':all_walls,'furnitureAcknowledged':True,
        'openings':[{'id':'manual-window','wallId':'wall-west','kind':'window','distanceFromStartM':1,'widthM':.7,
            'bottomM':1,'heightM':.8,'clearanceDepthM':0,'reviewed':True}],
        'dimensionEvidence':[{'field':'widthM','valueM':reference.json()['estimates'][0]['valueM'],'photoId':pid,
            'photoHash':c['photos'][0]['sha256'],'overrideReason':'Tape measured 6.4 m; controlled provisional reference retained.'}]}
    c=save_reviewed(client,c,corrected)
    confirmation=client.post(f"/api/captures/{c['id']}/confirm",headers=A,json={'expectedRevision':c['revision']})
    assert confirmation.json()['status']=='confirmed',confirmation.text
    c=confirmation.json()['capture'];before=deepcopy(c)
    second=analyze(client,c);assert second.status_code==200
    c=second.json()
    assert c['draft']['wallReviews']==remaining
    assert {k:v for k,v in c['draft'].items() if k!='wallReviews'}=={k:v for k,v in before['draft'].items() if k!='wallReviews'}
    assert c['calibrations']==before['calibrations']
    assert c['revision']==before['revision']+1 and c['state']=='draft'
    assert c['room'] is None and c['roomHash'] is None and c['confirmedRevision'] is None
    assert c['photos'][0]['semantics']==semantic_evidence(new) and c['photos'][0]['analysisAttempts']==2
    attempts=len(provider.calls)
    blocked=generate(client,c).json()
    assert blocked['status']=='blocked' and blocked['providerCalls']==0 and len(provider.calls)==attempts
    # Re-reviewing only primary/observed/NEW walls must still leave the old wall blocked.
    new_only=set(remaining)|{'wall-north',*observed}
    if new not in (None,'none'):new_only.add(new)
    incomplete={**c['draft'],'wallReviews':[wall for wall in all_walls if wall in new_only]}
    c=client.patch(f"/api/captures/{c['id']}/draft",headers=A,json={'expectedRevision':c['revision'],'draft':incomplete}).json()
    incomplete_confirmation=client.post(f"/api/captures/{c['id']}/confirm",headers=A,json={'expectedRevision':c['revision']}).json()
    assert incomplete_confirmation['status']=='review'
    assert any(issue['code']=='unreviewed-wall-openings' for issue in incomplete_confirmation['issues'])
    assert len(provider.calls)==attempts
    renewed={**c['draft'],'wallReviews':all_walls}
    c=client.patch(f"/api/captures/{c['id']}/draft",headers=A,json={'expectedRevision':c['revision'],'draft':renewed}).json()
    confirmation=client.post(f"/api/captures/{c['id']}/confirm",headers=A,json={'expectedRevision':c['revision']}).json()
    assert confirmation['status']=='confirmed'
    assert generate(client,confirmation['capture']).json()['result']['status']=='solved'
    assert not service.leases
