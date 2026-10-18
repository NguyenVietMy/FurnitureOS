from __future__ import annotations
from copy import deepcopy
import pytest
from api.capture_reference import ReferenceRequest,calibrate
from api.capture_models import CaptureView,DimensionEvidence
from api.capture_room import validate_capture_rectangle
from backend_tests.test_captures import harness,confirmed
from backend_tests.capture_transport import OWNERS

def request(**overrides):
    data={"expectedRevision":1,"photoId":"11111111-1111-1111-1111-111111111111","photoHash":"a"*64,"referenceType":"measured",
        "referenceWidthM":1,"referenceHeightM":1,"plane":"floor","perspective1x":True,"coplanar":True,"visible":True,
        "dimensionsReviewed":True,"marksReviewed":True,"corners":[[100,100],[300,100],[300,300],[100,300]],
        "segments":[{"field":"widthM","start":[100,350],"end":[900,350]}]}
    return ReferenceRequest.model_validate({**data,**overrides})

def test_independent_projective_correspondences_recover_known_distance():
    # Forward projection is independently specified; the helper only sees image points.
    def project(x,y):
        denominator=1+.025*x+.015*y
        return [(200+220*x+15*y)/denominator,(160+10*x+215*y)/denominator]
    r=request(corners=[project(0,0),project(1,0),project(1,1),project(0,1)],
        segments=[{"field":"widthM","start":project(0,2),"end":project(4,2)}])
    result=calibrate(r,1400,1000)
    assert result.status=="provisional"
    assert result.estimates[0].valueM==pytest.approx(4,abs=1e-8)
    assert result.requiresConfirmation is True

@pytest.mark.parametrize("changes,reason",[
    ({"coplanar":False},"unconfirmed-plane-or-marks"),
    ({"visible":False},"unconfirmed-plane-or-marks"),
    ({"perspective1x":False},"unsupported-projection"),
    ({"segments":[{"field":"heightM","start":[100,350],"end":[900,350]}]},"noncoplanar-target"),
    ({"corners":[[100,100],[120,100],[120,120],[100,120]]},"tiny-reference"),
    ({"corners":[[100,100],[300,300],[300,100],[100,300]]},"degenerate-reference"),
    ({"referenceType":"a4"},"reference-size-mismatch")
])
def test_unreliable_reference_returns_no_metric_values(changes,reason):
    result=calibrate(request(**changes),1200,800)
    assert result.status=="typed-input-required" and result.reason==reason and not result.estimates

def test_extrapolation_and_zero_dimension_fail_closed():
    result=calibrate(request(corners=[[100,100],[125,100],[125,150],[100,150]]),1200,800)
    assert result.status=="typed-input-required"
    result=calibrate(request(segments=[{"field":"depthM","start":[350,350],"end":[350,350]}]),1200,800)
    assert result.reason=="unsupported-dimension"

def test_conflicting_independent_measurements_require_explicit_resolution(harness):
    _,_,client=harness;c=CaptureView.model_validate(confirmed(client))
    p=c.photos[0]
    first=DimensionEvidence(field="widthM",valueM=6,photoId=p.id,photoHash=p.sha256)
    second=first.model_copy(update={"valueM":7})
    draft=c.draft.model_copy(update={"dimensionEvidence":(first,second)})
    _,issues=validate_capture_rectangle(c.model_copy(update={"draft":draft}))
    assert "dimension-conflict" in {i.code for i in issues}
    draft=draft.model_copy(update={"dimensionEvidence":tuple(e.model_copy(update={"overrideReason":"Tape measured 6 m; marker plane was unreliable."}) for e in (first,second))})
    room,issues=validate_capture_rectangle(c.model_copy(update={"draft":draft}))
    assert room is not None and not issues
