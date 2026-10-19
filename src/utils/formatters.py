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


def parse_speed_limit(text: str) -> Optional[int]:
    import re
    cleaned = text.strip().lower()
    if not cleaned or cleaned in ("0", "none", "max", "unlimited", "inf"):
        return None
    try:
        from yt_dlp.utils import parse_bytes
        val = parse_bytes(cleaned)
        if val and val > 0:
            return int(val)
    except Exception:
        pass
    m = re.match(r"^([\d.]+)\s*([kmg]?)(?:i?b(?:/s)?)?$", cleaned)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    mult = {"": 1, "k": 1024, "m": 1024 * 1024, "g": 1024 * 1024 * 1024}.get(unit, 1)
    res = int(num * mult)
    return res if res > 0 else None


def format_speed_limit(limit_bytes: Optional[int]) -> str:
    if not limit_bytes or limit_bytes <= 0:
        return ""
    if limit_bytes >= 1_073_741_824:
        return f"{limit_bytes / 1_073_741_824:.1f} GB/s".replace(".0 GB/s", " GB/s")
    if limit_bytes >= 1_048_576:
        return f"{limit_bytes / 1_048_576:.1f} MB/s".replace(".0 MB/s", " MB/s")
    if limit_bytes >= 1024:
        return f"{limit_bytes / 1024:.0f} KB/s"
    return f"{limit_bytes} B/s"
