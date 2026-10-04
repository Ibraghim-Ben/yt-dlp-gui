from __future__ import annotations


def resolve_container(video_ext: str, audio_acodec: str | None) -> str:
    if video_ext.lower() == "webm":
        acodec = (audio_acodec or "").lower()
        if "opus" not in acodec and "vorbis" not in acodec:
            return "mkv"
    return video_ext
