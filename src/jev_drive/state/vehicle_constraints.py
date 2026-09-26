"""Command/vehicle bounds without state-dependent driving recommendations."""


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
    return {name: getattr(config, name) for name in fields}
