from __future__ import annotations
import uuid
import glob
import os
import json
import shutil
from typing import Optional, TYPE_CHECKING
import pathlib
from PyQt6.QtCore import QObject, pyqtSignal
if TYPE_CHECKING:
    from ..utils.config import Config
from .models import DownloadTask, DownloadStatus
from .worker import DownloadWorker
from .downloader import build_ydl_opts
from .ffmpeg_utils import find_ffmpeg


class QueueManager(QObject):
    task_added = pyqtSignal(object)
    task_updated = pyqtSignal(str, object)
    task_removed = pyqtSignal(str)
    log_message = pyqtSignal(str, str)

    def __init__(self, config: "Config", parent=None):
        super().__init__(parent)
        self._config = config
        self._tasks: dict[str, DownloadTask] = {}
        self._workers: dict[str, DownloadWorker] = {}
        self._order: list[str] = []
        self._in_flight_templates: set[str] = set()
        self._load_tasks()

    def _save_tasks(self) -> None:
        try:
            tasks_file = self._config.data_dir / "tasks.json"
            data = []
            for tid in self._order:
                task = self._tasks.get(tid)
                if not task:
                    continue
                
                status = task.status
                if status in (DownloadStatus.QUEUED, DownloadStatus.ANALYZING, 
                              DownloadStatus.DOWNLOADING, DownloadStatus.PROCESSING):
                    status = DownloadStatus.CANCELLED
                
                task_dict = {
                    "id": task.id,
                    "url": task.url,
                    "title": task.title,
                    "selected_format_id": task.selected_format_id,
                    "audio_format_id": task.audio_format_id,
                    "output_dir": task.output_dir,
                    "output_template": task.output_template,
                    "mode": task.mode,
                    "target_ext": task.target_ext,
                    "embed_subs": task.embed_subs,
                    "subs_langs": task.subs_langs,
                    "embed_thumbnail": task.embed_thumbnail,
                    "embed_metadata": task.embed_metadata,
                    "status": status.name,
                    "progress": task.progress,
                    "error_message": task.error_message,
                    "file_path": task.file_path,
                    "thumbnail_url": task.thumbnail_url,
                }
                data.append(task_dict)
            
            temp_file = tasks_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(tasks_file)
        except Exception as e:
            self.log_message.emit("error", f"Failed to save tasks: {e}")

    def _load_tasks(self) -> None:
        try:
            tasks_file = self._config.data_dir / "tasks.json"
            if not tasks_file.exists():
                return

            try:
                shutil.copy2(tasks_file, tasks_file.with_suffix(".bak"))
            except OSError:
                pass

            data = json.loads(tasks_file.read_text(encoding="utf-8"))
            for task_dict in data:
                try:
                    status_name = task_dict.get("status", "CANCELLED")
                    status = DownloadStatus[status_name]

                    task = DownloadTask(
                        id=task_dict["id"],
                        url=task_dict["url"],
                        title=task_dict["title"],
                        video_info=None,
                        selected_format_id=task_dict.get("selected_format_id"),
                        audio_format_id=task_dict.get("audio_format_id"),
                        output_dir=task_dict["output_dir"],
                        output_template=task_dict["output_template"],
                        mode=task_dict["mode"],
                        target_ext=task_dict.get("target_ext"),
                        embed_subs=task_dict.get("embed_subs", False),
                        subs_langs=task_dict.get("subs_langs", ""),
                        embed_thumbnail=task_dict.get("embed_thumbnail", True),
                        embed_metadata=task_dict.get("embed_metadata", True),
                        status=status,
                        progress=task_dict.get("progress", 0.0),
                        error_message=task_dict.get("error_message", ""),
                        file_path=task_dict.get("file_path", ""),
                        thumbnail_url=task_dict.get("thumbnail_url", ""),
                    )
                    self._tasks[task.id] = task
                    self._order.append(task.id)
                except Exception as e:
                    self.log_message.emit(
                        "warning",
                        f"Skipping corrupted task {task_dict.get('id', '?')}: {e}",
                    )
        except Exception as e:
            self.log_message.emit("error", f"Failed to load tasks: {e}")

    def _add_task_no_save(
        self,
        url: str,
        title: str,
        video_info,
        selected_format_id: Optional[str],
        audio_format_id: Optional[str],
        mode: str,
        target_ext: Optional[str] = None,
        embed_subs: bool = False,
        subs_langs: str = "en",
        embed_thumbnail: bool = True,
        embed_metadata: bool = True,
    ) -> DownloadTask:
        task_id = str(uuid.uuid4())
        cfg = self._config
        template = str(pathlib.PurePath(cfg.output_dir) / cfg.output_template)

        task = DownloadTask(
            id=task_id,
            url=url,
            title=title,
            video_info=video_info,
            selected_format_id=selected_format_id,
            audio_format_id=audio_format_id,
            output_dir=cfg.output_dir,
            output_template=template,
            mode=mode,
            target_ext=target_ext,
            embed_subs=embed_subs,
            subs_langs=subs_langs,
            embed_thumbnail=embed_thumbnail,
            embed_metadata=embed_metadata,
            thumbnail_url=video_info.thumbnail if video_info else "",
        )
        self._tasks[task_id] = task
        self._order.append(task_id)
        self.task_added.emit(task)
        return task

    def add_task(self, **kwargs) -> DownloadTask:
        task = self._add_task_no_save(**kwargs)
        self._save_tasks()
        self._try_start_next()
        return task

    def add_tasks_batch(self, specs: list[dict]) -> list[DownloadTask]:
        tasks = []
        for spec in specs:
            tasks.append(self._add_task_no_save(**spec))
        self._save_tasks()
        self._try_start_next()
        return tasks

    def cancel_task(self, task_id: str) -> None:
        worker = self._workers.get(task_id)
        if worker:
            worker.cancel()
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.CANCELLED
            self.task_updated.emit(task_id, task)
            self._save_tasks()
            
            try:
                if task.file_path and os.path.exists(task.file_path):
                    try:
                        os.remove(task.file_path)
                    except OSError:
                        pass
                    
                    if task.file_path.endswith(".part"):
                        ytdl_path = task.file_path[:-5] + ".ytdl"
                        if os.path.exists(ytdl_path):
                            try:
                                os.remove(ytdl_path)
                            except OSError:
                                pass
            except OSError:
                pass

    def remove_task(self, task_id: str) -> None:
        self.cancel_task(task_id)
        self._tasks.pop(task_id, None)
        if task_id in self._order:
            self._order.remove(task_id)
        self.task_removed.emit(task_id)
        self._save_tasks()

    def tasks_in_order(self) -> list[DownloadTask]:
        return [self._tasks[tid] for tid in self._order if tid in self._tasks]

    def _active_count(self) -> int:
        return sum(
            1 for tid, w in self._workers.items()
            if w.isRunning() and self._tasks.get(tid, None) is not None
            and self._tasks[tid].status == DownloadStatus.DOWNLOADING
        )

    def _try_start_next(self) -> None:
        max_parallel = self._config.max_parallel
        while self._active_count() < max_parallel:
            next_task = self._next_queued()
            if next_task is None:
                break
            self._start_task(next_task)

    def _next_queued(self) -> Optional[DownloadTask]:
        for tid in self._order:
            task = self._tasks.get(tid)
            if task and task.status == DownloadStatus.QUEUED:
                return task
        return None

    def _unique_template(self, template: str, task: DownloadTask) -> str:
        if not task.video_info:
            return template
        fake_info = {
            "title": task.title,
            "uploader": task.video_info.channel or task.title,
            "channel": task.video_info.channel or task.title,
            "id": "",
            "resolution": "",
            "format_id": task.selected_format_id or "best",
            "ext": "CHKEXT",
        }
        try:
            import yt_dlp as _yt
            with _yt.YoutubeDL({"outtmpl": template, "quiet": True}) as ydl:
                candidate = ydl.prepare_filename(fake_info)
            stem = candidate[: -len(".CHKEXT")]
            pattern = glob.escape(stem) + ".*"
            hits = [
                f for f in glob.glob(pattern)
                if os.path.isfile(f) and not f.endswith((".part", ".ytdl", ".tmp"))
            ]
            if not hits and stem not in self._in_flight_templates:
                return template
            n = 2
            while True:
                candidate_stem = stem + f" [{n}]"
                on_disk = [
                    f for f in glob.glob(glob.escape(candidate_stem) + ".*")
                    if os.path.isfile(f) and not f.endswith((".part", ".ytdl", ".tmp"))
                ]
                if not on_disk and candidate_stem not in self._in_flight_templates:
                    if ".%(ext)s" in template:
                        return template[: -len(".%(ext)s")] + f" [{n}].%(ext)s"
                    return template + f" [{n}]"
                n += 1
        except Exception as e:
            self.log_message.emit("warning", f"_unique_template failed: {e}")
            return template

    def _start_task(self, task: DownloadTask) -> None:
        cfg = self._config
        task.status = DownloadStatus.DOWNLOADING
        self.task_updated.emit(task.id, task)

        unique_template = self._unique_template(task.output_template, task)

        try:
            import yt_dlp as _yt
            with _yt.YoutubeDL({"outtmpl": unique_template, "quiet": True}) as ydl:
                stem = ydl.prepare_filename({
                    "title": task.title,
                    "uploader": task.video_info.channel if task.video_info else task.title,
                    "channel": task.video_info.channel if task.video_info else task.title,
                    "id": "", "resolution": "",
                    "format_id": task.selected_format_id or "best",
                    "ext": "CHKEXT",
                })
            self._in_flight_templates.add(stem[: -len(".CHKEXT")])
        except Exception:
            pass

        needs_cookies = bool(
            task.video_info and getattr(task.video_info, "auth_required", False)
        )

        ydl_opts = build_ydl_opts(
            task_id=task.id,
            output_template=unique_template,
            mode=task.mode,
            selected_format_id=task.selected_format_id,
            audio_format_id=task.audio_format_id,
            target_ext=task.target_ext,
            ffmpeg_path=cfg.ffmpeg_path or find_ffmpeg(),
            cookies_browser=cfg.cookies_browser if needs_cookies else None,
            rate_limit=cfg.rate_limit or None,
            embed_thumbnail=task.embed_thumbnail,
            embed_metadata=task.embed_metadata,
            embed_subs=task.embed_subs,
            subs_langs=task.subs_langs,
            manual_sub_langs=task.video_info.manual_subtitle_langs if task.video_info else frozenset(),
            archive_file=cfg.download_archive or None,
            log_callback=lambda lvl, msg: self.log_message.emit(lvl, msg),
        )

        worker = DownloadWorker(task, ydl_opts)
        worker.progress_updated.connect(self._on_progress)
        worker.status_changed.connect(self._on_status)
        worker.log_message.connect(lambda lvl, msg: self.log_message.emit(lvl, msg))
        worker.download_finished.connect(self._on_finished)
        worker.errored.connect(self._on_error)
        worker.finished.connect(lambda: self._cleanup_worker(task.id))

        self._workers[task.id] = worker
        worker.start()

    def _on_progress(self, task_id: str, pct: float, speed: str, eta: str, filepath: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.progress = pct
            task.speed = speed
            task.eta = eta
            if filepath:
                task.file_path = filepath
            self.task_updated.emit(task_id, task)

    def _on_status(self, task_id: str, status_name: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus[status_name]
            self.task_updated.emit(task_id, task)
            self._save_tasks()

    def _on_finished(self, task_id: str, output_dir: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.DONE
            task.progress = 100.0
            task.file_path = output_dir
            self.task_updated.emit(task_id, task)
            self._save_tasks()

    def _on_error(self, task_id: str, error_msg: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.status = DownloadStatus.ERROR
            task.error_message = error_msg
            self.task_updated.emit(task_id, task)
            self._save_tasks()

    def _cleanup_worker(self, task_id: str) -> None:
        worker = self._workers.pop(task_id, None)
        if worker:
            worker.deleteLater()
        task = self._tasks.get(task_id)
        if task:
            try:
                import yt_dlp as _yt
                with _yt.YoutubeDL({"outtmpl": task.output_template, "quiet": True}) as ydl:
                    stem = ydl.prepare_filename({
                        "title": task.title,
                        "uploader": task.video_info.channel if task.video_info else task.title,
                        "channel": task.video_info.channel if task.video_info else task.title,
                        "id": "", "resolution": "",
                        "format_id": task.selected_format_id or "best",
                        "ext": "CHKEXT",
                    })
                self._in_flight_templates.discard(stem[: -len(".CHKEXT")])
            except Exception:
                pass
        self._try_start_next()

    def has_active_tasks(self) -> bool:
        return any(w.isRunning() for w in self._workers.values())

    def cancel_all(self) -> None:
        active = [w for w in self._workers.values() if w.isRunning()]
        for w in active:
            w.cancel()
        for w in active:
            w.wait(3000)
