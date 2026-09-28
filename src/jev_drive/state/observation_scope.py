"""Describe observation limits without claiming complete object coverage."""


def build(config, actor_audit):
    return {
        "actor_roi_m": list(config.actor_roi),
        "selection": "actor center inside ROI, then nearest K after overlap filtering",
        "max_actors": config.max_actors,
        "roi_candidate_count": actor_audit["roi_candidate_count"],
        "selected_count": len(actor_audit["selected_ids"]),
        "omitted_by_nearest_k": actor_audit["omitted_by_nearest_k"],
        "overlap_filter_enabled": config.actor_overlap_filter,
        "unlisted_space_is_not_verified_clear": True,
        "actor_velocity": "actor minus ego translational velocity, expressed in current ego axes; not the derivative in a rotating frame",
        "actor_position": "actor bounding-box center in ego rig coordinates",
        "ego_position": "rig origin; ego box center is offset by ego.box_center_rig_m",
        "actor_future_trajectories_provided": False,
    }
