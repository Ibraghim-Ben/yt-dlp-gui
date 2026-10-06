from __future__ import annotations
from typing import Callable, Optional
import yt_dlp
from .models import VideoInfo, FormatInfo, PlaylistEntry, MediaType
from .ffmpeg_utils import setup_bundled_binaries, find_quickjs


class _YTDLPLogger:
    def __init__(self, callback: Callable[[str, str], None]):
        self._cb = callback

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug]") and "[download]" not in msg:
            self._cb("debug", msg)

    def info(self, msg: str) -> None:
        if "[download]" not in msg:
            self._cb("info", msg)

    def warning(self, msg: str) -> None:
        self._cb("warning", msg)

    def error(self, msg: str) -> None:
        self._cb("error", msg)


def _classify_media_type(fmt: dict) -> Optional[MediaType]:
    vcodec = fmt.get("vcodec")
    acodec = fmt.get("acodec")
    
    has_video = bool(vcodec) and vcodec != "none"
    has_audio = bool(acodec) and acodec != "none"

    if not has_video and not has_audio:
        ext = fmt.get("ext", "").lower()
        if ext in ("mp4", "mkv", "webm", "mov", "avi", "flv"):
            return MediaType.VIDEO
        if ext in ("mp3", "m4a", "ogg", "opus", "wav", "flac"):
            return MediaType.AUDIO_ONLY
        return None

    if has_video and has_audio:
        return MediaType.VIDEO
    if has_video:
        return MediaType.VIDEO_ONLY
    if has_audio:
        return MediaType.AUDIO_ONLY
    return None


def _normalize_codec(codec: str | None) -> str | None:
    if not codec or codec == "none":
        return None
    c = codec.lower()
    _PREFIX_MAP: list[tuple[tuple[str, ...], str]] = [
        (("hvc1", "hev1"), "H.265"),
        (("avc1", "avc3", "h264"), "H.264"),
        (("vp09", "vp9"), "VP9"),
        (("av01", "av1"), "AV1"),
        (("mp4a",), "AAC"),
        (("opus",), "Opus"),
        (("vorbis",), "Vorbis"),
        (("mp4v",), "MP4V"),
        (("ac-3", "ec-3"), "AC-3"),
    ]
    for prefixes, name in _PREFIX_MAP:
        if c.startswith(prefixes):
            return name
    parts = codec.split(".")
    return parts[0].upper() if len(parts) > 1 else codec


def _parse_format(fmt: dict, duration: Optional[float] = None) -> Optional[FormatInfo]:
    media_type = _classify_media_type(fmt)
    if media_type is None:
        return None
    width = fmt.get("width")
    height = fmt.get("height")
    resolution = fmt.get("resolution") or (f"{width}x{height}" if width and height else None)

    filesize = fmt.get("filesize")
    filesize_approx = fmt.get("filesize_approx")
    if not filesize and not filesize_approx:
        try:
            tbr = float(fmt.get("tbr") or 0)
            dur = float(duration or 0)
            if tbr > 0 and dur > 0:
                filesize_approx = int(tbr * 1000 / 8 * dur)
        except (TypeError, ValueError):
            pass

    return FormatInfo(
        format_id=str(fmt.get("format_id") or ""),
        ext=str(fmt.get("ext") or ""),
        resolution=resolution,
        width=width,
        height=height,
        fps=fmt.get("fps"),
        vcodec=_normalize_codec(fmt.get("vcodec")),
        acodec=_normalize_codec(fmt.get("acodec")),
        filesize=filesize,
        filesize_approx=filesize_approx,
        tbr=fmt.get("tbr"),
        vbr=fmt.get("vbr"),
        abr=fmt.get("abr"),
        asr=fmt.get("asr"),
        media_type=media_type,
        format_note=str(fmt.get("format_note") or ""),
    )


def _get_best_thumbnail_url(info: dict) -> Optional[str]:
    thumbs = info.get("thumbnails")
    if thumbs and isinstance(thumbs, list):
        valid = [t for t in thumbs if isinstance(t, dict) and t.get("url")]
        if valid:
            def _score(t: dict) -> tuple:
                pref = t.get("preference") if t.get("preference") is not None else -1
                w = t.get("width") or 0
                h = t.get("height") or 0
                return (pref, w * h, w)
            best = max(valid, key=_score)
            return best.get("url")
    return info.get("thumbnail")


def _parse_video_info(info: dict, original_url: str) -> VideoInfo:
    raw_formats = info.get("formats", [])
    duration = info.get("duration")
    parsed = [_parse_format(f, duration) for f in raw_formats]

    seen: set[tuple] = set()
    unique: list[FormatInfo] = []
    
    def _parse_priority(fmt: FormatInfo) -> int:
        note = (fmt.format_note or "").lower()
        if "original" in note or "orig" in note:
            return 0
        if "dubbed" in note or "translation" in note:
            return 2
        return 1

    valid_parsed = sorted([f for f in parsed if f is not None], key=_parse_priority)

    for f in valid_parsed:
        size = f.filesize or f.filesize_approx or 0
        note_key = f.format_note if f.media_type == MediaType.AUDIO_ONLY else ""
        key = (f.media_type, f.height, f.fps, f.vcodec, f.acodec, f.ext, round(size / 1024 / 1024), note_key)
        if key not in seen:
            seen.add(key)
            unique.append(f)

    formats = sorted(unique, key=lambda f: f.sort_key)

    is_playlist = info.get("_type") in ("playlist", "multi_video")
    entries: list[PlaylistEntry] = []
    if is_playlist:
        for i, entry in enumerate(info.get("entries", []) or []):
            if entry is None:
                continue
            entries.append(PlaylistEntry(
                url=entry.get("webpage_url") or entry.get("url") or "",
                title=entry.get("title") or f"Video {i + 1}",
                duration=entry.get("duration"),
                uploader=entry.get("uploader") or entry.get("channel"),
                thumbnail=_get_best_thumbnail_url(entry),
                index=i + 1,
                available=entry.get("availability", "public") not in ("private", "premium_only", "subscriber_only", "needs_auth"),
            ))

    subs_dict = info.get("subtitles") or {}
    auto_subs_dict = info.get("automatic_captions") or {}

    detected_orig_lang = ""
    for k in auto_subs_dict:
        if k.endswith("-orig"):
            detected_orig_lang = k[:-5]
            break
    if not detected_orig_lang:
        detected_orig_lang = str(info.get("language") or "")

    manual_subs: list[tuple[str, str]] = []
    for lang_code, subs_list in subs_dict.items():
        if not lang_code or lang_code.endswith("-orig") or lang_code == "live_chat":
            continue
        name = lang_code
        if subs_list and isinstance(subs_list, list) and subs_list[0]:
            name = subs_list[0].get("name") or lang_code
        manual_subs.append((lang_code, name))
    manual_subs.sort(key=lambda x: x[1].lower())

    real_auto_langs = {k[:-5] for k in auto_subs_dict if k.endswith("-orig")}
    if not real_auto_langs and detected_orig_lang and detected_orig_lang in auto_subs_dict:
        real_auto_langs = {detected_orig_lang}

    auto_orig: list[tuple[str, str]] = []
    for lang_code in sorted(real_auto_langs):
        if not lang_code or lang_code in subs_dict or lang_code not in auto_subs_dict:
            continue
        subs_list = auto_subs_dict[lang_code]
        name = lang_code
        if subs_list and isinstance(subs_list, list) and subs_list[0]:
            name = subs_list[0].get("name") or lang_code
        if "auto" not in name.lower():
            name = f"{name} (auto)"
        auto_orig.append((lang_code, name))
    auto_orig.sort(key=lambda x: x[1].lower())

    subtitles = manual_subs + auto_orig

    return VideoInfo(
        url=original_url,
        title=info.get("title") or "Unknown",
        channel=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
        thumbnail=_get_best_thumbnail_url(info),
        webpage_url=info.get("webpage_url"),
        formats=formats,
        is_playlist=is_playlist,
        playlist_title=info.get("title") if is_playlist else None,
        playlist_entries=entries,
        subtitles=subtitles,
        manual_subtitle_langs=frozenset(subs_dict.keys()),
    )


_AUTH_ERROR_NEEDLES = (
    "sign in",
    "login required",
    "http error 401",
    "http error 403",
    "private video",
    "members only",
    "confirm your age",
    "age-restricted",
    "this video is available to",
    "not available in your country",
    "requires authentication",
    "access forbidden",
)


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(needle in msg for needle in _AUTH_ERROR_NEEDLES)


def extract_info(
    url: str,
    cookies_browser: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
    flat_playlist: bool = False,
    ffmpeg_path: Optional[str] = None,
) -> VideoInfo:
    setup_bundled_binaries()

    def noop(level: str, msg: str) -> None:
        pass

    cb = log_callback or noop

    def _build_opts(with_cookies: bool) -> dict:
        opts: dict = {
            "quiet": True,
            "no_warnings": False,
            "extract_flat": "in_playlist" if flat_playlist else False,
        }
        qjs_exe = find_quickjs()
        if qjs_exe:
            opts["js_runtimes"] = {"quickjs": {"path": qjs_exe}}
        if with_cookies and cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)
        if ffmpeg_path:
            opts["ffmpeg_location"] = ffmpeg_path
        if log_callback:
            opts["logger"] = _YTDLPLogger(cb)
        return opts

    auth_required = False

    if cookies_browser:
        try:
            cb("info", "Trying without cookies…")
            with yt_dlp.YoutubeDL(_build_opts(with_cookies=False)) as ydl:
                info = ydl.extract_info(url, download=False)
            cb("info", "No authentication needed — cookies not used")
        except Exception as exc:
            if not _is_auth_error(exc):
                raise
            cb("info", f"Authentication required, retrying with {cookies_browser} cookies…")
            with yt_dlp.YoutubeDL(_build_opts(with_cookies=True)) as ydl:
                info = ydl.extract_info(url, download=False)
            auth_required = True
            cb("info", "Success with cookies")
    else:
        with yt_dlp.YoutubeDL(_build_opts(with_cookies=False)) as ydl:
            info = ydl.extract_info(url, download=False)

    video_info = _parse_video_info(info, url)
    video_info.auth_required = auth_required
    return video_info



def build_ydl_opts(
    *,
    task_id: str,
    output_template: str,
    mode: str,
    selected_format_id: Optional[str],
    audio_format_id: Optional[str],
    target_ext: Optional[str],
    ffmpeg_path: str,
    cookies_browser: Optional[str],
    rate_limit: Optional[str],
    embed_thumbnail: bool,
    embed_metadata: bool,
    embed_subs: bool,
    subs_langs: str,
    manual_sub_langs: frozenset = frozenset(),
    archive_file: Optional[str] = None,
    log_callback: Callable[[str, str], None],
) -> dict:
    setup_bundled_binaries()

    opts: dict = {
        "outtmpl": output_template,
        "logger": _YTDLPLogger(log_callback),
        "continuedl": True,
        "nooverwrites": False,
        "retries": 5,
        "fragment_retries": 5,
        "color": "no_color",
    }

    qjs_exe = find_quickjs()
    if qjs_exe:
        opts["js_runtimes"] = {"quickjs": {"path": qjs_exe}}

    if ffmpeg_path:
        opts["ffmpeg_location"] = ffmpeg_path

    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)

    if rate_limit:
        try:
            val = float(rate_limit[:-1])
            unit = rate_limit[-1].upper()
            mult = 1024 if unit == "K" else 1024 * 1024
            opts["ratelimit"] = int(val * mult)
        except ValueError:
            log_callback("warning", f"Invalid rate limit in config, ignoring: {rate_limit}")

    if archive_file:
        opts["download_archive"] = archive_file

    if selected_format_id:
        if audio_format_id:
            opts["format"] = f"{selected_format_id}+{audio_format_id}"
        else:
            opts["format"] = f"{selected_format_id}+bestaudio[format_note*=original]/bestaudio"
    else:
        if mode == "audio":
            opts["format"] = "bestaudio[format_note*=original]/bestaudio/best"
        else:
            opts["format"] = (
                "bestvideo+bestaudio[format_note*=original]/"
                "bestvideo+bestaudio/best"
            )

    if target_ext and mode != "audio":
        opts["merge_output_format"] = target_ext

    _AUDIO_EXTS = {"mp3", "m4a", "opus", "flac", "wav", "ogg", "aac"}
    postprocessors: list = []
    if mode == "audio" and target_ext and target_ext.lower() in _AUDIO_EXTS:
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": target_ext.lower(),
        })
    if embed_thumbnail:
        supported_exts = ("mp3", "mkv", "mka", "ogg", "opus", "flac", "m4a", "mp4", "mov", "m4v")
        if not target_ext or target_ext.lower() in supported_exts:
            postprocessors.append({"key": "EmbedThumbnail"})
            opts["writethumbnail"] = True
    if embed_subs:
        if subs_langs.strip() == "all":
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = not bool(manual_sub_langs)
            opts["subtitleslangs"] = ["all"]
        else:
            requested_langs = [lang.strip() for lang in subs_langs.split(",") if lang.strip()]
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = any(lang not in manual_sub_langs for lang in requested_langs)
            opts["subtitleslangs"] = requested_langs
        opts["sleep_subtitles"] = 2
        opts["ignoreerrors"] = True
        postprocessors.append({"key": "FFmpegEmbedSubtitle"})
    if embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata"})
    if postprocessors:
        opts["postprocessors"] = postprocessors

    return opts


ERROR_MAP: list[tuple[str, str]] = [
    ("Video unavailable", "Video is unavailable or has been removed"),
    ("Private video", "This video is private"),
    ("Sign in to confirm your age", "Age-restricted — use cookies from your browser"),
    ("Sign in to confirm", "Sign-in required — use cookies from your browser"),
    ("This video is available to", "Members-only content"),
    ("HTTP Error 429", "Too many requests. Try again later or use a proxy"),
    ("HTTP Error 403", "Access forbidden (403)"),
    ("Unsupported URL", "Unsupported URL — yt-dlp does not recognise this link"),
    ("Unable to extract", "Could not extract video info — the URL may be unsupported"),
    ("is not a valid URL", "Invalid URL"),
    ("No video formats found", "No downloadable formats found"),
    ("Postprocessing", "FFmpeg post-processing failed — check FFmpeg path in Settings"),
    ("Conversion failed", "FFmpeg conversion failed — check FFmpeg path in Settings"),
    ("ffmpeg", "FFmpeg error — check FFmpeg path in Settings"),
    ("No space left", "Not enough disk space"),
    ("Permission denied", "Permission denied — check folder write access"),
    ("getaddrinfo failed", "Network error — check your internet connection"),
    ("Connection refused", "Connection refused — check your proxy settings"),
    ("handshake operation timed out", "Connection timed out — check your VPN, proxy, or internet connection"),
    ("Unable to download API page", "Connection timed out — check your VPN, proxy, or internet connection"),
    ("certificate verify failed", "SSL certificate error — check your system date/time or proxy settings"),
    ("[SSL:", "SSL error — check your system date/time or proxy settings"),
]


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    for needle, friendly in ERROR_MAP:
        if needle.lower() in msg.lower():
            return friendly
    return f"Download error: {msg}"
