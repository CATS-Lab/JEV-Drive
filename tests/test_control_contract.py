import pytest
from jev_drive.config import Config
from jev_drive.policy.questions import build, VERSION
from jev_drive.state.vehicle_constraints import build as constraints
from jev_drive.control import score_control, choice_control


def answer(level):
    return {'type': 'score', 'score': float(level), 'probabilities': {str(i): float(i == level) for i in range(9)}}


@pytest.mark.parametrize('custom', [False, True])
def test_published_score_actions_equal_executed_actions(custom):
    config = Config()
    if custom:
        config = Config(speed_score_gain=.17, steering_score_gain=.021, max_abs_steering_rad=.3)
    questions = build(config)
    actions = constraints(config)['control_mapping']['actions']
    for level in range(9):
        speed, steering = score_control.commands({'speed': answer(level), 'steering': answer(level)}, config)
        assert speed == actions['speed_delta_mps_by_level'][level]
        assert steering == actions['absolute_steering_rad_by_level'][level]
        assert f'{speed:+.6g} m/s' in questions['speed']['criteria'][level]
        assert f'{steering:+.6g} rad' in questions['steering']['criteria'][level]
    assert VERSION == 'jev-drive-v1.7'


def test_choice_exposes_numeric_actions_and_controller_rules():
    config = Config(mode='choice')
    questions = build(config)
    contract = constraints(config)['control_mapping']
    for speed in ['accelerate', 'hold', 'decelerate']:
        for steer in ['left', 'straight', 'right']:
            answers = {axis: {'type': 'choice', 'choice': label, 'probabilities': {k: float(k == label) for k in questions[axis]['criteria']}} for axis, label in [('speed', speed), ('steering', steer)]}
            dv, angle = choice_control.commands(answers, config)
            assert dv == contract['actions']['speed'][speed]
            assert angle == contract['actions']['steering'][steer]
            assert f'{dv:+.6g} m/s' in questions['speed']['criteria'][speed]
            assert f'{angle:+.6g} rad' in questions['steering']['criteria'][steer]
    assert 'v_old>v_max' in contract['speed_update'][-1]
    assert 'delta_req-delta_old' in contract['steering_update'][0]


@pytest.mark.parametrize('value', [0, 2.25, 3.99, 4, 4.16, 7.75, 8])
def test_fractional_score_matches_published_formula_even_when_mode_differs(value):
    config = Config()
    answers = {'speed': answer(4), 'steering': answer(4)}
    for axis in answers: answers[axis]['score'] = value
    dv, steering = score_control.commands(answers, config)
    mapping = constraints(config)['control_mapping']['score_mapping']
    assert dv == pytest.approx((value - 4) * mapping['speed_score_gain_mps'])
    assert steering == pytest.approx((value - 4) * mapping['steering_score_gain_rad'])
