"""One rectangle authority for review, confirmation and generation."""
from __future__ import annotations
from hashlib import sha256
import json
from pydantic import ValidationError
from .capture_models import CaptureView, CaptureIssue, WALL_IDS
from .domain import rectangular_room_shell
from .models import RoomShell
from .zones import derive_zones, ZoneDerivationError
from .circulation import MAX_RAW_LATTICE_POINTS, MAX_LATTICE_POINTS_PER_AXIS
from math import floor

def room_hash(room: RoomShell) -> str:
    return sha256(json.dumps(room.model_dump(mode="json"),sort_keys=True,separators=(",",":")).encode()).hexdigest()

def validate_capture_rectangle(capture: CaptureView) -> tuple[RoomShell | None, tuple[CaptureIssue,...]]:
    draft, issues = capture.draft, []
    def issue(code,field,detail):
        issues.append(CaptureIssue(code=code,field=field,detail=detail))
    if draft.topology != "rectangle":
        issue("unsupported-topology","topology","Choose Rectangle. Other Room shapes are not supported.")
    if draft.roomType != "bedroom":
        issue("unsupported-room-type","roomType","Declare Bedroom; other Room Types are not supported by this generator.")
    accepted = [p for p in capture.photos if p.state == "accepted"]
    if set(p.primaryWallId for p in accepted) != set(WALL_IDS) or len(accepted)<4:
        issue("missing-wall-coverage","photos","Add an accepted photo for each stable wall A, B, C and D.")
    if len({p.sha256 for p in accepted}) != len(accepted):
        issue("duplicate-wall-photo","photos","The same photo cannot count as different wall coverage.")
    if set(draft.wallReviews) != set(WALL_IDS):
        issue("unreviewed-wall-openings","wallReviews","Review the complete Opening inventory on every wall, including walls without Openings.")
    for field in ("widthM","depthM","heightM"):
        value = getattr(draft,field)
        if value is None or not 0 < value <= 1000:
            issue("invalid-dimension",field,"Enter a positive finite dimension no greater than 1000 m.")
    if not draft.dimensionsConfirmed:
        issue("unconfirmed-dimensions","dimensionsConfirmed","Explicitly confirm all three final dimensions.")
    if any(p.semantics is None or p.semantics.detectedFurniture != "absent" for p in accepted) and not draft.furnitureAcknowledged:
        issue("furniture-warning","furnitureAcknowledged","Acknowledge that this Design assumes an empty Room.")
    photos = {p.id:p for p in accepted}
    for evidence in draft.dimensionEvidence:
        photo = photos.get(evidence.photoId)
        if photo is None or photo.sha256 != evidence.photoHash:
            issue("stale-calibration","dimensionEvidence","Remove or remeasure calibration whose photo changed.")
    for field in ("widthM","depthM","heightM"):
        evidence = [e for e in draft.dimensionEvidence if e.field == field]
        if len(evidence)>1:
            low,high = min(e.valueM for e in evidence),max(e.valueM for e in evidence)
            if high-low>max(.05,.05*low) and not all(e.overrideReason.strip() for e in evidence):
                issue("dimension-conflict",field,"Resolve conflicting measurements or supply an explicit manual override reason.")
    if len({o.id for o in draft.openings}) != len(draft.openings):
        issue("duplicate-opening","openings","Opening IDs must be unique.")
    openings = []
    for opening in draft.openings:
        prefix = "openings."+opening.id
        if not opening.reviewed or opening.wallId is None or opening.kind == "unknown":
            issue("unresolved-opening",prefix,"Review this Opening's wall and type.")
            continue
        required = ("distanceFromStartM","widthM","bottomM","heightM","clearanceDepthM")
        if any(getattr(opening,name) is None for name in required):
            issue("missing-opening-metric",prefix,"Enter offset, width, bottom, height and clearance for this Opening.")
            continue
        d,w,b,h,c = (getattr(opening,name) for name in required)
        length = draft.widthM if opening.wallId in ("wall-north","wall-south") else draft.depthM
        if length is None or d<0 or w<=0 or b<0 or h<=0 or c<0 or d+w>length+1e-9 or draft.heightM is None or b+h>draft.heightM+1e-9:
            issue("invalid-opening",prefix,"Opening intervals must fit their wall and ceiling, with positive width/height.")
            continue
        swing = None
        if opening.kind == "door":
            if opening.direction != "inward" or opening.angle != "90" or opening.hingeSide == "unknown":
                issue("unsupported-or-uncertain-swing",prefix,"Confirm an inward 90-degree swing and its start/end hinge; unknown or other operation blocks generation.")
                continue
            if b != 0:
                issue("invalid-opening",prefix,"Door bottom must be at the floor.")
                continue
            swing = {"hingeSide":opening.hingeSide}
        elif opening.direction != "unknown" or opening.angle != "unknown" or opening.hingeSide != "unknown":
            issue("invalid-opening",prefix,"Windows cannot carry door swing fields.")
            continue
        openings.append({"id":opening.id,"kind":opening.kind,"wallId":opening.wallId,
                         "offsetAlongWallM":d+w/2-length/2,"widthM":w,"bottomM":b,"heightM":h,
                         "clearanceDepthM":c,"doorSwing":swing})
    for i,a in enumerate(openings):
        for b in openings[i+1:]:
            if a["wallId"] == b["wallId"] and abs(a["offsetAlongWallM"]-b["offsetAlongWallM"]) < (a["widthM"]+b["widthM"])/2-1e-9 and min(a["bottomM"]+a["heightM"],b["bottomM"]+b["heightM"])-max(a["bottomM"],b["bottomM"])>1e-9:
                issue("opening-overlap","openings","Openings on the same wall cannot overlap.")
    if issues:
        return None,tuple(issues)
    try:
        shell = rectangular_room_shell("capture-"+capture.id,draft.widthM,draft.depthM,draft.heightM)
        data = shell.model_dump(mode="json")
        data["openings"] = openings
        for wall,label in zip(data["walls"],"ABCD",strict=True):
            wall["label"] = "Wall "+label
        return RoomShell.model_validate(data),()
    except (ValidationError,ValueError):
        issue("invalid-room","room","These dimensions and Openings do not describe a supported rectangle.")
        return None,tuple(issues)

def computational_support(room: RoomShell) -> str | None:
    try:
        derive_zones(room)
    except ZoneDerivationError:
        return "This valid Room exceeds the supported Zone computation bounds."
    xs,zs = zip(*room.floorPolygon,strict=True)
    # Match the authority's raw lattice: the 0.60 m walker stays inside the shell.
    nx,nz = max(0,floor((max(xs)-min(xs)-.60)/.05+1e-9)+1),max(0,floor((max(zs)-min(zs)-.60)/.05+1e-9)+1)
    if nx>MAX_LATTICE_POINTS_PER_AXIS or nz>MAX_LATTICE_POINTS_PER_AXIS or nx*nz>MAX_RAW_LATTICE_POINTS:
        return "This valid Room exceeds the supported circulation computation bounds."
    return None
