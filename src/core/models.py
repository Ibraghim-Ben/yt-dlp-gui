from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union
from ..utils.formatters import format_filesize, format_duration


class DownloadStatus(Enum):
    QUEUED = auto()
    ANALYZING = auto()
    DOWNLOADING = auto()
    PROCESSING = auto()
    DONE = auto()
    ERROR = auto()
    CANCELLED = auto()


class MediaType(Enum):
    VIDEO = auto()
    AUDIO_ONLY = auto()
    VIDEO_ONLY = auto()


@dataclass
class FormatInfo:
    format_id: str
    ext: str
    resolution: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    vcodec: Optional[str]
    acodec: Optional[str]
    filesize: Optional[int]
    filesize_approx: Optional[int]
    tbr: Optional[float]
    vbr: Optional[float]
    abr: Optional[float]
    asr: Optional[float]
    media_type: MediaType
    format_note: str

    @property
    def display_resolution(self) -> str:
        if self.height:
            return f"{self.height}p"
        if self.resolution and self.resolution.lower() != "unknown":
            return self.resolution
            
        note = (self.format_note or "").lower()
        if "p" in note and note.replace("p", "").isdigit():
            return note
            
        fid = (self.format_id or "").lower()
        for prefix in ["dash-", "hls-", "http-"]:
            fid = fid.replace(prefix, "")
        if "p" in fid and fid.replace("p", "").isdigit():
            return fid
        if fid.isdigit():
            return f"{fid}p"
            
        return "—"

    @property
    def display_bitrate(self) -> str:
        if self.abr and self.abr > 0:
            return f"{int(self.abr)} Kbps"
        if self.tbr and self.tbr > 0:
            return f"{int(self.tbr)} Kbps"
        return "—"

    @property
    def display_fps(self) -> str:
        if self.fps and self.fps > 0:
            return f"{int(self.fps)}"
        return "—"

    @property
    def display_vcodec(self) -> str:
        codec_map = {
            "av01": "AV1", "vp9": "VP9", "vp09": "VP9",
            "h264": "H.264", "avc1": "H.264",
            "h265": "H.265", "hev1": "H.265", "hevc": "H.265",
            "vp8": "VP8",
        }
        if not self.vcodec or self.vcodec == "none":
            return "—"
        return codec_map.get(self.vcodec.lower().split(".")[0], self.vcodec)

    @property
    def display_acodec(self) -> str:
        codec_map = {
            "opus": "Opus", "mp4a": "AAC", "aac": "AAC",
            "mp3": "MP3", "vorbis": "Vorbis", "flac": "FLAC",
            "ac3": "AC-3", "eac3": "E-AC-3",
        }
        if not self.acodec or self.acodec == "none":
            return "—"
        return codec_map.get(self.acodec.lower().split(".")[0], self.acodec)

    @property
    def display_size(self) -> str:
        size = self.filesize or self.filesize_approx
        return format_filesize(size)

    @property
    def display_type(self) -> str:
        if self.media_type == MediaType.VIDEO:
            return "Video+Audio"
        if self.media_type == MediaType.AUDIO_ONLY:
            return "Audio"
        return "Video"

    @property
    def sort_key(self) -> tuple:
        try:
            h = int(self.height)
        except (TypeError, ValueError):
            h = 0
        try:
            fps = float(self.fps)
        except (TypeError, ValueError):
            fps = 0.0
        try:
            tbr = float(self.tbr)
        except (TypeError, ValueError):
            tbr = 0.0
        type_order = {MediaType.VIDEO: 0, MediaType.VIDEO_ONLY: 1, MediaType.AUDIO_ONLY: 2}
        return (-h, -fps, -tbr, type_order.get(self.media_type, 9))


@dataclass
class PlaylistEntry:
    url: str
    title: str
    duration: Optional[int]
    uploader: Optional[str]
    thumbnail: Optional[str]
    index: int
    available: bool = True


@dataclass
class VideoInfo:
    url: str
    title: str
    channel: Optional[str]
    duration: Optional[int]
    thumbnail: Optional[str]
    webpage_url: Optional[str]
    formats: list[FormatInfo]
    is_playlist: bool
    playlist_title: Optional[str] = None
    playlist_entries: list[PlaylistEntry] = field(default_factory=list)
    subtitles: list[tuple[str, str]] = field(default_factory=list)
    manual_subtitle_langs: frozenset = field(default_factory=frozenset)
    auth_required: bool = False  # True if cookies were needed to access this URL

    @property
    def display_duration(self) -> str:
        res = format_duration(self.duration)
        return res if res else "—"


@dataclass
class DownloadTask:
    id: str
    url: str
    title: str
    video_info: Optional[VideoInfo]
    selected_format_id: Optional[str]
    audio_format_id: Optional[str]
    output_dir: str
    output_template: str
    mode: str
    target_ext: Optional[str] = None
    embed_subs: bool = False
    subs_langs: str = ""
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    error_message: str = ""
    file_path: str = ""
    thumbnail_url: str = ""
