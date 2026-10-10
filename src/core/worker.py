from __future__ import annotations
import yt_dlp
import os
import re
import sys
import subprocess
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from typing import Optional
from .models import DownloadTask, DownloadStatus
from .downloader import friendly_error

_orig_popen = subprocess.Popen
_worker_subprocs: dict[int, set[subprocess.Popen]] = {}
_subproc_lock = threading.Lock()

def _tracked_popen(*args, **kwargs):
    if os.name == "nt" and "creationflags" not in kwargs:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = _orig_popen(*args, **kwargs)
    ident = threading.current_thread().ident
    with _subproc_lock:
        if ident in _worker_subprocs:
            _worker_subprocs[ident].add(proc)
    return proc

subprocess.Popen = _tracked_popen


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
        self._stopping_live = False
        self._ydl = None
        self._thread_ident: Optional[int] = None
        self._files_to_clean: set[str] = set()
        self._last_filepath: str = ""

    def run(self) -> None:
        ident = threading.current_thread().ident
        self._thread_ident = ident
        with _subproc_lock:
            _worker_subprocs[ident] = set()

        self.status_changed.emit(self._task.id, DownloadStatus.DOWNLOADING.name)
        last_error_message = ""
        try:
            ydl_opts = dict(self._ydl_opts)
            ydl_opts["progress_hooks"] = [self._progress_hook]
            ydl_opts["postprocessor_hooks"] = [self._postprocessor_hook]

            logger = ydl_opts.get("logger")
            if logger and hasattr(logger, "_cb"):
                orig_cb = logger._cb
                def _worker_log_cb(lvl: str, msg: str) -> None:
                    nonlocal last_error_message
                    if lvl == "error":
                        last_error_message = msg
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

            ret = 0
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self._ydl = ydl
                ret = ydl.download([self._task.url])
                self._ydl = None

            if self._stopping_live:
                self._handle_live_stream_finish()
            elif not self._cancelled and not self._paused:
                media_ok = bool(self._last_filepath and os.path.isfile(self._last_filepath) and os.path.getsize(self._last_filepath) > 0)
                if not media_ok:
                    salvaged = self._salvage_live_file()
                    if salvaged:
                        self._last_filepath = salvaged
                        media_ok = True

                if ret != 0 or not media_ok:
                    self._cleanup_partial_files()
                    err_text = last_error_message or ("Download failed: output file not found" if not media_ok else f"Download failed (code {ret})")
                    self.errored.emit(self._task.id, friendly_error(err_text))
                else:
                    self.download_finished.emit(self._task.id, self._task.output_dir, self._last_filepath)
        except yt_dlp.utils.DownloadCancelled:
            if self._stopping_live:
                self._handle_live_stream_finish()
            elif self._cancelled:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()
            elif self._paused:
                self.status_changed.emit(self._task.id, DownloadStatus.PAUSED.name)
            else:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()
        except Exception as exc:
            if self._stopping_live:
                self._handle_live_stream_finish()
            else:
                self._cleanup_partial_files()
                self.errored.emit(self._task.id, friendly_error(exc))
        finally:
            with _subproc_lock:
                _worker_subprocs.pop(ident, None)

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

    def stop_and_save(self) -> None:
        self._stopping_live = True
        self._cancelled = True
        self._paused = False
        self._kill_child_ffmpeg()

    def _kill_child_ffmpeg(self) -> None:
        killed_tracked = False
        if self._thread_ident:
            with _subproc_lock:
                procs = list(_worker_subprocs.get(self._thread_ident, []))
            for p in procs:
                try:
                    p.kill()
                    killed_tracked = True
                except Exception:
                    pass

        if killed_tracked:
            return

        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            TH32CS_SNAPPROCESS = 0x00000002
            PROCESS_TERMINATE = 0x0001

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            try:
                kernel32 = ctypes.windll.kernel32
                current_pid = os.getpid()
                h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                if h_snap and h_snap != -1:
                    pe = PROCESSENTRY32()
                    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
                    if kernel32.Process32First(h_snap, ctypes.byref(pe)):
                        while True:
                            if pe.th32ParentProcessID == current_pid:
                                exe_name = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                                if "ffmpeg" in exe_name:
                                    hp = kernel32.OpenProcess(PROCESS_TERMINATE, False, pe.th32ProcessID)
                                    if hp:
                                        kernel32.TerminateProcess(hp, 0)
                                        kernel32.CloseHandle(hp)
                            if not kernel32.Process32Next(h_snap, ctypes.byref(pe)):
                                break
                    kernel32.CloseHandle(h_snap)
            except Exception:
                pass

            try:
                import subprocess
                pid = os.getpid()
                ps_cmd = (
                    f"Get-CimInstance Win32_Process | "
                    f"Where-Object {{ $_.ParentProcessId -eq {pid} -and $_.Name -like '*ffmpeg*' }} | "
                    f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
                )
                cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                    capture_output=True, timeout=5, creationflags=cflags
                )
            except Exception:
                pass
        else:
            import subprocess
            try:
                subprocess.run(["pkill", "-P", str(os.getpid()), "ffmpeg"], capture_output=True, timeout=3)
            except Exception:
                pass

    def cancel(self) -> None:
        self._cancelled = True
        self._paused = False
        self._kill_child_ffmpeg()

    def pause(self) -> None:
        self._paused = True

    def _handle_live_stream_finish(self) -> None:
        final_file = self._finalize_live_stream()
        if final_file and os.path.exists(final_file) and os.path.getsize(final_file) > 0:
            self.download_finished.emit(self._task.id, self._task.output_dir, final_file)
        else:
            salvaged = self._salvage_live_file()
            if salvaged and os.path.exists(salvaged) and os.path.getsize(salvaged) > 0:
                self.download_finished.emit(self._task.id, self._task.output_dir, salvaged)
            else:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()

    def _finalize_live_stream(self) -> Optional[str]:
        from .ffmpeg_utils import find_ffmpeg
        import subprocess
        import re

        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin:
            return None

        cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        probe_bin = os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if not os.path.isfile(probe_bin):
            probe_bin = ""

        media_candidates: list[str] = []
        thumb_candidates: list[str] = []

        if self._last_filepath and os.path.isfile(self._last_filepath) and os.path.getsize(self._last_filepath) > 0:
            media_candidates.append(self._last_filepath)

        for f in self._files_to_clean:
            if f and os.path.isfile(f) and os.path.getsize(f) > 0:
                ext = f.lower()
                if ext.endswith((".webp", ".jpg", ".jpeg", ".png")):
                    if f not in thumb_candidates:
                        thumb_candidates.append(f)
                elif not ext.endswith((".json", ".vtt", ".srt", ".description")):
                    if f not in media_candidates:
                        media_candidates.append(f)

        if self._task.output_dir and os.path.isdir(self._task.output_dir):
            clean_title = re.sub(r'[\\/*?:"<>|]', '_', self._task.title)[:20].strip()
            for entry in os.scandir(self._task.output_dir):
                if entry.is_file() and os.path.getsize(entry.path) > 0:
                    ext = entry.name.lower()
                    if clean_title and entry.name.startswith(clean_title):
                        if ext.endswith((".webp", ".jpg", ".jpeg", ".png")):
                            if entry.path not in thumb_candidates:
                                thumb_candidates.append(entry.path)
                        elif not ext.endswith((".json", ".vtt", ".srt", ".description")):
                            if entry.path not in media_candidates:
                                media_candidates.append(entry.path)

        if not media_candidates:
            return None

        def inspect_streams(path: str) -> tuple[bool, bool]:
            cmd = [probe_bin or ffmpeg_bin, path] if probe_bin else [ffmpeg_bin, "-i", path]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=cflags)
                text = r.stderr or r.stdout
                has_v = ": Video:" in text
                has_a = ": Audio:" in text
                return (has_v, has_a)
            except Exception:
                return (False, False)

        video_files: list[str] = []
        audio_files: list[str] = []
        muxed_files: list[str] = []

        for f in media_candidates:
            has_v, has_a = inspect_streams(f)
            if has_v and has_a:
                muxed_files.append(f)
            elif has_v:
                video_files.append(f)
            elif has_a:
                audio_files.append(f)

        video_files.sort(key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0, reverse=True)
        audio_files.sort(key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0, reverse=True)
        muxed_files.sort(key=lambda p: os.path.getsize(p) if os.path.exists(p) else 0, reverse=True)

        target_ext = (self._task.target_ext or ("mp3" if self._task.mode == "audio" else "mp4")).lstrip(".").lower()

        primary_file = (
            muxed_files[0] if muxed_files
            else (video_files[0] if (video_files and self._task.mode != "audio")
            else (audio_files[0] if audio_files else media_candidates[0]))
        )

        base = primary_file
        if base.endswith(".part"): base = base[:-5]
        if base.endswith(".ytdl"): base = base[:-5]
        base_no_ext = os.path.splitext(base)[0]
        base_no_ext = re.sub(r'(\.f[a-zA-Z0-9_\-]+|\.temp)$', '', base_no_ext)
        target_file = f"{base_no_ext}.{target_ext}"
        temp_target = f"{base_no_ext}.finalizing.{target_ext}"

        thumb_jpg: Optional[str] = None
        orig_thumb: Optional[str] = None
        if self._task.embed_thumbnail and thumb_candidates and target_ext in ("mp4", "mkv", "m4a", "mp3"):
            raw_thumb = thumb_candidates[0]
            if os.path.exists(raw_thumb) and os.path.getsize(raw_thumb) > 0:
                orig_thumb = raw_thumb
                if raw_thumb.lower().endswith((".jpg", ".jpeg")):
                    thumb_jpg = raw_thumb
                else:
                    temp_jpg = f"{base_no_ext}.thumb_temp.jpg"
                    try:
                        res = subprocess.run(
                            [ffmpeg_bin, "-y", "-i", raw_thumb, temp_jpg],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=15, creationflags=cflags
                        )
                        if res.returncode == 0 and os.path.exists(temp_jpg):
                            thumb_jpg = temp_jpg
                    except Exception:
                        pass

        if video_files and audio_files and self._task.mode != "audio":
            vid = video_files[0]
            aud = audio_files[0]
            cmd = [ffmpeg_bin, "-y", "-i", vid, "-i", aud]
            if thumb_jpg and os.path.exists(thumb_jpg) and target_ext == "mp4":
                cmd += [
                    "-i", thumb_jpg,
                    "-map", "0:v:0", "-map", "1:a:0", "-map", "2:v:0",
                    "-c", "copy",
                    "-disposition:v:1", "attached_pic"
                ]
            else:
                cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c", "copy"]
            cmd.append(temp_target)

            try:
                proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, creationflags=cflags)
                if proc.returncode == 0 and os.path.exists(temp_target) and os.path.getsize(temp_target) > 0:
                    import glob
                    for f in (vid, aud):
                        try: os.remove(f)
                        except OSError: pass
                        for extra in glob.glob(glob.escape(f) + "*"):
                            try: os.remove(extra)
                            except OSError: pass
                        if f.endswith(".part"):
                            for extra in glob.glob(glob.escape(f[:-5]) + "*"):
                                if extra not in (target_file, temp_target):
                                    try: os.remove(extra)
                                    except OSError: pass
                    if orig_thumb and os.path.exists(orig_thumb):
                        try: os.remove(orig_thumb)
                        except OSError: pass
                    if thumb_jpg and thumb_jpg != orig_thumb and os.path.exists(thumb_jpg):
                        try: os.remove(thumb_jpg)
                        except OSError: pass
                    if os.path.exists(target_file):
                        try: os.remove(target_file)
                        except OSError: pass
                    os.replace(temp_target, target_file)
                    return target_file
            except Exception:
                pass

        source_file = muxed_files[0] if muxed_files else primary_file
        cmd = [ffmpeg_bin, "-y", "-i", source_file]
        if thumb_jpg and os.path.exists(thumb_jpg) and target_ext == "mp4":
            cmd += [
                "-i", thumb_jpg,
                "-map", "0", "-map", "1",
                "-c", "copy",
                "-disposition:v:1", "attached_pic"
            ]
        else:
            cmd += ["-c", "copy"]
        cmd.append(temp_target)

        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, creationflags=cflags)
            if proc.returncode == 0 and os.path.exists(temp_target) and os.path.getsize(temp_target) > 0:
                import glob
                try: os.remove(source_file)
                except OSError: pass
                for extra in glob.glob(glob.escape(source_file) + "*"):
                    try: os.remove(extra)
                    except OSError: pass
                if source_file.endswith(".part"):
                    for extra in glob.glob(glob.escape(source_file[:-5]) + "*"):
                        if extra not in (target_file, temp_target):
                            try: os.remove(extra)
                            except OSError: pass
                if orig_thumb and os.path.exists(orig_thumb):
                    try: os.remove(orig_thumb)
                    except OSError: pass
                if thumb_jpg and thumb_jpg != orig_thumb and os.path.exists(thumb_jpg):
                    try: os.remove(thumb_jpg)
                    except OSError: pass
                if os.path.exists(target_file):
                    try: os.remove(target_file)
                    except OSError: pass
                os.replace(temp_target, target_file)
                return target_file
        except Exception:
            pass

        if thumb_jpg and thumb_jpg != orig_thumb and os.path.exists(thumb_jpg):
            try: os.remove(thumb_jpg)
            except OSError: pass

        if os.path.exists(temp_target):
            try: os.remove(temp_target)
            except OSError: pass

        try:
            if os.path.exists(target_file) and os.path.abspath(primary_file) != os.path.abspath(target_file):
                try: os.remove(target_file)
                except OSError: pass
            os.replace(primary_file, target_file)
            return target_file
        except Exception:
            return primary_file

    def _salvage_live_file(self) -> Optional[str]:
        if not self._task.output_dir or not os.path.isdir(self._task.output_dir):
            return None
        import time
        now = time.time()
        best_file = None
        best_size = 0
        try:
            for entry in os.scandir(self._task.output_dir):
                if entry.is_file():
                    ext = entry.name.lower()
                    if not ext.endswith((".webp", ".jpg", ".jpeg", ".png", ".json", ".vtt", ".srt", ".description")):
                        try:
                            st = entry.stat()
                            if now - st.st_mtime < 600 and st.st_size > 100 * 1024:
                                if st.st_size > best_size:
                                    best_size = st.st_size
                                    best_file = entry.path
                        except OSError:
                            pass
        except Exception:
            pass
        return best_file


def is_twitch_live_url(url: str) -> bool:
    clean = url.strip().split("?")[0].split("#")[0].rstrip("/")
    m = re.match(r'^https?://(?:(?:www|m)\.)?twitch\.tv/([a-zA-Z0-9_]+)$', clean, re.IGNORECASE)
    if not m:
        return False
    reserved = {"directory", "downloads", "jobs", "turbo", "prime", "videos", "clips", "p", "login", "signup", "settings"}
    return m.group(1).lower() not in reserved


def find_streamlink() -> Optional[str]:
    import shutil
    import sys
    found = shutil.which("streamlink") or shutil.which("streamlink.exe")
    if found:
        return found
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts")
    cand = os.path.join(scripts_dir, "streamlink.exe")
    if os.path.isfile(cand):
        return cand
    cand2 = os.path.join(os.path.dirname(sys.executable), "streamlink.exe")
    if os.path.isfile(cand2):
        return cand2
    for p in (
        r"C:\Program Files\Streamlink\bin\streamlink.exe",
        r"C:\Program Files (x86)\Streamlink\bin\streamlink.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Streamlink\bin\streamlink.exe"),
    ):
        if os.path.isfile(p):
            return p
    return None


class StreamlinkWorker(QThread):
    progress_updated = pyqtSignal(str, float, str, str, str)
    status_changed = pyqtSignal(str, str)
    log_message = pyqtSignal(str, str)
    download_finished = pyqtSignal(str, str, str)
    errored = pyqtSignal(str, str)

    def __init__(self, task: DownloadTask, streamlink_path: str, quality: str = "best"):
        super().__init__()
        self._task = task
        self._streamlink_path = streamlink_path
        self._quality = quality
        self._cancelled = False
        self._stopping = False
        self._proc: Optional[subprocess.Popen] = None
        self._output_file: str = ""

    def run(self) -> None:
        ident = threading.current_thread().ident
        with _subproc_lock:
            _worker_subprocs[ident] = set()

        self.status_changed.emit(self._task.id, DownloadStatus.DOWNLOADING.name)

        try:
            import time

            if self._task.output_dir:
                os.makedirs(self._task.output_dir, exist_ok=True)

            clean_title = re.sub(r'[\\/:"*?<>|]', '_', self._task.title).strip()[:80] or "stream"
            ts_file = os.path.join(self._task.output_dir, f"{clean_title}.ts")
            n = 2
            while os.path.exists(ts_file):
                ts_file = os.path.join(self._task.output_dir, f"{clean_title} [{n}].ts")
                n += 1

            self._output_file = ts_file

            stream_qual = self._quality if self._quality else "best"
            if stream_qual != "best" and "," not in stream_qual:
                stream_qual = f"{stream_qual},best"

            cmd = [
                self._streamlink_path,
                "--twitch-disable-ads",
                "--output", ts_file,
                "--force",
                self._task.url,
                stream_qual,
            ]

            self.log_message.emit("info", f"[streamlink] {self._task.url} → {os.path.basename(ts_file)}")

            cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            proc = _orig_popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=cflags,
            )
            self._proc = proc
            with _subproc_lock:
                if ident in _worker_subprocs:
                    _worker_subprocs[ident].add(proc)

            bytes_pattern = re.compile(r'Written\s+([\d.]+)\s*([KMGT]?B)', re.IGNORECASE)
            speed_pattern = re.compile(r'([\d.]+)\s*([KMGT]?B)/s', re.IGNORECASE)
            total_bytes = 0.0
            last_emit = time.monotonic()

            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self.log_message.emit("debug", f"[streamlink] {line}")

                m_bytes = bytes_pattern.search(line)
                if m_bytes:
                    val = float(m_bytes.group(1))
                    unit = m_bytes.group(2).upper()
                    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
                    total_bytes = val * mult.get(unit, 1)

                speed_str = ""
                m_speed = speed_pattern.search(line)
                if m_speed:
                    sv = float(m_speed.group(1))
                    su = m_speed.group(2).upper()
                    mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
                    bps = sv * mult.get(su, 1)
                    if bps >= 1024**2:
                        speed_str = f"{bps/1024**2:.1f} MiB/s"
                    elif bps >= 1024:
                        speed_str = f"{bps/1024:.1f} KiB/s"
                    else:
                        speed_str = f"{bps:.0f} B/s"

                now = time.monotonic()
                if now - last_emit >= 0.5:
                    last_emit = now
                    if total_bytes >= 1024**3:
                        size_str = f"{total_bytes/1024**3:.2f} GiB"
                    elif total_bytes >= 1024**2:
                        size_str = f"{total_bytes/1024**2:.1f} MiB"
                    elif total_bytes >= 1024:
                        size_str = f"{total_bytes/1024:.0f} KiB"
                    else:
                        size_str = ""
                    self.progress_updated.emit(
                        self._task.id, 0.0, speed_str, size_str,
                        ts_file if os.path.exists(ts_file) else ""
                    )

            proc.wait()
            returncode = proc.returncode

            if self._cancelled:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
                self._cleanup_partial_files()
                return

            ts_ok = os.path.exists(ts_file) and os.path.getsize(ts_file) > 0
            if self._stopping or returncode == 0 or ts_ok:
                self.status_changed.emit(self._task.id, DownloadStatus.PROCESSING.name)
                self.log_message.emit("info", "[streamlink] Converting .ts → .mp4…")
                final = self._convert_ts(ts_file)
                if final and os.path.exists(final) and os.path.getsize(final) > 0:
                    self.download_finished.emit(self._task.id, self._task.output_dir, final)
                elif ts_ok:
                    self.download_finished.emit(self._task.id, self._task.output_dir, ts_file)
                else:
                    self.errored.emit(self._task.id, "streamlink: no output file produced")
            else:
                self.errored.emit(self._task.id, f"streamlink exited with code {returncode}")

        except Exception as exc:
            if not self._cancelled:
                self.errored.emit(self._task.id, str(exc))
            else:
                self.status_changed.emit(self._task.id, DownloadStatus.CANCELLED.name)
        finally:
            with _subproc_lock:
                _worker_subprocs.pop(ident, None)

    def _convert_ts(self, ts_path: str) -> Optional[str]:
        from .ffmpeg_utils import find_ffmpeg
        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin or not os.path.exists(ts_path):
            return None
        mp4_path = ts_path.rsplit(".", 1)[0] + ".mp4"
        cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            proc = _orig_popen(
                [ffmpeg_bin, "-y", "-i", ts_path, "-c", "copy", mp4_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=cflags,
            )
            self._proc = proc
            proc.wait(timeout=300)
            if self._cancelled:
                self._try_remove(mp4_path)
                return None
            if proc.returncode == 0 and os.path.exists(mp4_path) and os.path.getsize(mp4_path) > 0:
                try:
                    os.remove(ts_path)
                except OSError:
                    pass
                return mp4_path
        except Exception:
            pass
        return None

    def stop_and_save(self) -> None:
        self._stopping = True
        self._terminate_proc()

    def cancel(self) -> None:
        self._cancelled = True
        self._terminate_proc()

    def _terminate_proc(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def _try_remove(self, path: str) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _cleanup_partial_files(self) -> None:
        if self._output_file:
            self._try_remove(self._output_file)
            mp4_file = self._output_file.rsplit(".", 1)[0] + ".mp4"
            self._try_remove(mp4_file)

    def pause(self) -> None:
        pass

