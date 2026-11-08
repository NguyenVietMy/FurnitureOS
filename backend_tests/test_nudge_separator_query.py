"""Preparation must retain the exact conservative separator, including fallbacks."""
from math import cos,sin
from random import Random
import pytest
from api import nudges


def rectangle(x,z,w,d,yaw=0):
    return tuple((x+a*cos(yaw)+b*sin(yaw),z-a*sin(yaw)+b*cos(yaw))
                 for a,b in ((-w/2,-d/2),(w/2,-d/2),(w/2,d/2),(-w/2,d/2)))


def test_prepared_separator_matches_original_rotations_tolerance_and_fallback():
    rng=Random(315006)
    for index in range(1500):
        moving=rectangle(rng.uniform(-4,4),rng.uniform(-4,4),rng.uniform(.1,2),rng.uniform(.1,2),rng.choice([0,.2,.7,1.5707963267948966]))
        fixed=rectangle(rng.uniform(-4,4),rng.uniform(-4,4),rng.uniform(.1,2),rng.uniform(.1,2),0 if index%3 else .43)
        slack=rng.choice([0,.001,.005])
        query=nudges._separator_query(moving,slack)
        try:expected=nudges._best_separator(moving,fixed,slack,'same reason')
        except nudges.NudgeProofError as e:
            with pytest.raises(nudges.NudgeProofError,match=str(e)):query(fixed,'same reason')
        else:assert query(fixed,'same reason')==expected


def test_prepared_separator_keeps_tiny_margins_and_original_vertex_order_fallback():
    moving=rectangle(0,0,1,1)
    for gap in [0,1e-12,.00001,.001,.005,.02]:
        fixed=rectangle(1+gap,0,1,1)
        for polygon in [fixed,tuple(reversed(fixed)),fixed[1:]+fixed[:1]]:
            query=nudges._separator_query(moving,.005)
            try:expected=nudges._best_separator(moving,polygon,.005,'edge')
            except nudges.NudgeProofError as e:
                with pytest.raises(nudges.NudgeProofError,match=str(e)):query(polygon,'edge')
            else:assert query(polygon,'edge')==expected


def test_witness_compression_keeps_every_edge_and_preserves_turns_and_branches():
    grid={(x,z):(x*.05,z*.05) for x in range(8) for z in range(6)}
    raw={tuple(sorted((a,b))) for a,b in [*(( (x,0),(x+1,0)) for x in range(7)),
                                        *(( (3,z),(3,z+1)) for z in range(5)),
                                        *(( (x,5),(x+1,5)) for x in range(3,7))]}
    segments=nudges._coalesce_witness_edges(raw,grid)
    expanded=set()
    for a,b in segments:
        assert a[0]==b[0] or a[1]==b[1]
        dx=0 if a[0]==b[0] else 1 if b[0]>a[0] else -1
        dz=0 if a[1]==b[1] else 1 if b[1]>a[1] else -1
        current=a
        while current!=b:
            nxt=(current[0]+dx,current[1]+dz);expanded.add(tuple(sorted((current,nxt))));current=nxt
    assert expanded==raw
    assert len(segments)==4
    # A branch remains an endpoint rather than disappearing inside a segment.
    assert sum((3,0) in edge for edge in segments)==3


def test_witness_compression_refuses_to_merge_a_geometric_bend_or_gap():
    grid={(0,0):(0.,0.),(1,0):(.05,0.),(2,0):(.1,.00001),(3,0):(.15,0.)}
    raw={((0,0),(1,0)),((1,0),(2,0)),((2,0),(3,0))}
    assert set(nudges._coalesce_witness_edges(raw,grid))==raw


def test_long_straight_witness_uses_identical_union_and_turning_path_keeps_polygon_cap():
    from types import SimpleNamespace
    def polygons(points):
        keys=list(range(len(points)))
        witness=SimpleNamespace(grid=tuple(zip(keys,points)),clearance_width_m=.6)
        parents={i:None if i==0 else i-1 for i in keys}
        return nudges._fixed_witness_polygons(witness,parents,(),(keys[-1],),float('inf'))
    straight=[(i*.05,0.) for i in range(1001)]
    assert polygons(straight)==(nudges._swept_polygon(straight[0],straight[-1],.6),)
    zigzag=[(0.,0.)]
    for i in range(300):
        x,z=zigzag[-1];zigzag.append((x+.05,z) if i%2 else (x,z+.05))
    with pytest.raises(nudges.NudgeProofError,match='limit is 256'):
        polygons(zigzag)


def test_separator_query_retains_original_axis_omission_for_sub_epsilon_edges():
    moving=((1.,-6.),(2.,-6.5),(3.,-4.5),(2.,-4.))
    fixed=((2.,0.),(2.0000000000000004,0.),(2.0000000000000004,2.),(2.,2.))
    assert nudges._separator_query(moving,.005)(fixed,'tiny')==nudges._best_separator(moving,fixed,.005,'tiny')


def test_witness_compression_stops_at_original_certificate_deadline(monkeypatch):
    monkeypatch.setattr(nudges.time,'monotonic',lambda:2.)
    with pytest.raises(nudges.NudgeProofError,match='timed out'):
        nudges._coalesce_witness_edges({((0,0),(1,0))},{(0,0):(0.,0.),(1,0):(.05,0.)},1.)


def test_fresh_witness_parent_reuse_matches_full_geometric_recheck(monkeypatch):
    from dataclasses import replace
    from api.catalogue import catalogue
    from api.design import FEATURED_PRODUCT_ID
    from api.domain import rectangular_room_shell,footprint_of
    from api.models import Placement
    from api.circulation import validate_circulation_with_witness
    from backend_tests.test_swaps import _design,_product_variant
    base=catalogue.get(FEATURED_PRODUCT_ID)
    product=_product_variant(base,'controlled-cube',dimensionsM=dict(widthM=.6,heightM=.6,depthM=.6),wallContactFaces=[],accessRegions=[dict(face='front',depthM=.6,required=True,purpose='controlled access')])
    placements=(Placement(instanceId='fixed',productId=product.id,position=(-1.5,0,0),yaw=0),Placement(instanceId='moving',productId=product.id,position=(1.5,0,0),yaw=0))
    design=_design(rectangular_room_shell('witness-reuse',6,6,3),(product,product),placements)
    result,witness=validate_circulation_with_witness(design,.6);assert result.status=='clear' and witness is not None
    footprint=footprint_of(product,(1.5,0),0).corners
    original=nudges._collision_query;count=[0]
    def factory(obstacles):
        query=original(obstacles)
        def observed(*args):count[0]+=1;return query(*args)
        return observed
    monkeypatch.setattr(nudges,'_collision_query',factory)
    actual=nudges._safe_backbone(witness,'moving',footprint,float('inf'),True);reused_calls=count[0]
    count[0]=0
    expected=nudges._safe_backbone(replace(witness,parents=()),'moving',footprint,float('inf'),True)
    assert actual==expected
    assert reused_calls<count[0]


def test_walker_support_corner_matches_original_complete_projection_exactly():
    rng=Random(316016)
    for _ in range(1500):
        point=(rng.uniform(-100,100),rng.uniform(-100,100));width=rng.uniform(.00001,3)
        yaw=rng.uniform(-3.14,3.14)
        for axis in [(0.,1.),(1.,0.),(-1.,0.),(0.,-1.),(cos(yaw),sin(yaw))]:
            expected=nudges._axis_projections(nudges._walker_polygon(point,width),axis)[0]
            assert nudges._walker_min_projection(point,width,axis)==expected
