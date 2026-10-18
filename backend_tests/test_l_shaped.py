from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from math import cos,sin,pi,hypot
import json
import pytest
from pydantic import ValidationError
from api.capture_models import CaptureView,L_WALL_IDS
from api.capture_room import validate_capture_rectangle
from api.circulation import _prepare_room_geometry,_inside_prepared_room,_swept_polygon,validate_circulation
from api.domain import l_shaped_room_shell,footprint_of,inside_depth,validate_placement,wall_inward_normal
from api.models import RoomShell,Placement
from api.nudges import build_nudge_certificate,certificate_contains,nudged_placement
from api.swaps import validate_fixed_pose_design
from api.zones import derive_zones
from api.room_geometry import signed_area
from backend_tests.test_zones_circulation import product_variant,static_catalogue,solved_from_placements

def room():
    return l_shaped_room_shell("hand-l",6,5,2,2,2.7)

def capture(**patch):
    now=datetime.now(timezone.utc)
    draft=dict(roomType="bedroom",topology="L-shaped",widthM=6,depthM=5,notchWidthM=2,notchDepthM=2,heightM=2.7,
               dimensionsConfirmed=True,wallReviews=list(L_WALL_IDS),furnitureAcknowledged=True)
    draft.update(patch)
    return CaptureView.model_validate(dict(id="33333333-3333-3333-3333-333333333333",revision=1,state="draft",
        createdAt=now,expiresAt=now+timedelta(hours=24),draft=draft,
        photos=[dict(id=f"44444444-4444-4444-4444-{i+1:012d}",primaryWallId=wall,state="accepted",declaredBytes=1000,sha256=str(i+1)*64)
                for i,wall in enumerate(L_WALL_IDS)]))

def transformed(shell,angle,reverse=False):
    def point(p):return (100+p[0]*cos(angle)-p[1]*sin(angle),200+p[0]*sin(angle)+p[1]*cos(angle))
    data=shell.model_dump(mode="json")
    data["floorPolygon"]=[point(p) for p in (reversed(shell.floorPolygon) if reverse else shell.floorPolygon)]
    data["walls"]=[dict(w.model_dump(),start=point(w.end),end=point(w.start)) for w in reversed(shell.walls)]
    return RoomShell.model_validate(data),point

def test_hand_computed_capture_vertices_lengths_zones_and_area():
    shell,issues=validate_capture_rectangle(capture())
    assert not issues
    assert shell.floorPolygon==((-3,-2.5),(1,-2.5),(1,-.5),(3,-.5),(3,2.5),(-3,2.5))
    assert [hypot(w.end[0]-w.start[0],w.end[1]-w.start[1]) for w in shell.walls]==[4,2,2,3,6,5]
    assert signed_area(shell.floorPolygon)==26
    offer=derive_zones(room())
    expected=((-3,-2.5,1,-.5),(-3,-.5,3,2.5))
    assert tuple((z.bounds.minX,z.bounds.minZ,z.bounds.maxX,z.bounds.maxZ) for z in offer.zones)==expected
    assert [z.id for z in offer.zones]==["zone-"+sha256(("hand-l|"+s).encode()).hexdigest()[:12]
                                         for s in ("-3,-2.5,1,-0.5","-3,-0.5,3,2.5")]
    assert sum((b-a)*(d-c) for a,c,b,d in expected)==26

@pytest.mark.parametrize("field,value",[("notchWidthM",0),("notchWidthM",-1),("notchWidthM",6),("notchDepthM",5),("widthM",0),("heightM",-2),("notchDepthM",6)])
def test_invalid_dimensions_are_field_specific_and_correctable(field,value):
    shell,issues=validate_capture_rectangle(capture(**{field:value}))
    assert shell is None and any(i.field==field for i in issues)
    assert not validate_capture_rectangle(capture())[1]

@pytest.mark.parametrize("value",[float("nan"),float("inf"),-float("inf")])
def test_nonfinite_dimensions_rejected_before_provider(value):
    with pytest.raises(ValidationError):capture(notchWidthM=value)

@pytest.mark.parametrize("angle,reverse",[(0,False),(.37,False),(.37,True),(pi/2,True)])
def test_rotated_reversed_wall_normals_points_and_footprints(angle,reverse):
    shell,point=transformed(room(),angle,reverse)
    assert abs(signed_area(shell.floorPolygon))==pytest.approx(26)
    assert inside_depth(shell,point((0,-1.5)))==pytest.approx(1)
    assert inside_depth(shell,point((2,-1.5)))==pytest.approx(-1)
    small=product_variant("small",width=.5,depth=.5)
    for centre,status in [((0,-1.5),"fits"),((2,1),"fits"),((2,-1.5),"invalid-fit")]:
        c=point(centre)
        fit=validate_placement(small,shell,Placement(productId=small.id,position=(c[0],0,c[1]),yaw=-angle))
        assert fit.status==status
    b=next(w for w in shell.walls if w.id=="wall-notch-vertical")
    assert wall_inward_normal(shell,b)==pytest.approx((-cos(angle),-sin(angle)))
    # Valid lower-arm placement lies beyond the unrelated notch-wall half-plane.
    assert validate_placement(small,shell,Placement(productId=small.id,position=(*point((2,1))[:1],0,point((2,1))[1]),yaw=0)).status=="fits"

def test_whole_rotated_footprint_crosses_notch_despite_all_corners_inside():
    shell=room();product=product_variant("bridge",width=4,depth=.2)
    placement=Placement(productId=product.id,position=(1,0,-.5),yaw=-pi/4)
    footprint=footprint_of(product,(1,-.5),placement.yaw)
    assert all(inside_depth(shell,p)>0 for p in footprint.corners)
    assert validate_placement(product,shell,placement).reason=="footprint-outside-room"
    geometry=_prepare_room_geometry(shell)
    assert not _inside_prepared_room(geometry,footprint.corners)
    # A swept connector can cross the notch with individually contained endpoints.
    assert not _inside_prepared_room(geometry,_swept_polygon((.5,-1.5),(2.2,0),.6))


@pytest.mark.parametrize("size",[1e-30,1e-200])
@pytest.mark.parametrize("centre,status",[((.6,0),"fits"),((0,0),"fits"),((2,-1.5),"invalid-fit")])
def test_tiny_positive_subject_edges_remain_safe_in_domain_and_http(size,centre,status):
    from fastapi.testclient import TestClient
    from api.main import create_app
    product=product_variant("tiny-positive",width=size,depth=size,placement_class="floor-covering")
    shell=room()
    placement=Placement(productId=product.id,position=(centre[0],0,centre[1]),yaw=0)
    fit=validate_placement(product,shell,placement)
    assert fit.status==status
    # Disable exception propagation to assert the actual HTTP boundary is not500.
    client=TestClient(create_app(),raise_server_exceptions=False)
    response=client.post("/api/placement-validation",json=dict(product=product.model_dump(mode="json"),
        room=shell.model_dump(mode="json"),placement=placement.model_dump(mode="json")))
    assert response.status_code==200,response.text
    assert response.json()["status"]==status
    if status=="invalid-fit":assert response.json()["reason"]=="footprint-outside-room"

@pytest.mark.parametrize("z,status",[(-1.5,"fits"),(1,"invalid-fit"),(-.6,"invalid-fit"),(-.75,"fits"),(-.7495,"fits"),(-.748,"invalid-fit")])
def test_finite_notch_wall_contact_full_partial_and_tolerance(z,status):
    product=product_variant("contact",width=.5,depth=.5)
    placement=Placement(instanceId="contact",productId=product.id,position=(.75,0,z),yaw=0,wallContact={"wallId":"wall-notch-vertical","face":"right"})
    fit=validate_placement(product,room(),placement)
    assert fit.status==status
    if status=="invalid-fit":assert fit.reason=="not-touching-declared-wall"
    if z==1:
        moved=nudged_placement(product,room(),placement,(.75,z))
        assert not moved.wallContacts

def test_required_access_and_notch_opening_exclusions():
    product=product_variant("access",width=.5,depth=.5,access_regions=[dict(face="right",depthM=1,required=True,purpose="access")])
    fit=validate_placement(product,room(),Placement(productId=product.id,position=(.5,0,-1.5),yaw=0))
    assert fit.status=="invalid-fit" and fit.reason=="access-region-outside-room"
    small=product_variant("small",width=.2,depth=.2)
    for wall,centre in [("wall-notch-vertical",(.8,-1.5)),("wall-notch-horizontal",(2,-.3))]:
        for hinge in ("start","end"):
            data=room().model_dump(mode="json")
            data["openings"]=[dict(id="notch-door",kind="door",wallId=wall,offsetAlongWallM=0,widthM=1,bottomM=0,heightM=2,clearanceDepthM=.6,doorSwing=dict(hingeSide=hinge))]
            shell=RoomShell.model_validate(data)
            fit=validate_placement(small,shell,Placement(productId=small.id,position=(centre[0],0,centre[1]),yaw=0))
            assert fit.status=="invalid-fit" and fit.reason in ("opening-exclusion","door-swing-exclusion")
            assert all(not (z.bounds.minX<centre[0]<z.bounds.maxX and z.bounds.minZ<centre[1]<z.bounds.maxZ) for z in derive_zones(shell).zones)

@pytest.mark.parametrize("points",[
    ((0,0),(4,0),(3,1),(4,4),(0,4)), # unsupported reflex nonorthogonal
    ((0,0),(4,0),(4,4),(2,2),(0,4),(2,1)), # unsupported concavity
    ((0,0),(4,4),(4,0),(0,4)), # self intersection
    ((0,0),(4,0),(4,0),(4,4),(0,4)), # duplicate
    ((0,0),(2,0),(4,0),(4,4),(0,4)), # collinear
])
def test_rejects_unsupported_polygons(points):
    data=dict(id="bad",ceilingHeightM=3,floorPolygon=points,walls=[dict(id=str(i),label=str(i),start=p,end=points[(i+1)%len(points)]) for i,p in enumerate(points)])
    with pytest.raises(ValidationError):RoomShell.model_validate(data)

def elbow_design(arm):
    shell=l_shaped_room_shell("elbow",6,5,6-arm,5-arm,3)
    data=shell.model_dump(mode="json")
    data["openings"]=[dict(id="entry",kind="door",wallId="wall-west",offsetAlongWallM=2-arm/2,widthM=.6,bottomM=0,heightM=2,clearanceDepthM=0,doorSwing=dict(hingeSide="start")),
                      dict(id="exit",kind="door",wallId="wall-south",offsetAlongWallM=-2.5+arm/2,widthM=.6,bottomM=0,heightM=2,clearanceDepthM=0,doorSwing=dict(hingeSide="end"))]
    # west directed north; entry near top. south directed west; exit near right.
    return solved_from_placements(RoomShell.model_validate(data),(),())

@pytest.mark.parametrize("arm,status",[(1,"clear"),(.59,"CIRCULATION_BLOCKED")])
def test_complete_circulation_through_elbow(arm,status):
    result=validate_circulation(elbow_design(arm),.6)
    assert result.status==status

def test_available_l_certificate_safe_nudge_and_notch_rejection_and_swap_revalidation():
    product=product_variant("mover",width=.4,depth=.4)
    placement=Placement(instanceId="mover",productId=product.id,position=(.6,0,0),yaw=0)
    design=solved_from_placements(room(),(product,),(placement,))
    certificate,response=build_nudge_certificate(design,"mover",.6,region_id="region",session_id="session",version=1,expires_at=100)
    assert response.status=="available"
    assert certificate_contains(certificate,(.6,.2))
    assert not certificate_contains(certificate,(1.2,-.8))
    moved=nudged_placement(product,room(),placement,(.6,.2))
    assert validate_placement(product,room(),moved).status=="fits"
    oversized=product_variant("mover",width=5,depth=4)
    _,failure=validate_fixed_pose_design(static_catalogue(oversized),design,.6)
    assert failure is not None
    inaccessible=product_variant("mover",width=1.4,depth=.4,access_regions=[dict(face="back",depthM=2,required=True,purpose="access")])
    _,failure=validate_fixed_pose_design(static_catalogue(inaccessible),design,.6)
    assert failure is not None

def test_capture_requires_six_primary_photos_and_active_associations():
    c=capture();assert not validate_capture_rectangle(c)[1]
    data=c.model_dump(mode="json");data["photos"][1]["primaryWallId"]="wall-north";data["photos"][0]["observedWallIds"]=list(L_WALL_IDS)
    assert any(i.code=="missing-wall-coverage" for i in validate_capture_rectangle(CaptureView.model_validate(data))[1])
    data=c.model_dump(mode="json");data["draft"]["topology"]="rectangle";data["draft"]["wallReviews"]=["wall-north","wall-east","wall-south","wall-west"]
    assert any(i.code=="inactive-photo-wall" for i in validate_capture_rectangle(CaptureView.model_validate(data))[1])


from backend_tests.test_captures import harness,A,B,png
from api.capture_reference import ReferenceRequest,calibrate

def collect_l(client):
    c=client.post("/api/captures",json={"consent":True},headers=A).json()
    c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":{**c["draft"],"topology":"L-shaped","roomType":"bedroom"}},headers=A).json()
    for i,wall in enumerate(L_WALL_IDS):
        image=png(i)
        result=client.post(f"/api/captures/{c['id']}/photos",json={"expectedRevision":c["revision"],"primaryWallId":wall,"declaredBytes":len(image)},headers=A)
        assert result.status_code==200,result.text
        c=result.json();pid=c["photos"][-1]["id"]
        result=client.post(f"/api/captures/{c['id']}/photos/{pid}/content?expectedRevision={c['revision']}",content=image,headers={**A,"Content-Type":"image/png"})
        assert result.status_code==200,result.text
        c=result.json()
    return c

def confirm_l(client,c,**metrics):
    desired={**c["draft"],"widthM":6,"depthM":5,"notchWidthM":2,"notchDepthM":2,"heightM":2.7,**metrics,"dimensionsConfirmed":True,"wallReviews":list(L_WALL_IDS),"furnitureAcknowledged":True}
    first=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":desired},headers=A)
    assert first.status_code==200,first.text
    c=first.json()
    reviewed={**c["draft"],"dimensionsConfirmed":True,"wallReviews":list(L_WALL_IDS)}
    c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":reviewed},headers=A).json()
    response=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":c["revision"]},headers=A)
    assert response.status_code==200 and response.json()["status"]=="confirmed",response.text
    return response.json()["capture"]

def test_l_capture_http_six_photos_confirm_real_solver_and_metric_revocation(harness):
    _,provider,client=harness
    c=confirm_l(client,collect_l(client))
    result=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A)
    assert result.status_code==200,result.text
    body=result.json()
    assert body["result"]["status"]=="solved",body
    design=body["result"]["design"]
    assert len(design["room"]["walls"])==6 and design["room"]==c["room"]
    assert design["circulation"]["status"]=="clear"
    sid=design["swap"]["sessionId"];instance=design["placements"][0]["instanceId"]
    assert client.get(f"/api/swaps/{sid}",headers=B).json()["status"]=="unknown-session"
    assert client.get(f"/api/swaps/{sid}",headers=A).json()["status"]=="current"
    assert client.get(f"/api/swaps/{sid}/candidates?expectedVersion=2&instanceId={instance}",headers=A).json()["status"]=="stale-version"
    assert client.get(f"/api/nudges/{sid}/region?expectedVersion=2&instanceId={instance}",headers=A).json()["status"]=="stale-version"
    prior_calls=len(provider.calls)
    for field in ("widthM","depthM","heightM","notchWidthM","notchDepthM"):
        desired={**c["draft"],field:c["draft"][field]+.1,"dimensionsConfirmed":True,"wallReviews":list(L_WALL_IDS)}
        c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":desired},headers=A).json()
        assert c["draft"]["dimensionsConfirmed"] is False and c["draft"]["wallReviews"]==[]
        assert c["room"] is None and c["roomHash"] is None and c["state"]=="draft"
        assert client.get(f"/api/swaps/{sid}",headers=A).json()["status"]=="unknown-session"
        denied=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A).json()
        assert denied["status"]=="blocked" and denied["providerCalls"]==0 and len(provider.calls)==prior_calls
        c=confirm_l(client,c)

def test_l_capture_http_no_fit_retains_limiting_constraint(harness):
    _,provider,client=harness
    c=confirm_l(client,collect_l(client),widthM=1.4,depthM=1.4,notchWidthM=.6,notchDepthM=.6)
    result=client.post(f"/api/captures/{c['id']}/generate",json={"expectedRevision":c["revision"],"referenceId":"ref-01"},headers=A).json()
    assert result["status"]=="generated" and result["result"]["code"]=="no-valid-design",result
    assert result["result"]["designFailure"]["limitingConstraint"]
    assert len(provider.calls)<=3

@pytest.mark.parametrize("field",["notchWidthM","notchDepthM"])
def test_notch_reference_targets_are_floor_lengths(field):
    base=dict(expectedRevision=1,photoId="44444444-4444-4444-4444-444444444444",photoHash="a"*64,
        referenceType="measured",referenceWidthM=2,referenceHeightM=2,plane="floor",perspective1x=True,
        coplanar=True,visible=True,dimensionsReviewed=True,marksReviewed=True,corners=[[50,50],[150,50],[150,150],[50,150]],
        segments=[dict(field=field,start=[50,200],end=[150,200])])
    result=calibrate(ReferenceRequest.model_validate(base),640,480)
    assert result.status=="provisional" and result.estimates[0].valueM==pytest.approx(2)
    base["plane"]="wall"
    assert calibrate(ReferenceRequest.model_validate(base),640,480).reason=="noncoplanar-target"

def test_shape_change_drops_provisional_truth_but_keeps_photo_bytes_and_attempts(harness):
    service,_,client=harness
    c=confirm_l(client,collect_l(client));photo=c["photos"][0]
    reference=dict(expectedRevision=c["revision"],photoId=photo["id"],photoHash=photo["sha256"],
        referenceType="measured",referenceWidthM=2,referenceHeightM=2,plane="floor",perspective1x=True,coplanar=True,
        visible=True,dimensionsReviewed=True,marksReviewed=True,corners=[[50,50],[150,50],[150,150],[50,150]],
        segments=[dict(field="widthM",start=[50,200],end=[350,200])])
    assert client.post(f"/api/captures/{c['id']}/calibrate",json=reference,headers=A).status_code==200
    c=client.get(f"/api/captures/{c['id']}",headers=A).json()
    evidence=dict(field="widthM",valueM=6,photoId=photo["id"],photoHash=photo["sha256"],overrideReason="")
    c=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":{**c["draft"],"dimensionEvidence":[evidence]}},headers=A).json()
    before=dict(service.objects)
    changed=client.patch(f"/api/captures/{c['id']}/draft",json={"expectedRevision":c["revision"],"draft":{**c["draft"],"topology":"rectangle","dimensionsConfirmed":True}},headers=A).json()
    assert changed["draft"]["widthM"] is None and changed["draft"]["dimensionEvidence"]==[] and changed["calibrations"]==[]
    assert changed["draft"]["notchWidthM"] is None and len(changed["photos"])==6 and service.objects==before
    assert any(p["primaryWallId"]=="wall-notch-vertical" for p in changed["photos"])
    assert all(p["semantics"] is None and p["observedWallIds"]==[] for p in changed["photos"])
    issue=client.post(f"/api/captures/{c['id']}/confirm",json={"expectedRevision":changed["revision"]},headers=A).json()
    assert any(i["code"]=="inactive-photo-wall" for i in issue["issues"])

def test_quarter_turn_zones_have_independently_expected_bounds_and_area():
    shell,_=transformed(room(),pi/2,True)
    zones=derive_zones(shell).zones
    assert [(z.bounds.minX,z.bounds.minZ,z.bounds.maxX,z.bounds.maxZ) for z in zones]==[
        (97.5,197,102.5,201),(97.5,201,100.5,203)]
    assert sum((z.bounds.maxX-z.bounds.minX)*(z.bounds.maxZ-z.bounds.minZ) for z in zones)==26

def test_wide_elbow_blocked_connectivity_by_complete_arm_obstacle():
    shell=elbow_design(1).room
    obstacle=product_variant("arm-block",width=1,depth=.4)
    design=solved_from_placements(shell,(obstacle,),(Placement(instanceId="block",productId=obstacle.id,position=(-2.5,0,0),yaw=0),))
    assert validate_circulation(design,.6).status=="CIRCULATION_BLOCKED"

@pytest.mark.parametrize("changes,code",[
    (dict(wallId="wall-notch-vertical",distanceFromStartM=1.8,widthM=.5),"invalid-opening"),
    (dict(wallId="wall-notch-horizontal",distanceFromStartM=0,widthM=2.5),"invalid-opening"),
    (dict(wallId=None),"unresolved-opening"),
])
def test_l_opening_bounds_are_correctable(changes,code):
    opening=dict(id="window",kind="window",wallId="wall-notch-vertical",distanceFromStartM=0,widthM=.5,bottomM=1,heightM=.5,clearanceDepthM=0,reviewed=True)
    opening.update(changes)
    assert any(i.code==code for i in validate_capture_rectangle(capture(openings=[opening]))[1])

def test_real_l_bed_with_required_access_has_a_useful_nudge_certificate():
    from api.catalogue import catalogue
    from api.domain import resolve_design
    from api.models import DesignRequest,PlacementIntent
    data=room().model_dump(mode="json")
    data["openings"]=[dict(id="entry",kind="door",wallId="wall-west",offsetAlongWallM=0,widthM=.8,bottomM=0,heightM=2,clearanceDepthM=0,doorSwing=dict(hingeSide="start"))]
    shell=RoomShell.model_validate(data)
    design=resolve_design(catalogue,DesignRequest(room=shell,intents=[PlacementIntent(id="bed",kind="centred_on",productId="bed-prudence-tufted-queen-natural",wallId="wall-south",face="back")]))
    assert design.status=="solved",design
    certificate,response=build_nudge_certificate(design,"bed",.6,region_id="bed-region",session_id="bed-session",version=1,expires_at=100)
    assert response.status=="available"
    origin=certificate.origin
    assert any(certificate_contains(certificate,(origin[0]+dx,origin[1]+dz)) for dx,dz in ((.05,0),(-.05,0),(0,-.05)))
    assert not certificate_contains(certificate,(2,-1))

def test_l_semantic_schema_and_prompt_are_active_wall_specific(harness):
    _,provider,client=harness
    c=collect_l(client);photo=c["photos"][0]
    response=client.post(f"/api/captures/{c['id']}/photos/{photo['id']}/analyze",headers=A,json={"expectedRevision":c["revision"]})
    assert response.status_code==200,response.text
    prompt=json.loads(provider.calls[-1]["prompt_text"])
    assert prompt["allowedWalls"]==list(L_WALL_IDS)
    assert "wall-notch-vertical" in json.dumps(provider.calls[-1]["output_schema"])
