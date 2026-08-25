"""Utility functions for formatting time values."""

from gettext import gettext as _


def format_hours_to_hm(hours: float) -> str:
    """
    Format a fractional hours value to hours and minutes string.

    Args:
        hours: Fractional hours value (e.g., 10.5 for 10h 30m).

    Returns:
        Formatted string like "10h 30m", "10h", or "30m".
        Zero values are omitted (e.g., 0.5h -> "30m", 10h -> "10h").
    """
    h = int(hours)
    m = int((hours - h) * 60)
    if h > 0 and m > 0:
        return f"{h}h {m}m"
    if h > 0:
        return f"{h}h"
    return f"{m}m"


def format_seconds(seconds: float, compact: bool = False) -> str:
    """
    Format a number of seconds into a human-readable time string.

    Args:
        seconds: Positive number of seconds.
        compact: If True, omit spaces and zero-valued components
            (e.g. "3s", "2m5s", "1h30m" vs "3s", "2m 5s", "1h 30m").

    Returns:
        Formatted time string.
    """
    sep = "" if compact else " "

    if seconds < 60:
        return _("{:.0f}s").format(seconds)
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        if compact and secs == 0:
            return _("{}m").format(minutes)
        return _("{}m" + sep + "{}s").format(minutes, secs)
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        if compact and mins == 0:
            return _("{}h").format(hours)
        return _("{}h" + sep + "{}m").format(hours, mins)


def format_clock(seconds: float) -> str:
    """
    Format a number of seconds as a clock reading.

    Args:
        seconds: Positive number of seconds.

    Returns:
        ``MM:SS``, widening to ``H:MM:SS`` past an hour. Unlike
        :func:`format_seconds` the seconds are always shown, so a
        job estimate reads at a glance and stays comparable as it
        moves.
    """
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
