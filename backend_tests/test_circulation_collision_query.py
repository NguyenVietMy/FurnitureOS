"""Exact SAT parity and bounded work for repeated clearance-grid collision queries."""
from math import cos, sin
from random import Random
import api.circulation as circulation


def rectangle(x, z, width, depth, yaw=0):
    c, s = cos(yaw), sin(yaw)
    return tuple((x + a*c - b*s, z + a*s + b*c)
                 for a,b in [(-width/2,-depth/2),(width/2,-depth/2),(width/2,depth/2),(-width/2,depth/2)])


def test_prepared_query_matches_original_sat_for_sweeps_rotations_and_tolerance_edges():
    rng = Random(430315)
    obstacles = tuple((str(i % 5), rectangle(rng.uniform(-5,5),rng.uniform(-5,5),rng.uniform(.1,2),rng.uniform(.1,2),rng.uniform(-3.14,3.14))) for i in range(18))
    query = circulation._collision_query(obstacles)
    for i in range(400):
        x,z = rng.uniform(-6,6),rng.uniform(-6,6)
        polygon = (circulation._walker_polygon((x,z),.6) if i % 3 == 0 else
                   circulation._swept_polygon((x,z),(x+rng.uniform(-.2,.2),z+rng.uniform(-.2,.2)),.6) if i % 3 == 1 else
                   rectangle(x,z,.6,.8,rng.uniform(-3.14,3.14)))
        assert query(polygon) == circulation._collisions(polygon,obstacles)
    for gap in [-1e-8,-1e-9,-1e-10,0,1e-10,1e-9,1e-8]:
        obstacle = (('edge',rectangle(1+gap,0,1,1)),)
        query = circulation._collision_query(obstacle)
        for polygon in [rectangle(0,0,1,1),rectangle(0,0,1,1,1e-10)]:
            assert query(polygon) == circulation._collisions(polygon,obstacle)


def test_distant_grid_obstacles_do_not_repeat_sat_but_rotated_potential_collisions_still_do(monkeypatch):
    obstacles = tuple((str(i),rectangle(10+i*2,10,1,1)) for i in range(6)) + (('near',rectangle(0,0,1,1,.2)),)
    query = circulation._collision_query(obstacles)
    calls=[];original=circulation._polygons_overlap
    def observed(first,second,tolerance):
        calls.append(second)
        return original(first,second,tolerance)
    monkeypatch.setattr(circulation,'_polygons_overlap',observed)
    assert query(circulation._walker_polygon((0,0),.6)) == ('near',)
    assert calls == [obstacles[-1][1]]


def test_cardinal_sweeps_match_original_convex_hull_exactly_without_rebuilding_it(monkeypatch):
    rng = Random(61030)
    cases=[]
    for _ in range(300):
        x,z = rng.uniform(-20,20),rng.uniform(-20,20)
        for end in [(x,z),(x+.05,z),(x-.05,z),(x,z+.05),(x,z-.05)]:
            cases.append(((x,z),end,.6))
    expected=[circulation._convex_hull((*circulation._walker_polygon(start,width),*circulation._walker_polygon(end,width))) for start,end,width in cases]
    def unexpected(_points):
        raise AssertionError('Cardinal lattice edges must not rebuild the identical convex hull.')
    monkeypatch.setattr(circulation,'_convex_hull',unexpected)
    assert [circulation._swept_polygon(start,end,width) for start,end,width in cases] == expected


def test_replacement_cache_preserves_entire_result_and_witness_and_falls_back_on_changed_room():
    from api.design import resolve_fixture
    from api.domain import rectangular_room_shell
    from api.models import FixtureSelectionRequest
    from backend_tests.catalogue_fixtures import original_published_catalogue
    design = resolve_fixture(FixtureSelectionRequest(fixtureId='zoned-repairable',maxCandidates=256),original_published_catalogue())
    assert design.status=='solved'
    variable=design.placements[0].instanceId
    moved=design.model_copy(update={'placements':(design.placements[0].model_copy(update={'position':(0,design.placements[0].position[1],0)}),*design.placements[1:])})
    changed=design.model_copy(update={'room':rectangular_room_shell('cache-changed-room',8,8,3)})
    static_moved=design.model_copy(update={'placements':(design.placements[0],design.placements[1].model_copy(update={'position':(0,design.placements[1].position[1],0)}),*design.placements[2:])})
    cases=[design,moved,changed,static_moved]
    expected=[circulation.validate_circulation_with_witness(d,.6) for d in cases]
    wider=circulation.validate_circulation_with_witness(design,.8)
    with circulation.reuse_static_clearance(design,variable,.6) as cache:
        actual=[circulation.validate_circulation_with_witness(d,.6) for d in cases]
        assert actual==expected
        assert 0<len(cache.results)<=circulation.MAX_REUSED_CLEARANCE_POLYGONS
        assert circulation.validate_circulation_with_witness(design,.8)==wider
    assert not cache.results and circulation._STATIC_CLEARANCE.get() is None


def test_static_clearance_cache_is_bounded_and_reset_on_failure(monkeypatch):
    import pytest
    from api.design import resolve_fixture
    from api.models import FixtureSelectionRequest
    from backend_tests.catalogue_fixtures import original_published_catalogue
    design=resolve_fixture(FixtureSelectionRequest(fixtureId='zoned-repairable',maxCandidates=256),original_published_catalogue())
    monkeypatch.setattr(circulation,'MAX_REUSED_CLEARANCE_POLYGONS',2)
    with pytest.raises(RuntimeError,match='controlled'):
        with circulation.reuse_static_clearance(design,design.placements[0].instanceId,.6) as cache:
            for x in [-2,-1,0,1,2]:cache.free(circulation._walker_polygon((x,0),.6))
            assert len(cache.results)==2
            raise RuntimeError('controlled')
    assert not cache.results and circulation._STATIC_CLEARANCE.get() is None


def test_prepared_polygon_projection_is_used_without_recomputation(monkeypatch):
    polygon=circulation._walker_polygon((0,0),.6)
    obstacles=(('near',rectangle(0,0,1,1)),('far',rectangle(10,10,1,1)))
    expected=circulation._collisions(polygon,obstacles)
    projection=circulation._polygon_projection(polygon)
    query=circulation._collision_query(obstacles)
    def unexpected(_polygon):raise AssertionError('Exact cached projection must be reused')
    monkeypatch.setattr(circulation,'_polygon_projection',unexpected)
    assert query(polygon,projection)==expected


def test_strictly_disjoint_cached_axes_need_no_interval_math_or_sat(monkeypatch):
    polygon=circulation._walker_polygon((0,0),.6)
    projection=circulation._polygon_projection(polygon)
    query=circulation._collision_query((('far-x',rectangle(10,0,1,1)),('far-z',rectangle(0,10,1,1))))
    def unexpected(*_args):raise AssertionError('Separated exact SAT axis needs no further overlap work')
    monkeypatch.setattr(circulation,'min',unexpected,raising=False)
    monkeypatch.setattr(circulation,'max',unexpected,raising=False)
    monkeypatch.setattr(circulation,'_collisions',unexpected)
    assert query(polygon,projection)==()


def test_nearest_order_reuse_matches_exact_sort_for_changing_free_grids_and_has_a_node_cap(monkeypatch):
    from api.domain import rectangular_room_shell
    geometry=circulation._prepare_room_geometry(rectangular_room_shell('nearest-cache',2,2,3))
    targets=frozenset({(0.,0.),(.1,.2)})
    cache=circulation._StaticClearanceCache(geometry,'variable',.6,(),known_targets=targets)
    monkeypatch.setattr(circulation,'MAX_REUSED_NEAREST_NODES',200)
    assert cache.prepare_lattice(-.3,-.3,12,12)
    rng=Random(300315)
    for _ in range(50):
        grid={k:p for k,p in cache.lattice.items() if rng.random()<.4}
        target=(0.,0.)
        expected=sorted(grid.items(),key=lambda item: (circulation.hypot(item[1][0]-target[0],item[1][1]-target[1]),item[0][1],item[0][0]))[:16]
        assert cache.nearest(target,grid)==expected
    assert cache.ordered_nodes==144 and len(cache.orders)==1
    assert cache.nearest((.1,.2),cache.lattice) is None
    assert cache.nearest((.7,.8),cache.lattice) is None
    cache.clear()
    assert not cache.lattice and not cache.orders and not cache.results and cache.ordered_nodes==0


def test_nearest_reuse_keeps_raw_lattice_limits_and_refuses_different_lattice(monkeypatch):
    from api.domain import rectangular_room_shell
    geometry=circulation._prepare_room_geometry(rectangular_room_shell('nearest-cache-limits',2,2,3))
    cache=circulation._StaticClearanceCache(geometry,'variable',.6,())
    assert not cache.prepare_lattice(0,0,circulation.MAX_LATTICE_POINTS_PER_AXIS+1,1)
    assert not cache.prepare_lattice(0,0,500,500)
    assert not cache.lattice
    assert cache.prepare_lattice(-.3,-.3,12,12)
    assert not cache.prepare_lattice(-.2,-.3,12,12)
    monkeypatch.setattr(circulation,'GRID_RESOLUTION_M',.1)
    assert not cache.prepare_lattice(-.3,-.3,12,12)


def test_ordered_rectangle_projection_and_rotated_fallback_match_generic_axes():
    rng=Random(315120)
    for _ in range(1500):
        polygon=rectangle(rng.uniform(-20,20),rng.uniform(-20,20),rng.uniform(.00001,3),rng.uniform(.00001,3),rng.choice([0,.3,1.5707963267948966]))
        for points in [polygon,tuple(reversed(polygon)),polygon[1:]+polygon[:1]]:
            edges=tuple(zip(points,(*points[1:],points[0]),strict=True))
            expected=(min(p[0] for p in points),max(p[0] for p in points),min(p[1] for p in points),max(p[1] for p in points),
                      any(a[0]==b[0] and a[1]!=b[1] for a,b in edges),any(a[1]==b[1] and a[0]!=b[0] for a,b in edges))
            assert circulation._polygon_projection(points)==expected


def test_room_query_matches_original_containment_for_rectangle_l_and_tolerance():
    from api.domain import rectangular_room_shell,l_shaped_room_shell
    rooms=[rectangular_room_shell('rect',10,10,3),l_shaped_room_shell('ell',10,10,2,2,3)]
    rng=Random(300315)
    for room in rooms:
        geometry=circulation._prepare_room_geometry(room)
        query=circulation._room_query(geometry)
        for _ in range(1500):
            polygon=rectangle(rng.uniform(-6,6),rng.uniform(-6,6),rng.uniform(.01,2),rng.uniform(.01,2),rng.choice([0,.2,.7]))
            assert query(polygon)==circulation._inside_prepared_room(geometry,polygon)
        for gap in [-1e-8,-1e-9,-1e-10,0,1e-10,1e-9,1e-8]:
            for x,z in [(5-.3+gap,0),(0,5-.3+gap),(3-.3+gap,-4)]:
                polygon=circulation._walker_polygon((x,z),.6)
                assert query(polygon)==circulation._inside_prepared_room(geometry,polygon)


def test_bounded_nearest_selection_keeps_exact_first16_order_including_ties():
    rng=Random(315016)
    full={(x,z):(x*.05,z*.05) for x in range(-20,21) for z in range(-20,21)}
    for _ in range(100):
        grid={key:p for key,p in full.items() if rng.random()<.7}
        target=rng.choice([(0.,0.),(.1,.1),(.125,-.125)])
        expected=sorted(grid.items(),key=lambda item:(circulation.hypot(item[1][0]-target[0],item[1][1]-target[1]),item[0][1],item[0][0]))[:16]
        assert circulation._nearest_grid_nodes(target,grid)==expected


def test_cardinal_pair_fast_path_is_exact_sat_and_rotated_queries_keep_fallback(monkeypatch):
    import pytest
    rng=Random(315049)
    obstacles=tuple((str(i),rectangle(rng.uniform(-2,2),rng.uniform(-2,2),rng.uniform(.1,2),rng.uniform(.1,2))) for i in range(20))
    query=circulation._collision_query(obstacles)
    for _ in range(300):
        polygon=rectangle(rng.uniform(-3,3),rng.uniform(-3,3),.6,.6,rng.choice([0,.3]))
        assert query(polygon)==circulation._collisions(polygon,obstacles)
    direct=circulation._collision_query((('hit',rectangle(0,0,2,2)),))
    def unexpected(*args):raise AssertionError('Full SAT must remain the rotated fallback')
    monkeypatch.setattr(circulation,'_polygons_overlap',unexpected)
    assert direct(rectangle(0,0,.6,.6))==('hit',)
    with pytest.raises(AssertionError,match='rotated fallback'):
        direct(rectangle(0,0,.6,.6,.3))
