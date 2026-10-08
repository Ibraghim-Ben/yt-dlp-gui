from __future__ import annotations
import yt_dlp
import os
import re
from PyQt6.QtCore import QThread, pyqtSignal
from .models import DownloadTask, DownloadStatus
from .downloader import friendly_error


class AnalyzeWorker(QThread):
    analyze_finished = pyqtSignal(object)
    error = pyqtSignal(str)
    log = pyqtSignal(str, str)

    def __init__(self, url: str, cookies_browser: str, ffmpeg_path: str = ""):
        super().__init__()
        self._url = url
        self._cookies_browser = cookies_browser
        self._ffmpeg_path = ffmpeg_path

    def run(self) -> None:
        from .downloader import extract_info
        try:
            info = extract_info(
                self._url,
                cookies_browser=self._cookies_browser or None,
                log_callback=lambda lvl, msg: self.log.emit(lvl, msg),
                flat_playlist=True,
                ffmpeg_path=self._ffmpeg_path or None,
            )
            self.analyze_finished.emit(info)
        except Exception as exc:
            self.error.emit(friendly_error(exc))


class DownloadWorker(QThread):
    progress_updated = pyqtSignal(str, float, str, str, str)
    status_changed = pyqtSignal(str, str)
    log_message = pyqtSignal(str, str)
    download_finished = pyqtSignal(str, str, str)
    errored = pyqtSignal(str, str)

    def __init__(self, task: DownloadTask, ydl_opts: dict):
        super().__init__()
        self._task = task
        self._ydl_opts = ydl_opts
        self._cancelled = False
        self._paused = False
        self._files_to_clean: set[str] = set()
        self._last_filepath: str = ""

    def run(self) -> None:
        self.status_changed.emit(self._task.id, DownloadStatus.DOWNLOADING.name)
        try:
            ydl_opts = dict(self._ydl_opts)
            ydl_opts["progress_hooks"] = [self._progress_hook]
            ydl_opts["postprocessor_hooks"] = [self._postprocessor_hook]

            logger = ydl_opts.get("logger")
            if logger and hasattr(logger, "_cb"):
                orig_cb = logger._cb
                def _worker_log_cb(lvl: str, msg: str) -> None:
                    m_thumb = re.search(r'writing video thumbnail(?:\s+\d+)?\s+to:\s*(.+)', msg, re.IGNORECASE)
                    if m_thumb:
                        thumb_path = m_thumb.group(1).strip().strip('"\'')
                        if thumb_path:
                            self._files_to_clean.add(thumb_path)
                    elif "converting thumbnail" in msg.lower():
                        m = re.search(r'["\'](.*?)["\']', msg)
                        if m:
                            self._files_to_clean.add(m.group(1).strip().strip('"\''))
                    if "The download was cancelled" in msg:
                        if self._cancelled:
                            orig_cb("info", "Download cancelled by user")
                            return
                        elif self._paused:
                            orig_cb("info", "Download paused by user")
                            return
                    orig_cb(lvl, msg)
                logger._cb = _worker_log_cb

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self._task.url])
            if not self._cancelled and not self._paused:
                self.download_finished.emit(self._task.id, self._task.output_dir, self._last_filepath)
        except yt_dlp.utils.DownloadCancelled:
            if self._cancelled:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()
            elif self._paused:
                self.status_changed.emit(self._task.id, DownloadStatus.PAUSED.name)
            else:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()
        except Exception as exc:
            self._cleanup_partial_files()
            self.errored.emit(self._task.id, friendly_error(exc))

    def _progress_hook(self, d: dict) -> None:
        filepath = str(d.get("tmpfilename") or d.get("filename") or "")
        if filepath:
            self._files_to_clean.add(filepath)

        if self._cancelled or self._paused:
            raise yt_dlp.utils.DownloadCancelled()

        status = d.get("status")
        filename = str(d.get("filename") or d.get("tmpfilename") or "")

        is_subtitle = any(filename.lower().endswith(ext) for ext in (
            ".vtt", ".srt", ".ass", ".ssa", ".ttml", ".srv3", ".srv2", ".srv1", ".json3"
        ))

        if status == "downloading":
            if is_subtitle:
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100) if total else 0
            speed = yt_dlp.utils.remove_terminal_sequences(str(d.get("_speed_str") or "")).strip()
            eta = yt_dlp.utils.remove_terminal_sequences(str(d.get("_eta_str") or "")).strip()
            self.progress_updated.emit(self._task.id, pct, speed, eta, filepath)
        elif status == "finished":
            if is_subtitle:
                return
            clean = str(d.get("filename") or "")
            if clean and os.path.isfile(clean):
                self._last_filepath = clean
            self.status_changed.emit(self._task.id, DownloadStatus.PROCESSING.name)
            self.progress_updated.emit(self._task.id, 100.0, "", "", "")

    def _cleanup_partial_files(self) -> None:
        import glob
        import re
        
        safe_exts = [
            ".jpg", ".jpeg", ".webp", ".png", 
            ".vtt", ".srt", ".ass", ".ssa", ".ttml", ".srv3", ".srv2", ".srv1", ".json3", 
            ".info.json", ".description"
        ]

        stems: set[str] = set()

        tmpl = self._task.assigned_template or self._task.output_template
        if tmpl:
            try:
                with yt_dlp.YoutubeDL({"outtmpl": tmpl, "quiet": True}) as ydl:
                    prepared = ydl.prepare_filename({
                        "title": self._task.title,
                        "uploader": self._task.video_info.channel if self._task.video_info else self._task.title,
                        "channel": self._task.video_info.channel if self._task.video_info else self._task.title,
                        "id": "",
                        "resolution": "",
                        "format_id": self._task.selected_format_id or "best",
                        "ext": "CHKEXT",
                    })
                    if prepared.endswith(".CHKEXT"):
                        stems.add(prepared[:-7])
            except Exception:
                pass

        for f in self._files_to_clean:
            base = f
            if base.endswith(".part"): base = base[:-5]
            if base.endswith(".ytdl"): base = base[:-5]
            
            for ext in ["", ".part", ".ytdl"]:
                try:
                    path = f + ext
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
            
            base_no_ext = os.path.splitext(base)[0]
            stems.add(base_no_ext)
            clean_stem = re.sub(r'(\.f[a-zA-Z0-9_\-]+|\.temp)$', '', base_no_ext)
            stems.add(clean_stem)

        for stem in stems:
            if not stem:
                continue
            try:
                for match in glob.glob(glob.escape(stem) + "*"):
                    low = match.lower()
                    if any(low.endswith(ext) for ext in safe_exts) or low.endswith(".part") or low.endswith(".ytdl") or ".temp." in low:
                        if os.path.exists(match):
                            os.remove(match)
            except OSError:
                pass

        if self._task.output_dir and os.path.isdir(self._task.output_dir) and self._task.title:
            try:
                clean_title = re.sub(r'[\\/*?:"<>|]', '_', self._task.title)
                prefix = clean_title[:20].strip()
                if prefix:
                    for entry in os.scandir(self._task.output_dir):
                        if entry.is_file():
                            name = entry.name
                            if name.startswith(prefix) and any(name.lower().endswith(ext) for ext in safe_exts):
                                try:
                                    os.remove(entry.path)
                                except OSError:
                                    pass
            except Exception:
                pass

    def _postprocessor_hook(self, d: dict) -> None:
        if self._cancelled or self._paused:
            raise yt_dlp.utils.DownloadCancelled()

        if d.get("status") == "finished":
            final = str(d.get("info_dict", {}).get("filepath") or
                        d.get("info_dict", {}).get("_filename") or
                        d.get("filepath") or "")
            if final and os.path.isfile(final):
                self._last_filepath = final

    def cancel(self) -> None:
        self._cancelled = True
        self._paused = False

    def pause(self) -> None:
        self._paused = True

