from __future__ import annotations
import base64
from typing import Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QStatusBar, QToolBar, QMessageBox, QFrame, QLabel, QDialog, QPushButton,
)
from PyQt6.QtCore import Qt, QSize, QByteArray, QEvent, QObject
from PyQt6.QtGui import (
    QAction, QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent, QResizeEvent, QCursor,
)

from ..utils.config import Config
from ..core.queue_manager import QueueManager
from ..core.worker import AnalyzeWorker
from ..core.models import VideoInfo, FormatInfo, PlaylistEntry
from ..core.container_rules import resolve_container
from ..core.ffmpeg_utils import find_ffmpeg

from .url_bar import UrlBar, _normalize_url
from .format_selector import FormatSelector
from .download_queue import DownloadQueue
from .log_panel import LogPanel
from .settings_dialog import SettingsDialog
from .playlist_dialog import PlaylistDialog
from .drop_overlay import DropOverlay


class NoTooltipFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            return True
        return super().eventFilter(obj, event)


class MainWindow(QMainWindow):
    def __init__(self, config: Config, queue: QueueManager):
        super().__init__()
        self._config = config
        self._queue = queue
        self._analyze_worker: Optional[AnalyzeWorker] = None
        self._current_video: Optional[VideoInfo] = None
        self._last_clipboard_url: str = _normalize_url(QApplication.clipboard().text().strip()) or ""

        self.setWindowTitle("yt-dlp GUI")
        if not QApplication.windowIcon().isNull():
            self.setWindowIcon(QApplication.windowIcon())
        self.setMinimumSize(960, 640)
        self.setAcceptDrops(True)
        self.installEventFilter(self)

        self._drop_overlay = DropOverlay(self)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._connect_queue()

        if config.window_geometry:
            try:
                self.restoreGeometry(QByteArray(base64.b64decode(config.window_geometry)))
            except Exception:
                pass

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))

        self._tooltip_filter = NoTooltipFilter()
        tb.installEventFilter(self._tooltip_filter)

        settings_act = QAction("⚙  Settings", self)
        settings_act.setToolTip("")
        settings_act.triggered.connect(self._open_settings)
        tb.addAction(settings_act)

        tb.addSeparator()

        self._log_act = QAction("📋  Log", self)
        self._log_act.setToolTip("")
        self._log_act.setCheckable(True)
        self._log_act.setChecked(False)
        self._log_act.toggled.connect(self._toggle_log)
        tb.addAction(self._log_act)

        self.addToolBar(tb)

    def _build_central(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(8)

        self._main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter.setObjectName("mainSplitter")
        self._main_splitter.setHandleWidth(6)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self._url_bar = UrlBar()
        self._url_bar.analyze_requested.connect(self._on_analyze)
        left_layout.addWidget(self._url_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("separator")
        left_layout.addWidget(sep)

        self._format_selector = FormatSelector()
        self._format_selector.download_requested.connect(self._on_download_requested)
        self._format_selector.set_output_dir(self._config.output_dir)
        left_layout.addWidget(self._format_selector, 1)

        self._main_splitter.addWidget(left_widget)

        self._dl_queue = DownloadQueue()
        self._dl_queue.pause_requested.connect(self._queue.pause_task)
        self._dl_queue.resume_requested.connect(self._queue.resume_task)
        self._dl_queue.cancel_requested.connect(self._queue.cancel_task)
        self._dl_queue.remove_requested.connect(self._queue.remove_task)
        self._main_splitter.addWidget(self._dl_queue)

        self._main_splitter.setSizes([520, 520])

        self._log_panel = LogPanel()
        self._log_panel.setVisible(False)

        self._vert_splitter = QSplitter(Qt.Orientation.Vertical)
        self._vert_splitter.setObjectName("vertSplitter")
        self._vert_splitter.setHandleWidth(6)
        self._vert_splitter.addWidget(self._main_splitter)
        self._vert_splitter.addWidget(self._log_panel)
        self._vert_splitter.setSizes([480, 150])

        root.addWidget(self._vert_splitter, 1)

        for w in (central, left_widget, self._format_selector, self._dl_queue, self._log_panel, self._main_splitter, self._vert_splitter):
            w.setAcceptDrops(True)
            w.installEventFilter(self)

    def _build_statusbar(self) -> None:
        self._status = QStatusBar(self)
        self._status.setObjectName("statusBar")
        self._status.hide()

    def _connect_queue(self) -> None:
        self._queue.task_added.connect(self._dl_queue.add_task)
        self._queue.task_updated.connect(
            lambda tid, task: self._dl_queue.update_task(task)
        )
        self._queue.task_removed.connect(self._dl_queue.remove_task)
        self._queue.log_message.connect(self._log_panel.append)
        
        for task in self._queue.tasks_in_order():
            self._dl_queue.add_task(task)

    def _on_analyze(self, url: str) -> None:
        self._last_clipboard_url = url
        try:
            if self._analyze_worker and self._analyze_worker.isRunning():
                self._status.showMessage("Already analyzing… please wait.")
                return
        except RuntimeError:
            self._analyze_worker = None

        self._url_bar.set_busy(True)
        self._status.showMessage(f"Analyzing {url}…")
        self._format_selector.clear()

        worker = AnalyzeWorker(
            url,
            cookies_browser=self._config.cookies_browser,
            ffmpeg_path=self._config.ffmpeg_path or find_ffmpeg(),
        )
        worker.analyze_finished.connect(self._on_analyze_done)
        worker.error.connect(self._on_analyze_error)
        worker.log.connect(self._log_panel.append)
        worker.analyze_finished.connect(lambda _: self._url_bar.set_busy(False))
        worker.error.connect(lambda _: self._url_bar.set_busy(False))
        worker.finished.connect(worker.deleteLater)
        self._analyze_worker = worker
        worker.start()

    def _on_analyze_done(self, video_info: VideoInfo) -> None:
        self._current_video = video_info
        self._status.showMessage(f"Loaded: {video_info.title}")

        if video_info.is_playlist:
            if not video_info.playlist_entries:
                self._status.showMessage("Error: Playlist has no available videos")
                QMessageBox.warning(
                    self,
                    "Empty Playlist",
                    "No available videos were found in this playlist.",
                )
                return
            dlg = PlaylistDialog(
                video_info,
                cookies_browser=self._config.cookies_browser,
                parent=self,
            )
            dlg.entries_selected.connect(self._on_playlist_entries_selected)
            dlg.exec()
        else:
            self._format_selector.load_video(video_info, self._config.output_dir)

    def _on_analyze_error(self, msg: str) -> None:
        self._status.showMessage(f"Error: {msg}")
        dlg = QDialog(self)
        dlg.setWindowTitle("Analysis Failed")
        layout = QVBoxLayout(dlg)
        
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        text_width = lbl.fontMetrics().horizontalAdvance(msg)
        width = max(180, min(text_width + 40, 450))
        lbl.setMinimumWidth(width)
        
        btn = QPushButton("OK")
        btn.clicked.connect(dlg.accept)
        
        layout.addWidget(lbl)
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        dlg.exec()

    def _on_playlist_entries_selected(self, entries: list[PlaylistEntry]) -> None:
        specs = []
        for entry in entries:
            specs.append({
                "url": entry.url,
                "title": entry.title,
                "video_info": None,
                "selected_format_id": None,
                "audio_format_id": None,
                "mode": "video",
            })
        if specs:
            self._queue.add_tasks_batch(specs)
        self._status.showMessage(f"Added {len(entries)} items to queue")

    def _on_download_requested(
        self,
        selected_fmt: Optional[FormatInfo],
        audio_fmt: Optional[FormatInfo],
        mode: str,
        output_dir: str,
        embed_subs: bool = False,
        subs_langs: str = "en",
        embed_thumbnail: bool = True,
        embed_metadata: bool = True,
        audio_format_ext: str = "",
    ) -> None:
        if not self._current_video:
            return
        self._config.output_dir = output_dir

        target_ext = selected_fmt.ext if selected_fmt else None
        if target_ext and audio_fmt:
            target_ext = resolve_container(target_ext, audio_fmt.acodec)
        if mode == "audio" and audio_format_ext:
            target_ext = audio_format_ext

        self._queue.add_task(
            url=self._current_video.webpage_url or self._current_video.url,
            title=self._current_video.title,
            video_info=self._current_video,
            selected_format_id=selected_fmt.format_id if selected_fmt else None,
            audio_format_id=audio_fmt.format_id if audio_fmt else None,
            mode=mode,
            target_ext=target_ext,
            embed_subs=embed_subs,
            subs_langs=subs_langs,
            embed_thumbnail=embed_thumbnail,
            embed_metadata=embed_metadata,
        )
        self._status.showMessage(f"Added to queue: {self._current_video.title}")

    def _toggle_log(self, visible: bool) -> None:
        self._log_panel.setVisible(visible)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, parent=self)
        if dlg.exec():
            self._format_selector.set_output_dir(self._config.output_dir)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About yt-dlp GUI",
            "<b>yt-dlp GUI</b><br><br>"
            "A graphical interface for yt-dlp.<br><br>"
            "Built with Python + PyQt6.",
        )

    def _has_valid_drag_data(self, mime_data) -> bool:
        if not mime_data:
            return False
        if mime_data.hasUrls():
            for u in mime_data.urls():
                s = u.toString().strip().lower()
                if s.startswith(("http://", "https://")):
                    return True
        if mime_data.hasText():
            t = mime_data.text().strip().lower()
            if any(p in t for p in ("http://", "https://", "www.", "youtu.be", "youtube.com")):
                return True
        return False

    def _extract_url_from_mime(self, mime_data) -> str:
        if not mime_data:
            return ""
        if mime_data.hasUrls():
            for u in mime_data.urls():
                s = u.toString().strip()
                if s.startswith(("http://", "https://")):
                    return s
        if mime_data.hasText():
            text = mime_data.text().strip()
            for line in text.splitlines():
                line = line.strip()
                if line.startswith(("http://", "https://", "www.")):
                    return line
            if " " in text:
                for token in text.split():
                    if token.startswith(("http://", "https://")):
                        return token
            return text
        return ""

    def _show_drop_overlay(self) -> None:
        if hasattr(self, "_drop_overlay") and self._drop_overlay:
            self._drop_overlay.setGeometry(self.rect())
            self._drop_overlay.show()
            self._drop_overlay.raise_()

    def _hide_drop_overlay(self) -> None:
        if hasattr(self, "_drop_overlay") and self._drop_overlay:
            self._drop_overlay.hide()

    def _hide_drop_overlay_if_outside(self) -> None:
        pos = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos):
            self._hide_drop_overlay()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_drop_overlay") and self._drop_overlay:
            self._drop_overlay.setGeometry(self.rect())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._has_valid_drag_data(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_overlay()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._has_valid_drag_data(event.mimeData()):
            event.acceptProposedAction()
            if not self._drop_overlay.isVisible():
                self._show_drop_overlay()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hide_drop_overlay_if_outside()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hide_drop_overlay()
        url = self._extract_url_from_mime(event.mimeData())
        if url:
            event.acceptProposedAction()
            normalized = _normalize_url(url) or url
            self._url_bar.set_url(normalized)
            self._on_analyze(normalized)
        else:
            event.ignore()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype == QEvent.Type.DragEnter:
            if isinstance(event, QDragEnterEvent) and self._has_valid_drag_data(event.mimeData()):
                event.acceptProposedAction()
                self._show_drop_overlay()
                return True
        elif etype == QEvent.Type.DragMove:
            if isinstance(event, QDragMoveEvent) and self._has_valid_drag_data(event.mimeData()):
                event.acceptProposedAction()
                if not self._drop_overlay.isVisible():
                    self._show_drop_overlay()
                return True
        elif etype == QEvent.Type.DragLeave:
            self._hide_drop_overlay_if_outside()
        elif etype == QEvent.Type.Drop:
            if isinstance(event, QDropEvent):
                self._hide_drop_overlay()
                url = self._extract_url_from_mime(event.mimeData())
                if url:
                    event.acceptProposedAction()
                    normalized = _normalize_url(url) or url
                    self._url_bar.set_url(normalized)
                    self._on_analyze(normalized)
                    return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._check_clipboard()

    def _check_clipboard(self) -> None:
        if not self._config.clipboard_monitor:
            return
        try:
            if self._analyze_worker and self._analyze_worker.isRunning():
                return
        except RuntimeError:
            self._analyze_worker = None
        text = QApplication.clipboard().text().strip()
        normalized = _normalize_url(text)
        if not normalized:
            return
        if normalized == self._last_clipboard_url:
            return
        current_text = self._url_bar._edit.text().strip()
        if normalized == current_text:
            self._last_clipboard_url = normalized
            return
        self._last_clipboard_url = normalized
        self._url_bar.set_url(normalized)
        self._on_analyze(normalized)

    def closeEvent(self, event) -> None:
        if self._queue.has_active_tasks():
            reply = QMessageBox.question(
                self,
                "Active Downloads",
                "There are active downloads. Cancel them and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._queue.cancel_all()
        self._config.window_geometry = base64.b64encode(self.saveGeometry().data()).decode("ascii")
        try:
            self._config.save()
        except Exception as e:
            QMessageBox.warning(self, "Save Settings Failed", f"Could not save configuration during exit:\n{e}")
        event.accept()
