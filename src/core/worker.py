from __future__ import annotations
import yt_dlp
import os
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
    download_finished = pyqtSignal(str, str)
    errored = pyqtSignal(str, str)

    def __init__(self, task: DownloadTask, ydl_opts: dict):
        super().__init__()
        self._task = task
        self._ydl_opts = ydl_opts
        self._cancelled = False
        self._files_to_clean: set[str] = set()

    def run(self) -> None:
        self.status_changed.emit(self._task.id, DownloadStatus.DOWNLOADING.name)
        try:
            ydl_opts = dict(self._ydl_opts)
            ydl_opts["progress_hooks"] = [self._progress_hook]
            ydl_opts["postprocessor_hooks"] = [self._postprocessor_hook]
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self._task.url])
            if not self._cancelled:
                self.download_finished.emit(self._task.id, self._task.output_dir)
        except yt_dlp.utils.DownloadCancelled:
            self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
            self._cleanup_partial_files()
        except Exception as exc:
            self._cleanup_partial_files()
            self.errored.emit(self._task.id, friendly_error(exc))

    def _progress_hook(self, d: dict) -> None:
        filepath = str(d.get("tmpfilename") or d.get("filename") or "")
        if filepath:
            self._files_to_clean.add(filepath)

        if self._cancelled:
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
            speed = str(d.get("_speed_str") or "").strip()
            eta = str(d.get("_eta_str") or "").strip()
            self.progress_updated.emit(self._task.id, pct, speed, eta, filepath)
        elif status == "finished":
            if is_subtitle:
                return
            self.status_changed.emit(self._task.id, DownloadStatus.PROCESSING.name)
            self.progress_updated.emit(self._task.id, 100.0, "", "", "")

    def _cleanup_partial_files(self) -> None:
        import glob
        
        safe_exts = [
            ".jpg", ".webp", ".png", 
            ".vtt", ".srt", ".ass", ".ttml", ".srv3", ".srv2", ".srv1", ".json3", 
            ".info.json", ".description"
        ]

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
            try:
                for match in glob.glob(glob.escape(base_no_ext) + ".*"):
                    if any(match.lower().endswith(ext) for ext in safe_exts):
                        if os.path.exists(match):
                            os.remove(match)
            except OSError:
                pass

    def _postprocessor_hook(self, d: dict) -> None:
        if self._cancelled:
            raise yt_dlp.utils.DownloadCancelled()

    def cancel(self) -> None:
        self._cancelled = True

