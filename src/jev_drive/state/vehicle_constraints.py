"""Command/vehicle bounds without state-dependent driving recommendations."""

from ..control.action_mapping import speed_increments, steering_targets, choice_targets


def build(config):
    fields = (
        "min_target_speed_mps",
        "max_target_speed_mps",
        "max_abs_steering_rad",
        "max_acceleration_mps2",
        "max_deceleration_mps2",
        "max_steering_rate_radps",
        "wheelbase_m",
    )
    result = {name: getattr(config, name) for name in fields}
    result["control_mapping"] = {
        "mode": config.mode,
        "selection": "Score: map the returned continuous score in [0,8], not the highest-probability level. Probability ties are valid. Choice: execute returned validated choice label.",
        "actions": ({"speed_delta_mps_by_level": speed_increments(config), "absolute_steering_rad_by_level": steering_targets(config)} if config.mode == "score" else choice_targets(config)),
        "score_mapping": {
            "speed_score_gain_mps": config.speed_score_gain,
            "steering_score_gain_rad": config.steering_score_gain,
            "speed": "dv_req=(answers.speed.score-4)*speed_score_gain_mps",
            "steering": "delta_req=(answers.steering.score-4)*steering_score_gain_rad; absolute target, never add it to the previous steering command",
            "score_source": "Use the API-reported score directly; the recomputed probability-weighted mean is diagnostic only. Integer action-table entries are anchors for this linear mapping before limits.",
        } if config.mode == "score" else None,
        "variables": "dt=decision_dt_s; v_old=ego.current_target_speed_mps; delta_old=ego.commanded_steering_rad; dv_req=selected speed increment; delta_req=selected absolute steering target; clip(x,lo,hi)=max(lo,min(hi,x)); a_up=max_acceleration_mps2; a_down=max_deceleration_mps2; rate=max_steering_rate_radps; v_min/min_target_speed_mps; v_max/max_target_speed_mps; delta_max/max_abs_steering_rad.",
        "speed_update": [
            "dv=clip(dv_req,-a_down*dt,a_up*dt)",
            "v_new=clip(v_old+dv,v_min,v_max)",
            "If v_old>v_max: v_new=max(v_new,v_old-a_down*dt), even for hold/accelerate actions; gradual cap recovery.",
        ],
        "steering_update": [
            "d_delta=clip(delta_req-delta_old,-rate*dt,rate*dt)",
            "delta_new=clip(delta_old+d_delta,-delta_max,delta_max)",
        ],
        "reference": {
            "horizon_s": config.trajectory_horizon_s,
            "frequency_hz": config.trajectory_frequency_hz,
            "curvature": "kappa=tan(delta_new)/wheelbase_m; positive left, negative right; fixed over reference horizon.",
            "speed": "Start at measured ego.speed_mps. Ramp toward v_new with acceleration a_up when below target or -a_down when above; hold v_new once reached. Arc length s(t) is the integral of this speed.",
            "geometry": "For nonzero steering: heading=kappa*s; x=sin(kappa*s)/kappa; y=(1-cos(kappa*s))/kappa. For abs(delta_new)<1e-9: x=s,y=0,heading=0. Coordinates relative to current ego rig.",
            "execution": "MPC tracks this reference; actual motion may differ. Replan after decision_dt_s, not after the whole reference horizon.",
        },
    }
    return result
