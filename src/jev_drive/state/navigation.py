"""Route geometry, kept separate from lane and traffic-control facts."""

from .snapshot import SceneSnapshot
from ..config import Config


from .road_graph import clip_resample


def build(snapshot: SceneSnapshot, config: Config) -> dict:
    return {
        "route_segments": clip_resample(
            snapshot.route_world,
            snapshot.ego,
            config.road_roi,
            config.centerline_spacing_m,
        ),
        "source": snapshot.provenance.get("route", "unknown"),
    }
