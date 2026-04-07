"""Timestamp parsing utilities."""

import re


def parse_ts(ts: str) -> float:
    """Convert HH:MM:SS or MM:SS or SS to seconds."""
    ts = ts.strip()
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        else:
            return float(ts)
    except ValueError:
        raise ValueError(f"Invalid timestamp: '{ts}'. Use HH:MM:SS, MM:SS, or seconds.")


def fmt_ts(seconds: float) -> str:
    """Format seconds back to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"
