from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QCheckBox,
    QDialogButtonBox, QFrame,
)
from PyQt6.QtCore import pyqtSignal
from ..core.models import VideoInfo, PlaylistEntry
from ..utils.formatters import format_duration


class PlaylistDialog(QDialog):
    entries_selected = pyqtSignal(list)

    def __init__(self, video_info: VideoInfo, cookies_browser: str, parent=None):
        super().__init__(parent)
        self._video_info = video_info
        self._cookies_browser = cookies_browser
        self._entries = list(video_info.playlist_entries)
        self._checkboxes: list[QCheckBox] = []

        self.setWindowTitle("Select Videos from Playlist")
        self.setMinimumSize(700, 500)
        self._build_ui()
        self._populate(self._entries)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title = QLabel(f"<b>{self._video_info.playlist_title or self._video_info.title}</b>")
        title.setObjectName("playlistTitle")
        layout.addWidget(title)

        count_str = f"{len(self._entries)} videos"
        self._count_label = QLabel(count_str)
        self._count_label.setObjectName("playlistCount")
        layout.addWidget(self._count_label)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        sel_all = QPushButton("Select all")
        sel_none = QPushButton("Deselect all")
        sel_all.clicked.connect(self._select_all)
        sel_none.clicked.connect(self._deselect_all)
        toolbar.addWidget(sel_all)
        toolbar.addWidget(sel_none)
        toolbar.addStretch()

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by title…")
        self._filter_edit.setFixedWidth(200)
        self._filter_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_edit)
        layout.addLayout(toolbar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        self._list = QListWidget()
        self._list.setObjectName("playlistList")
        self._list.setSpacing(1)
        layout.addWidget(self._list, 1)


        self._selected_label = QLabel()
        self._selected_label.setObjectName("selectedCount")
        layout.addWidget(self._selected_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("Add to Queue")
        layout.addWidget(buttons)

    def _populate(self, entries: list[PlaylistEntry]) -> None:
        self._list.clear()
        self._checkboxes.clear()

        for entry in entries:
            item = QListWidgetItem()
            item.setSizeHint(item.sizeHint().__class__(0, 32))
            self._list.addItem(item)

            cb = QCheckBox()
            cb.setChecked(entry.available)
            cb.setEnabled(entry.available)

            dur_str = format_duration(entry.duration)

            avail_str = "" if entry.available else "  ⚠ Unavailable"
            label = f"{entry.index:3d}.  {entry.title}{avail_str}"
            if dur_str:
                label += f"    [{dur_str}]"
            cb.setText(label)
            cb.stateChanged.connect(self._update_count)

            self._list.setItemWidget(item, cb)
            self._checkboxes.append(cb)

        self._update_count()

    def _select_all(self) -> None:
        for cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(True)

    def _deselect_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            widget = self._list.itemWidget(item)
            if widget:
                visible = not text or text in widget.text().lower()
                item.setHidden(not visible)

    def _update_count(self) -> None:
        checked = sum(1 for cb in self._checkboxes if cb.isChecked())
        self._selected_label.setText(f"Selected: {checked} of {len(self._entries)}")
        self._ok_btn.setEnabled(checked > 0)

    def _accept(self) -> None:
        selected = [
            self._entries[i]
            for i, cb in enumerate(self._checkboxes)
            if cb.isChecked() and i < len(self._entries)
        ]
        self.entries_selected.emit(selected)
        self.accept()
