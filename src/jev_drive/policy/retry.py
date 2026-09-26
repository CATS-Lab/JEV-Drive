"""Convert Retry-After to a wall-clock wait; simulation time is unaffected."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def retry_delay(header, backoff_s, now=None):
    if header:
        try:
            seconds = float(header)
        except ValueError:
            try:
                date = parsedate_to_datetime(header)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = (date - (now or datetime.now(timezone.utc))).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = None
        if seconds is not None and math.isfinite(seconds) and seconds >= 0:
            # Even a zero header must not produce a busy retry loop.
            return max(1.0, seconds)
    return backoff_s
