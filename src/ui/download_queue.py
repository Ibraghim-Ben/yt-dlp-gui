from __future__ import annotations
import os
import subprocess
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QProgressBar, QPushButton, QSizePolicy, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen
from ..core.models import DownloadTask, DownloadStatus


_STATUS_LABELS = {
    DownloadStatus.QUEUED:      "Queued",
    DownloadStatus.ANALYZING:   "Analyzing…",
    DownloadStatus.DOWNLOADING: "Downloading",
    DownloadStatus.PROCESSING:  "Processing…",
    DownloadStatus.PAUSED:      "Paused",
    DownloadStatus.DONE:        "Done",
    DownloadStatus.ERROR:       "Error",
    DownloadStatus.CANCELLED:   "Cancelled",
}


class ActionButton(QPushButton):
    def __init__(self, icon_type: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._icon_type = icon_type
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_icon_type(self, icon_type: str) -> None:
        if self._icon_type != icon_type:
            self._icon_type = icon_type
            self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        is_hover = self.underMouse() and self.isEnabled()
        is_dark = self.palette().window().color().lightness() < 128

        if is_hover:
            if self._icon_type == "cancel":
                bg = QColor("#f38ba8") if is_dark else QColor("#d20f39")
                fg = QColor("#1e1e2e") if is_dark else QColor("#ffffff")
            else:
                bg = QColor("#89b4fa") if is_dark else QColor("#1e66f5")
                fg = QColor("#1e1e2e") if is_dark else QColor("#ffffff")
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(1.0, 1.0, 16.0, 16.0), 3.0, 3.0)
        else:
            if self._icon_type == "cancel":
                fg = QColor("#6c7086") if is_dark else QColor("#acb0be")
            else:
                fg = QColor("#a6adc8") if is_dark else QColor("#6c6f85")

        cx = r.width() / 2.0
        cy = r.height() / 2.0

        if self._icon_type == "play":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fg))
            points = [
                QPointF(cx - 3.5, cy - 4.5),
                QPointF(cx + 4.5, cy),
                QPointF(cx - 3.5, cy + 4.5),
            ]
            painter.drawPolygon(points)
        elif self._icon_type == "pause":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fg))
            painter.drawRoundedRect(QRectF(cx - 4.0, cy - 4.5, 2.6, 9.0), 1.0, 1.0)
            painter.drawRoundedRect(QRectF(cx + 1.4, cy - 4.5, 2.6, 9.0), 1.0, 1.0)
        elif self._icon_type == "cancel":
            pen = QPen(fg, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            s = 3.8
            painter.drawLine(QPointF(cx - s, cy - s), QPointF(cx + s, cy + s))
            painter.drawLine(QPointF(cx - s, cy + s), QPointF(cx + s, cy - s))
        elif self._icon_type == "folder":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fg))
            painter.drawRoundedRect(QRectF(cx - 5.0, cy - 2.5, 10.0, 7.0), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(cx - 5.0, cy - 4.5, 4.5, 2.5), 1.0, 1.0)
        elif self._icon_type == "file_play":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(fg))
            points = [
                QPointF(cx - 2.5, cy - 3.5),
                QPointF(cx + 3.5, cy),
                QPointF(cx - 2.5, cy + 3.5),
            ]
            painter.drawPolygon(points)


class TaskItemWidget(QWidget):
    pause_clicked = pyqtSignal(str)
    resume_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)

    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self.setObjectName("taskItemWidget")
        self._task_id = task.id
        self._status = task.status
        self._file_path = task.file_path
        self._output_dir = task.output_dir
        self._build_ui(task)

    @property
    def status(self) -> DownloadStatus:
        return self._status

    def _build_ui(self, task: DownloadTask) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel(task.title)
        self._title_label.setObjectName("taskTitle")
        self._title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._title_label.setMaximumWidth(999)
        top.addWidget(self._title_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self._status_label = QLabel()
        self._status_label.setObjectName("taskStatus")
        self._status_label.setFixedWidth(100)
        self._status_label.setFixedHeight(18)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._status_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._pause_btn = ActionButton("pause")
        self._pause_btn.setObjectName("taskPauseBtn")
        self._pause_btn.clicked.connect(self._on_pause_toggle)
        top.addWidget(self._pause_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._open_folder_btn = ActionButton("folder")
        self._open_folder_btn.setObjectName("taskOpenFolderBtn")
        self._open_folder_btn.setToolTip("Open folder")
        self._open_folder_btn.setVisible(False)
        self._open_folder_btn.clicked.connect(self._on_open_folder)
        top.addWidget(self._open_folder_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._open_file_btn = ActionButton("file_play")
        self._open_file_btn.setObjectName("taskOpenFileBtn")
        self._open_file_btn.setToolTip("Open file")
        self._open_file_btn.setVisible(False)
        self._open_file_btn.clicked.connect(self._on_open_file)
        top.addWidget(self._open_file_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._cancel_btn = ActionButton("cancel")
        self._cancel_btn.setObjectName("taskCancelBtn")
        self._cancel_btn.clicked.connect(self._on_cancel)
        top.addWidget(self._cancel_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        root.addLayout(top)

        self._progress = QProgressBar()
        self._progress.setObjectName("taskProgress")
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        bot = QHBoxLayout()
        bot.setSpacing(12)
        self._speed_label = QLabel()
        self._speed_label.setObjectName("taskSpeed")
        bot.addWidget(self._speed_label)

        self._eta_label = QLabel()
        self._eta_label.setObjectName("taskEta")
        bot.addWidget(self._eta_label)
        bot.addStretch()

        self._error_label = QLabel()
        self._error_label.setObjectName("taskError")
        self._error_label.setWordWrap(True)
        bot.addWidget(self._error_label)
        root.addLayout(bot)

        self.update_task(task)

    def update_task(self, task: DownloadTask) -> None:
        self._status = task.status
        self._file_path = task.file_path
        self._output_dir = task.output_dir
        self._title_label.setText(task.title)
        self._progress.setValue(int(task.progress))

        label = _STATUS_LABELS.get(task.status, task.status.name)
        self._status_label.setText(label)
        
        status_name = task.status.name.lower()
        self._status_label.setProperty("taskStatus", status_name)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

        self._progress.setProperty("taskStatus", status_name)
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)

        if task.status == DownloadStatus.DOWNLOADING:
            parts = []
            if task.speed:
                parts.append(task.speed)
            if task.eta:
                parts.append(f"ETA {task.eta}")
            self._speed_label.setText("  ".join(parts))
        else:
            self._speed_label.setText("")
            self._eta_label.setText("")

        if task.status == DownloadStatus.ERROR:
            self._error_label.setText(task.error_message)
            self._error_label.setProperty("taskStatus", "error")
        else:
            self._error_label.setText("")
            self._error_label.setProperty("taskStatus", "")
            
        self._error_label.style().unpolish(self._error_label)
        self._error_label.style().polish(self._error_label)

        if task.status == DownloadStatus.PAUSED:
            self._pause_btn.setVisible(True)
            self._pause_btn.setEnabled(True)
            self._pause_btn.set_icon_type("play")
            self._pause_btn.setToolTip("Resume")
        elif task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED):
            self._pause_btn.setVisible(True)
            self._pause_btn.setEnabled(True)
            self._pause_btn.set_icon_type("pause")
            self._pause_btn.setToolTip("Pause")
        else:
            self._pause_btn.setVisible(False)

        is_done = task.status == DownloadStatus.DONE
        self._open_folder_btn.setVisible(is_done)
        self._open_file_btn.setVisible(is_done)

        is_terminal = task.status in (
            DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED
        )
        is_processing = task.status == DownloadStatus.PROCESSING
        self._cancel_btn.setEnabled(not is_processing)
        self._cancel_btn.setToolTip(
            "Remove" if is_terminal else ("Processing…" if is_processing else "Cancel")
        )

    def _on_pause_toggle(self) -> None:
        if self._status == DownloadStatus.PAUSED:
            self._pause_btn.setEnabled(False)
            self.resume_clicked.emit(self._task_id)
        elif self._status in (DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED):
            self._pause_btn.setEnabled(False)
            self.pause_clicked.emit(self._task_id)

    def _on_open_folder(self) -> None:
        if self._file_path and os.path.isfile(self._file_path):
            # /select, and the path MUST be a single argument — no space between them
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(self._file_path)}"])
        elif self._output_dir and os.path.isdir(self._output_dir):
            os.startfile(self._output_dir)

    def _on_open_file(self) -> None:
        if self._file_path and os.path.isfile(self._file_path):
            os.startfile(os.path.normpath(self._file_path))
        elif self._output_dir and os.path.isdir(self._output_dir):
            os.startfile(self._output_dir)

    def _on_cancel(self) -> None:
        is_active = self._status not in (DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED)
        if is_active:
            reply = QMessageBox.question(
                self,
                "Cancel Download",
                f"Are you sure you want to cancel downloading \"{self._title_label.text()}\"?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.cancel_clicked.emit(self._task_id)
        else:
            self.remove_clicked.emit(self._task_id)


class DownloadQueue(QWidget):
    pause_requested = pyqtSignal(str)
    resume_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_widget = QWidget()
        header_widget.setObjectName("queueHeaderWidget")
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        lbl = QLabel("Download Queue")
        lbl.setObjectName("queueHeader")
        header.addWidget(lbl)
        header.addStretch()

        self._clear_btn = QPushButton("Clear done")
        self._clear_btn.setObjectName("clearDoneBtn")
        self._clear_btn.setFixedHeight(24)
        self._clear_btn.clicked.connect(self._clear_done)
        header.addWidget(self._clear_btn)
        layout.addWidget(header_widget)

        self._list = QListWidget()
        self._list.setObjectName("queueList")
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setSpacing(2)
        self._list.setUniformItemSizes(False)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        layout.addWidget(self._list)

        self._task_widgets: dict[str, TaskItemWidget] = {}
        self._task_items: dict[str, QListWidgetItem] = {}

    def add_task(self, task: DownloadTask) -> None:
        widget = TaskItemWidget(task)
        widget.pause_clicked.connect(self.pause_requested)
        widget.resume_clicked.connect(self.resume_requested)
        widget.cancel_clicked.connect(self.cancel_requested)
        widget.remove_clicked.connect(self.remove_requested)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

        self._task_widgets[task.id] = widget
        self._task_items[task.id] = item
        self._list.scrollToBottom()
        QApplication.processEvents()

    def update_task(self, task: DownloadTask) -> None:
        widget = self._task_widgets.get(task.id)
        item = self._task_items.get(task.id)
        if widget and item:
            widget.update_task(task)
            item.setSizeHint(widget.sizeHint())

    def remove_task(self, task_id: str) -> None:
        item = self._task_items.pop(task_id, None)
        widget = self._task_widgets.pop(task_id, None)
        if widget:
            widget.deleteLater()
        if item:
            row = self._list.row(item)
            self._list.takeItem(row)

    def _on_cancel(self, task_id: str) -> None:
        self.cancel_requested.emit(task_id)

    def _clear_done(self) -> None:
        done_ids = [
            tid for tid, w in self._task_widgets.items()
            if self._get_task_status(w) in (
                DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED
            )
        ]
        for tid in done_ids:
            self.remove_requested.emit(tid)

    def _get_task_status(self, widget: TaskItemWidget) -> DownloadStatus:
        return widget.status
