from __future__ import annotations
from io import BytesIO
from datetime import datetime,timedelta,timezone
import json
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from api.main import create_app
from api.capture_files import normalize_photo
from api.capture_auth import SupabaseAuth,CaptureError
from api.capture_models import CaptureSemanticProposal,CaptureView
from api.capture_room import validate_capture_rectangle
from api.provider import ProviderReply
from backend_tests.capture_transport import ControlledSupabase,OWNERS,owner_token

def png(index=0):
    out=BytesIO();Image.new("RGB",(640,480),(40+index*20,100,180)).save(out,"PNG");return out.getvalue()

class ControlledProvider:
    def __init__(self):self.calls=[];self.after=None
    def generate(self,**kwargs):
        self.calls.append(kwargs)
        if self.after:self.after()
        prompt=json.loads(kwargs["prompt_text"])
        if "assignedWall" in prompt:
            payload={"openings":[],"detectedFurniture":"present","observation":"clear"}
        else:
            product=next(p for p in prompt["eligibleCatalogue"] if p["category"]=="bed")
            payload={"intents":[{"id":"anchor-bed","kind":"centred_on","productId":product["id"],"wallId":"wall-north","face":"back"}]}
        return ProviderReply(payload=payload,model="claude-opus-5",stop_reason="end_turn",usage=None,latency_ms=1)

@pytest.fixture
def harness():
    service=ControlledSupabase();provider=ControlledProvider()
    client=TestClient(create_app(capture_repository=service.repository,capture_auth=SupabaseAuth(service.settings,service.client),capture_vision_provider=provider,generation_provider=provider))
    return service,provider,client

A={"Authorization":"Bearer "+owner_token('test-owner-a')}
B={"Authorization":"Bearer "+owner_token('test-owner-b')}
def collect(client):
    response=client.post("/api/captures",json={"consent":True},headers=A);assert response.status_code==200
    c=response.json()
    for i,wall in enumerate(("wall-north","wall-east","wall-south","wall-west")):
        data=png(i)
        response=client.post(f"/api/captures/{c['id']}/photos",json={"expectedRevision":c["revision"],"declaredBytes":len(data),"primaryWallId":wall},headers=A)
        assert response.status_code==200
        c=response.json();photo=c["photos"][-1]
        response=client.post(f"/api/captures/{c['id']}/photos/{photo['id']}/content?expectedRevision={c['revision']}",content=data,headers={**A,"Content-Type":"image/png"})
        assert response.status_code==200,response.text
        c=response.json()
    return c

def save_reviewed(client,c,draft):
    # Explicit user workflow: save changed dimensions, then review the normalized
    # saved Room in a separate mutation. No hidden retry exists in the product.
    first=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":draft},headers=A)
    assert first.status_code==200,first.text
    c=first.json()
    second=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":draft},headers=A)
    assert second.status_code==200,second.text
    return second.json()


def confirmed(client,width=6,depth=4):
    c=collect(client)
    draft={**c["draft"],"topology":"rectangle","roomType":"bedroom","widthM":width,"depthM":depth,"heightM":2.5,
           "dimensionsConfirmed":True,"wallReviews":["wall-north","wall-east","wall-south","wall-west"],"furnitureAcknowledged":True}
    c=save_reviewed(client,c,draft)
    response=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":c["revision"]},headers=A)
    assert response.json()["status"]=="confirmed",response.text
    return response.json()["capture"]

def test_disabled_real_service_has_no_memory_fallback(monkeypatch):
    monkeypatch.delenv("FURNITUREOS_CAPTURE_ENABLED",raising=False)
    client=TestClient(create_app())
    assert client.get("/api/captures/config").json()["storageReady"] is False
    assert client.post("/api/captures",json={"consent":True},headers=A).status_code==503

def test_verified_identity_and_every_private_endpoint_deny_stranger(harness):
    service,_,client=harness;c=collect(client);cid=c["id"];pid=c["photos"][0]["id"]
    for method,path,body in [
        ("GET",f"/api/captures/{cid}",None),("GET",f"/api/captures/{cid}/photos/{pid}/content",None),
        ("POST",f"/api/captures/{cid}/confirm",{"expectedRevision":c["revision"]}),
        ("POST",f"/api/captures/{cid}/generate",{"expectedRevision":c["revision"],"referenceId":"ref-01"}),
        ("POST",f"/api/captures/{cid}/photos/{pid}/analyze",{"expectedRevision":c["revision"]}),
        ("DELETE",f"/api/captures/{cid}",{"expectedRevision":c["revision"]}),
        ("PATCH",f"/api/captures/{cid}/draft",{"expectedRevision":c["revision"],"draft":c["draft"]}),
    ]:
        assert client.request(method,path,json=body,headers=B).status_code==404
    assert client.get(f"/api/captures/{cid}").status_code==401
    assert client.get(f"/api/captures/{cid}",headers={"Authorization":"Bearer test-service"}).status_code==401
    assert service.rows[cid]["revision"]==c["revision"]
    reads=[token for _,path,token in service.calls if path.endswith("capture_user_operation")]
    assert all(token!="Bearer test-service" for token in reads)

@pytest.mark.parametrize("data,media,code",[(b"text","image/jpeg","file-type"),(png(),"text/plain","file-type"),(png()[:50],"image/png","invalid-image"),(b"x"*4000001,"image/png","file-size")], ids=["spoof","mime","truncated","oversize"])
def test_actual_image_type_size_decode(data,media,code):
    with pytest.raises(CaptureError) as failure:normalize_photo(data,media)
    assert failure.value.code==code

def test_metadata_stripped_exif_oriented_jpeg_and_animation_rejected():
    image=Image.new("RGB",(640,480),"red");exif=Image.Exif();exif[274]=6;exif[270]="private description"
    out=BytesIO();image.save(out,"JPEG",exif=exif)
    canonical=normalize_photo(out.getvalue(),"image/jpeg")
    assert canonical.width==480 and canonical.height==640
    with Image.open(BytesIO(canonical.data)) as check:assert not check.getexif()
    animated=BytesIO();image.save(animated,"PNG",save_all=True,append_images=[Image.new("RGB",(640,480),"blue")],duration=10)
    with pytest.raises(CaptureError):normalize_photo(animated.getvalue(),"image/png")

def test_missing_coverage_uncertain_swing_and_corrections(harness):
    _,provider,client=harness;c=collect(client)
    draft={**c["draft"],"topology":"rectangle","roomType":"bedroom","widthM":6,"depthM":4,"heightM":2.5,
        "dimensionsConfirmed":True,"wallReviews":["wall-north","wall-east","wall-south","wall-west"],"furnitureAcknowledged":True,
        "openings":[{"id":"door","kind":"door","wallId":"wall-east","distanceFromStartM":0,"widthM":.8,"bottomM":0,"heightM":2,"clearanceDepthM":0,"reviewed":True}]}
    c=save_reviewed(client,c,draft)
    response=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":c["revision"]},headers=A)
    assert any(i["code"]=="unsupported-or-uncertain-swing" for i in response.json()["issues"])
    assert not provider.calls
    draft["openings"][0].update(direction="inward",angle="90",hingeSide="end",wallId="wall-west")
    c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":draft},headers=A).json()
    reviewed=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":c["revision"]},headers=A).json()
    assert reviewed["status"]=="confirmed"
    opening=reviewed["room"]["openings"][0]
    assert opening["wallId"]=="wall-west" and opening["doorSwing"]=={"hingeSide":"end"}
    assert opening["offsetAlongWallM"]==pytest.approx(-1.6)

def test_nonfixture_confirmed_room_reaches_real_solver_and_invalid_distinct(harness):
    service,provider,client=harness;c=confirmed(client)
    result=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A)
    assert result.status_code==200,result.text
    data=result.json();assert data["status"]=="generated" and data["result"]["status"]=="solved",data
    design=data["result"]["design"]
    assert design["room"]==c["room"] and design["room"]["id"]=="capture-"+c["id"]
    assert max(v[0] for v in design["room"]["floorPolygon"])-min(v[0] for v in design["room"]["floorPolygon"])==6
    assert json.loads(provider.calls[0]["prompt_text"])["room"]==c["room"]
    draft={**c["draft"],"widthM":0}
    changed=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":draft},headers=A).json()
    invalid=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":changed["revision"],"referenceId":"ref-01"},headers=A).json()
    assert invalid["code"]=="invalid-room" and invalid["providerCalls"]==0
    assert client.get(f"/api/swaps/{design['swap']['sessionId']}",headers=A).status_code==200 # revoked => typed unknown, no geometry
    assert "design" not in client.get(f"/api/swaps/{design['swap']['sessionId']}",headers=A).json()

def test_small_valid_room_produces_honest_solver_no_fit(harness):
    _,provider,client=harness;c=confirmed(client,1,1)
    response=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A)
    assert response.status_code==200,response.text
    result=response.json()["result"]
    assert result["status"]=="failed" and result["code"]=="no-valid-design",result
    assert result["designFailure"]["reason"]=="NO_VALID_DESIGN"
    assert len(provider.calls)==3

def test_expiry_delete_and_late_generation_cannot_publish(harness):
    service,provider,client=harness;c=confirmed(client)
    provider.after=lambda:service.rows[c["id"]].update(state="deleting",roomHash=None)
    response=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A)
    assert response.status_code==404
    assert client.get(f"/api/captures/{c['id']}",headers=A).status_code==404

def test_semantics_forbid_metrics_and_cannot_overwrite_reviewed_draft(harness):
    _,provider,client=harness;c=confirmed(client);pid=c["photos"][0]["id"]
    response=client.post(f"/api/captures/{c['id']}/photos/{pid}/analyze",json={"expectedRevision":c["revision"]},headers=A)
    assert response.status_code==200,response.text
    updated=response.json()
    assert updated["revision"]==c["revision"]+1 and updated["state"]=="draft"
    assert updated["room"] is None and updated["confirmedRevision"] is None and updated["roomHash"] is None
    assert updated["draft"]["wallReviews"]==["wall-east","wall-south","wall-west"]
    assert updated["draft"]["furnitureAcknowledged"] is False
    for field in ("widthM","depthM","heightM","dimensionsConfirmed","openings","dimensionEvidence"):
        assert updated["draft"][field]==c["draft"][field]
    assert response.json()["photos"][0]["semantics"]["detectedFurniture"]=="present"
    from pydantic import ValidationError
    with pytest.raises(ValidationError):CaptureSemanticProposal.model_validate({"openings":[],"detectedFurniture":"unknown","observation":"unknown","widthM":4})
