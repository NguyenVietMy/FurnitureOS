"""API-only bytes: real repository/HTTP boundary over an offline privileged store."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import httpx
import pytest
from api import capture_auth
from api.capture_auth import CaptureError,CapturePrincipal,SupabaseSettings
from backend_tests.capture_transport import OWNERS
from backend_tests.test_captures import harness,collect,A,B


def photo_url(c):return f"/api/captures/{c['id']}/photos/{c['photos'][0]['id']}/content"


def invalidate(service,c,kind):
    row=service.rows[c["id"]]
    if kind=="delete":row["state"]="deleting";service.leases.clear()
    elif kind=="expiry":row["expiresAt"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif kind=="revision":row["revision"]+=1
    elif kind=="manifest":row["photos"][0]["sha256"]="a"*64
    elif kind=="unaccepted":row["photos"][0]["state"]="failed"
    elif kind=="owner":service.owners[c["id"]]=OWNERS["test-owner-b"]
    elif kind=="identity":service.auth_profiles["test-owner-a"]["is_anonymous"]=False
    elif kind=="lease":service.leases.clear()
    else:raise AssertionError(kind)


def test_owner_api_bytes_are_canonical_uncached_and_all_direct_caller_reads_deny(harness):
    s,_,client=harness;c=collect(client);p=c["photos"][0]
    key=s.key(OWNERS["test-owner-a"],c["id"],p["id"])
    for _ in range(2):
        reply=client.get(photo_url(c),headers=A)
        assert reply.status_code==200 and reply.content==s.objects[key]
        assert reply.headers["cache-control"]=="no-store" and reply.headers["x-content-type-options"]=="nosniff"
        assert "x-storage-internal" not in reply.headers and "cacheNonce" not in reply.text
        for caller in (A,B,{}):
            for prefix in ("","authenticated/"):
                assert s.client.get(s.settings.url+"/storage/v1/object/"+prefix+"captures/"+key,headers=caller).status_code==404
    assert len(s.storage_reads)==2
    assert len({str(r.url) for r in s.storage_reads})==2
    assert all(r.url.host=="capture-test.invalid" and r.headers["authorization"]=="Bearer test-service" for r in s.storage_reads)
    assert all(token!="Bearer test-service" for _,path,token in s.calls if path.endswith("capture_user_operation"))
    response=client.request("DELETE",f"/api/captures/{c['id']}",json={"expectedRevision":c["revision"]},headers=A)
    assert response.status_code==200
    assert client.get(photo_url(c),headers=A).status_code==404
    assert key in s.objects and len(s.storage_reads)==2 # Pending durable cleanup, no new fetch.


@pytest.mark.parametrize("kind",["delete","expiry","revision","manifest","unaccepted","owner","identity","lease"])
def test_failed_precheck_performs_zero_privileged_byte_reads(harness,kind):
    s,_,client=harness;c=collect(client);p=c["photos"][0];principal=CapturePrincipal(OWNERS["test-owner-a"],A['Authorization'][7:])
    with s.repository.lease(principal,c["id"],c["revision"],"photo-read") as lease:
        invalidate(s,c,kind)
        with pytest.raises(CaptureError) as failure:
            s.repository.download(principal,c["id"],p["id"],revision=c["revision"],lease=lease,expected_sha256=p["sha256"])
        assert failure.value.status_code==404
    assert not s.storage_reads


@pytest.mark.parametrize("kind",["delete","expiry","revision","manifest","unaccepted","owner","identity","lease"])
@pytest.mark.parametrize("analysis",[False,True],ids=["response","provider"])
def test_after_fetch_race_emits_no_photo_or_provider_call(harness,kind,analysis):
    s,provider,client=harness;c=collect(client)
    s.on_storage_read=lambda service:invalidate(service,c,kind)
    if analysis:
        response=client.post(photo_url(c).removesuffix("content")+"analyze",json={"expectedRevision":c["revision"]},headers=A)
    else:response=client.get(photo_url(c),headers=A)
    assert response.status_code==404 and response.headers["content-type"]=="application/json"
    assert not provider.calls and len(s.storage_reads)==1


@pytest.mark.parametrize("kind",["delete","revision","identity","lease"])
@pytest.mark.parametrize("analysis",[False,True])
def test_final_api_assertion_blocks_race_after_repository_guard(harness,monkeypatch,kind,analysis):
    s,provider,client=harness;c=collect(client);download=s.repository.download
    def late(*args,**kwargs):
        data=download(*args,**kwargs);invalidate(s,c,kind);return data
    monkeypatch.setattr(s.repository,"download",late)
    if analysis:reply=client.post(photo_url(c).removesuffix("content")+"analyze",json={"expectedRevision":c["revision"]},headers=A)
    else:reply=client.get(photo_url(c),headers=A)
    assert reply.status_code==404 and reply.headers["content-type"]=="application/json"
    assert not provider.calls


@pytest.mark.parametrize("url",["http://capture-test.invalid","https://evil.invalid/path","https://user@capture-test.invalid",
    "https://capture-test.invalid?x=1","https://capture-test.invalid#fragment","https://capture-test.invalid:444"])
def test_byte_transport_rejects_non_project_https_root_without_privileged_read(harness,url):
    s,_,client=harness;c=collect(client);p=c["photos"][0];principal=CapturePrincipal(OWNERS["test-owner-a"],A['Authorization'][7:])
    with s.repository.lease(principal,c["id"],c["revision"],"photo-read") as lease:
        s.repository.settings=replace(s.settings,url=url)
        with pytest.raises(CaptureError):
            s.repository.download(principal,c["id"],p["id"],revision=c["revision"],lease=lease,expected_sha256=p["sha256"])
    assert not s.storage_reads


@pytest.mark.parametrize("failure",["redirect","oversize","hash","timeout","error-array","error-message"])
def test_bounded_raw_fetch_never_forwards_redirect_or_invalid_bytes(harness,failure):
    s,provider,client=harness;c=collect(client);original=s.client
    def handle(request):
        if request.method=="GET" and request.url.path.startswith("/storage/v1/object/captures/"):
            if failure=="redirect":return httpx.Response(302,headers={"Location":"https://evil.invalid/private"})
            if failure=="timeout":raise httpx.ReadTimeout("offline deadline")
            if failure=="error-array":return httpx.Response(400,json=[])
            if failure=="error-message":return httpx.Response(400,json={"message":123})
            return httpx.Response(200,content=b"x"*(400001 if failure=="oversize" else 100))
        return original.send(request)
    s.repository.client=httpx.Client(transport=httpx.MockTransport(handle))
    try:
        response=client.get(photo_url(c),headers=A)
        assert response.status_code==404 and "location" not in response.headers and not provider.calls
    finally:s.repository.client.close()


def test_sixth_gate_is_default_closed_without_reading_actual_environment(monkeypatch):
    gates=["ENABLED","AUTH_VERIFIED","SCHEMA_VERIFIED","STORAGE_VERIFIED","CLEANUP_VERIFIED"]
    fake={"FURNITUREOS_CAPTURE_"+key:"1" for key in gates}
    fake.update(SUPABASE_URL="https://capture-test.invalid",SUPABASE_PUBLISHABLE_KEY="fake-public",SUPABASE_SECRET_KEY="fake-secret")
    monkeypatch.setattr(capture_auth,"os",SimpleNamespace(environ=fake))
    with pytest.raises(CaptureError) as failure:SupabaseSettings.from_environment()
    assert failure.value.code=="activation-required"
    fake["FURNITUREOS_CAPTURE_SERVER_PHOTOS_VERIFIED"]="0"
    with pytest.raises(CaptureError):SupabaseSettings.from_environment()
    fake["FURNITUREOS_CAPTURE_SERVER_PHOTOS_VERIFIED"]="1"
    assert SupabaseSettings.from_environment().url=="https://capture-test.invalid"
