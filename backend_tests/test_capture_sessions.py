from __future__ import annotations
from datetime import datetime,timedelta,timezone
import pytest
from api.swaps import DesignSessionStore
from api.main import create_app
from fastapi.testclient import TestClient
from backend_tests.test_captures import harness,confirmed,A,B

def generate(client,c):
    result=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A)
    assert result.status_code==200
    return result.json()["result"]["design"]

def test_private_geometry_denied_on_every_session_path_then_owner_succeeds(harness):
    _,_,client=harness;c=confirmed(client);design=generate(client,c);sid=design["swap"]["sessionId"];instance=design["placements"][0]["instanceId"]
    unknown=client.get("/api/swaps/never-existed").json()
    for headers in (B,{},{"Authorization":"Bearer bad"}):
        for method,path,body in [
            ("GET",f"/api/swaps/{sid}",None),
            ("GET",f"/api/swaps/{sid}/candidates?expectedVersion=1&instanceId={instance}",None),
            ("GET",f"/api/nudges/{sid}/region?expectedVersion=1&instanceId={instance}",None),
            ("POST","/api/swaps",{"sessionId":sid,"expectedVersion":1,"instanceId":instance,"replacementProductId":design["products"][0]["id"]}),
            ("POST","/api/nudges",{"sessionId":sid,"expectedVersion":1,"instanceId":instance,"regionId":"bad","target":[0,0]})
        ]:
            response=client.request(method,path,json=body,headers=headers)
            assert response.status_code==200 and response.json()==unknown
    # Failed outsider admission does not revoke the rightful owner's session.
    current=client.get(f"/api/swaps/{sid}",headers=A).json()
    assert current["status"]=="current"
    assert current["design"]["room"]==c["room"]

def test_remote_expiry_and_delete_revoke_already_published_design(harness):
    service,_,client=harness;c=confirmed(client);design=generate(client,c);sid=design["swap"]["sessionId"]
    service.rows[c["id"]]["expiresAt"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    result=client.get(f"/api/swaps/{sid}",headers=A).json()
    assert result["status"]=="unknown-session" and "design" not in result

def test_captured_swap_and_nudge_record_writers_keep_owner_binding(harness):
    _,_,client=harness;c=confirmed(client);design=generate(client,c);sid=design["swap"]["sessionId"];instance=design["placements"][0]["instanceId"]
    candidates=client.get(f"/api/swaps/{sid}/candidates?expectedVersion=1&instanceId={instance}",headers=A).json()
    if candidates.get("candidates"):
        target=candidates["candidates"][0]["product"]["id"]
        swapped=client.post("/api/swaps",json={"sessionId":sid,"expectedVersion":1,"instanceId":instance,"replacementProductId":target},headers=A).json()
        assert swapped["status"]=="accepted"
        assert client.get(f"/api/swaps/{sid}",headers=B).json()["status"]=="unknown-session"
        current=client.get(f"/api/swaps/{sid}",headers=A).json()
        assert current["status"]=="current" and current["version"]==2

def test_captured_nudge_writer_and_remote_delete_during_publication(harness):
    service,_,client=harness;c=confirmed(client)
    draft={**c["draft"],"openings":[{"id":"entry","wallId":"wall-south","kind":"door",
        "distanceFromStartM":.3,"widthM":.8,"bottomM":0,"heightM":2,"clearanceDepthM":.2,
        "direction":"inward","angle":"90","hingeSide":"end","reviewed":True}]}
    c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":draft},headers=A).json()
    c=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":c["revision"]},headers=A).json()["capture"]
    design=generate(client,c);sid=design["swap"]["sessionId"];instance=design["placements"][0]["instanceId"]
    region=client.get(f"/api/nudges/{sid}/region?expectedVersion=1&instanceId={instance}",headers=A).json()
    assert region["status"]=="available",region
    polygon=region["polygon"];point=max(polygon,key=lambda p:p[0]**2+p[1]**2)
    target=[region["origin"][i]+point[i]*.25 for i in (0,1)]
    result=client.post("/api/nudges",json={"sessionId":sid,"expectedVersion":1,"instanceId":instance,
        "regionId":region["regionId"],"target":target},headers=A).json()
    assert result["status"]=="accepted",result
    assert client.get(f"/api/swaps/{sid}",headers=B).json()["status"]=="unknown-session"
    assert client.get(f"/api/swaps/{sid}",headers=A).json()["version"]==2
    # Another process invalidates the persisted lease after local current() work.
    service.on_assert=lambda _service,row:row.update(state="deleting")
    result=client.get(f"/api/swaps/{sid}",headers=A).json()
    assert result["status"]=="unknown-session" and "design" not in result
