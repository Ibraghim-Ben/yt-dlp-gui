from __future__ import annotations


def format_duration(seconds: float | int | None) -> str:
    if not seconds:
        return ""
    try:
        dur = int(float(seconds))
        m, s = divmod(dur, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except (TypeError, ValueError):
        return ""


def format_filesize(size: int | float | None) -> str:
    if not size:
        return "—"
    try:
        val = float(size)
        if val >= 1_073_741_824:
            return f"{val / 1_073_741_824:.1f} GB"
        if val >= 1_048_576:
            return f"{val / 1_048_576:.1f} MB"
        return f"{val / 1024:.0f} KB"
    except (TypeError, ValueError):
        return "—"
