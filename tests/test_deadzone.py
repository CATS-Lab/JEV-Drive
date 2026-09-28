import pytest
from jev_drive.config import Config
from jev_drive.control.action_mapping import centered_score, continuous_commands


@pytest.mark.parametrize('score', [3.9, 3.999, 4, 4.001, 4.1])
def test_neutral_interval_includes_boundaries(score):
    assert continuous_commands(score, score, Config()) == (0, 0)


def test_deadzone_continuity_symmetry_endpoints_and_disabled():
    for score in [0, 1.2, 3.899999, 4.100001, 6.8, 8]:
        assert centered_score(score, .1) == pytest.approx(-centered_score(8-score, .1))
        assert centered_score(score, 0) == pytest.approx(score-4)
    assert abs(centered_score(4.1+1e-8, .1)) < 2e-8
    assert abs(centered_score(3.9-1e-8, .1)) < 2e-8
    assert continuous_commands(0,8,Config()) == (-1, .06)


@pytest.mark.parametrize('width', [-.1, 4, float('nan'), float('inf'), True])
def test_invalid_deadzone_rejected(width):
    with pytest.raises(ValueError):Config(score_deadzone=width)
