from copy import deepcopy
from dataclasses import replace
import pytest
from jev_drive.config import Config
from jev_drive.state.actor_filter import filter_actors
from jev_drive.state.actors import build_with_audit
from test_core import snapshot


def actor(
    key,
    x=0,
    y=0,
    z=0,
    length=4,
    width=2,
    kind="automobile",
    velocity=(5, 0, 0),
    quat=(0, 0, 0, 1),
):
    return dict(
        id=key,
        position_world_m=[x, y, z],
        dimensions_m=[length, width, 2],
        quaternion_xyzw=list(quat),
        source_type=kind,
        velocity_world_mps=list(velocity) if velocity is not None else None,
        velocity_source="past_position_difference",
    )


def ids(actors):
    return [a["id"] for a in actors]


def test_duplicate_keeps_one_and_does_not_mutate():
    records = [actor("b", x=0.1), actor("a")]
    before = deepcopy(records)
    clean, audit = filter_actors(records)
    assert ids(clean) == ["a"] and records == before
    assert audit["removed"][0]["represented_by"] == ["a"]
    assert ids(filter_actors(list(reversed(records)))[0]) == ["a"]


def test_large_box_replaced_by_disjoint_components():
    records = [
        actor("large", length=20, width=3, kind="heavy_truck"),
        actor("front", x=5, length=8, width=2.8, kind="heavy_truck"),
        actor("rear", x=-5, length=8, width=2.8, kind="trailer"),
    ]
    clean, audit = filter_actors(records)
    assert set(ids(clean)) == {"front", "rear"}
    assert audit["removed"][0]["reason"] == "enclosing_multiple_components"


@pytest.mark.parametrize(
    "other",
    [
        actor("b", x=3),  # partial bumper overlap
        actor("b", z=5),  # separate vertical road level
        actor("b", quat=(0, 0, 1, 0)),  # opposing heading
        actor("b", x=0.7, velocity=(10, 0, 0)),  # incompatible motion
        actor("b", kind="pedestrian"),  # different physical object class
        actor("b", x=0.7, velocity=None),  # insufficient evidence
    ],
)
def test_ambiguous_overlaps_not_deleted(other):
    clean, audit = filter_actors([actor("a"), other])
    assert len(clean) == 2 and not audit["removed"]
    assert audit["retained_overlap_pairs"]


def test_no_transitive_suppression():
    clean, _ = filter_actors([actor("a", x=0), actor("b", x=0.7), actor("c", x=1.4)])
    assert ids(clean) == ["a", "c"]


def test_filter_precedes_nearest_k_and_can_be_disabled():
    snap = replace(
        snapshot(), actors=[actor("a", x=5), actor("b", x=5.1), actor("c", x=12)]
    )
    clean, audit = build_with_audit(snap, Config(max_actors=2))
    assert ids(clean) == ["a", "c"]
    assert audit["selected_ids"] == ["a", "c"]
    raw, _ = build_with_audit(snap, Config(max_actors=2, actor_overlap_filter=False))
    assert ids(raw) == ["a", "b"]


def test_filter_rejects_repeated_ids():
    with pytest.raises(ValueError, match="duplicate actor IDs"):
        filter_actors([actor("a"), actor("a")])


def test_nearly_coincident_geometry_can_override_noisy_velocity():
    clean, audit = filter_actors([actor("a"), actor("b", x=0.05, velocity=(30, 0, 0))])
    assert ids(clean) == ["a"]
    assert audit["removed"][0]["overlap"]["velocity_difference_mps"] == 25


def test_large_box_does_not_suppress_a_single_small_vehicle():
    clean, audit = filter_actors(
        [actor("truck", length=20, width=3, kind="heavy_truck"), actor("car")]
    )
    assert len(clean) == 2 and not audit["removed"]


def test_audit_is_separate_from_model_state_and_snapshot_provenance():
    from jev_drive.state.state_builder import JevStateBuilder

    snap = replace(snapshot(), actors=[actor("a", x=5), actor("b", x=5.1)])
    before = deepcopy(snap.provenance)
    envelope = JevStateBuilder(Config()).build(snap)
    assert [a["id"] for a in envelope["state"]["actors"]] == ["a"]
    assert envelope["provenance"]["actor_filter"]["removed"][0]["id"] == "b"
    assert "actor_filter" not in envelope["state"]
    assert snap.provenance == before
