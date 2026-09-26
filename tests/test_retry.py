from datetime import datetime, timezone
import pytest
from jev_drive.config import Config
from jev_drive.policy.retry import retry_delay


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, 5),
        ("bad", 5),
        ("nan", 5),
        ("inf", 5),
        ("-1", 5),
        ("0", 1),
        ("30", 30),
        ("120", 120),
        ("Sat, 26 Sep 2026 12:01:00 GMT", 60),
    ],
)
def test_retry_after(header, expected):
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    assert retry_delay(header, 5, now) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"retry_429": "yes"},
        {"retry_initial_s": 0},
        {"retry_initial_s": 61, "retry_max_s": 60},
        {"api_min_interval_s": -1},
        {"api_min_interval_s": float("nan")},
    ],
)
def test_invalid_retry_configuration(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)
