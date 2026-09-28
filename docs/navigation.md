# Road-level navigation

English | [简体中文](navigation.zh-CN.md)

JEV receives an ordered list of **road corridors**, each containing adjacent same-direction lane IDs. These are map-derived road sections, not official street names or road IDs. JEV chooses its lane, maneuver timing, speed and steering. No recorded intermediate ego waypoints or GT lane-change schedule are sent.

```json
{
  "mode": "road_corridor",
  "source": "map_topology",
  "destination_source": "recorded_trip_endpoint_only",
  "availability": "available",
  "corridors": [
    {"id": "corridor:A", "lane_ids": ["A1", "A2"]},
    {"id": "corridor:B", "lane_ids": ["B1", "B2"]}
  ],
  "destination_corridor_id": "corridor:B"
}
```

This illustrative route means: proceed through road section A toward B. It does not prescribe a particular lane or imply permission to cross lane markings. Lane geometry and direction remain in `road.lanes`; the corridor sequence selects the intended branch at a junction without supplying a driving trajectory. Lane IDs beyond the local map ROI become geometrically visible as the ego approaches.

## Destination and route generation

Set `navigation_destination_world_m` to `[x, y, z]` in the configuration to choose a destination in the scene's world coordinates. By default, the adapter reads **only the recorded trip's final position** to select the destination road section. It does not use the intermediate recorded path, final speed or final heading. Thus the default still uses a recording-derived destination, but does not reveal how the recorded vehicle reached it. The target is the road section, not a parking pose or exact stopping point.

The builder groups explicitly adjacent lanes whose local directions agree within 60 degrees, then builds directed connections from map successors. A shortest-path search weighted by section lengths selects a corridor sequence from the current ego road section to the destination section. Current position matching uses ego heading; the destination only selects a section. Matching farther than 6 metres from a centerline is rejected. Grouping is a conservative topology approximation, not a guarantee that every lateral transition is legal or feasible; JEV must inspect markings, lane connections and traffic.

Missing destinations, unmatched positions and disconnected routes produce `availability: "unavailable"` with a reason. The prompt asks JEV to slow or stop safely; there is no fallback to GT waypoints or automatic safety takeover. This is navigation on the available local scene map, not a city-scale routing service. New snapshots carry an empty legacy `route_world` and a separate destination; archived snapshots may supply only their final route point for compatibility.

The navigation implementation is isolated in [navigation.py](../src/jev_drive/state/navigation.py). Prompt version `jev-drive-v1.2` explains corridor semantics for both Score and Choice. Existing rollout GIFs and decision logs predate this change and are not evidence of its driving performance.
