from __future__ import annotations
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QAbstractItemView,
    QLabel, QRadioButton, QButtonGroup, QComboBox, QPushButton,
    QLineEdit, QFileDialog, QGroupBox, QHeaderView,
    QCheckBox,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QAbstractItemModel
)
from PyQt6.QtGui import QColor
from ..core.models import VideoInfo, FormatInfo, MediaType
from ..core.container_rules import resolve_container
from ..utils.theme import get_theme_color, get_theme_color_hex
from ..utils.formatters import format_filesize


def get_best_audio(formats: list[FormatInfo]) -> Optional[FormatInfo]:
    audio_formats = [f for f in formats if f.media_type == MediaType.AUDIO_ONLY]
    if not audio_formats:
        return None

    def _audio_rank(fmt: FormatInfo) -> tuple:
        note = (fmt.format_note or "").lower()
        is_original = "original" in note or "orig" in note
        is_dubbed = "dubbed" in note or "translation" in note or "translated" in note
        priority = 2 if is_original else (0 if is_dubbed else 1)
        abr = float(fmt.abr or 0)
        size = float(fmt.filesize or fmt.filesize_approx or 0)
        return (priority, abr, size)

    return max(audio_formats, key=_audio_rank)


_COLUMNS = ["Resolution", "FPS", "Video Codec", "Audio Codec", "Size", "Type", "Ext"]
_COL_IDX = {c: i for i, c in enumerate(_COLUMNS)}


class FormatTableModel(QAbstractTableModel):
    def __init__(self, formats: list[FormatInfo], parent=None):
        super().__init__(parent)
        self._formats = formats
        self._ext_header_name = "Ext"
        self._res_header_name = "Resolution"
        self._ui_mode = "video_audio"
        
        self._best_audio = get_best_audio(formats)

    def set_ui_mode(self, mode: str) -> None:
        if self._ui_mode != mode:
            self.layoutAboutToBeChanged.emit()
            self._ui_mode = mode
            self.layoutChanged.emit()

    def set_ext_header_name(self, name: str) -> None:
        if self._ext_header_name != name:
            self._ext_header_name = name
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, _COL_IDX["Ext"], _COL_IDX["Ext"])

    def set_res_header_name(self, name: str) -> None:
        if self._res_header_name != name:
            self._res_header_name = name
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, _COL_IDX["Resolution"], _COL_IDX["Resolution"])

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._formats)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == _COL_IDX["Ext"]:
                return self._ext_header_name
            if section == _COL_IDX["Resolution"]:
                return self._res_header_name
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        fmt = self._formats[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell_text(fmt, col)

        if role == Qt.ItemDataRole.EditRole:
            if col == _COL_IDX["Resolution"]:
                if self._res_header_name == "Bitrate":
                    val = fmt.abr if fmt.abr else (fmt.tbr if fmt.tbr else 0)
                    try: return float(val)
                    except (TypeError, ValueError): return 0.0
                try: return int(fmt.height)
                except (TypeError, ValueError): return 0
            if col == _COL_IDX["FPS"]:
                try: return float(fmt.fps)
                except (TypeError, ValueError): return 0.0
            if col == _COL_IDX["Size"]:
                size = fmt.filesize or fmt.filesize_approx or 0
                if paired := self._paired_audio(fmt):
                    size += paired.filesize or paired.filesize_approx or 0
                try: return int(size)
                except (TypeError, ValueError): return 0
            return self._cell_text(fmt, col)

        if role == Qt.ItemDataRole.ForegroundRole:
            if fmt.media_type == MediaType.AUDIO_ONLY:
                return get_theme_color("audioRow")
            if fmt.media_type == MediaType.VIDEO_ONLY:
                return get_theme_color("videoRow")
            return get_theme_color("mixedRow")

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

        if role == Qt.ItemDataRole.UserRole:
            return fmt

        return None

    def _paired_audio(self, fmt: FormatInfo) -> Optional[FormatInfo]:
        if self._ui_mode == "video_audio" and fmt.media_type == MediaType.VIDEO_ONLY:
            return self._best_audio
        return None

    def _cell_text(self, fmt: FormatInfo, col: int) -> str:
        if col == _COL_IDX["Resolution"]:
            if self._res_header_name == "Bitrate":
                return fmt.display_bitrate
            return fmt.display_resolution
        if col == _COL_IDX["FPS"]:
            return fmt.display_fps
        if col == _COL_IDX["Video Codec"]:
            return fmt.display_vcodec
        if col == _COL_IDX["Audio Codec"]:
            if paired := self._paired_audio(fmt):
                return paired.display_acodec
            return fmt.display_acodec
        if col == _COL_IDX["Size"]:
            if paired := self._paired_audio(fmt):
                s1 = fmt.filesize or fmt.filesize_approx or 0
                s2 = paired.filesize or paired.filesize_approx or 0
                return format_filesize(s1 + s2)
            return fmt.display_size
        if col == _COL_IDX["Type"]:
            return fmt.display_type
        if col == _COL_IDX["Ext"]:
            if paired := self._paired_audio(fmt):
                resolved = resolve_container(fmt.ext or "", paired.acodec)
                return resolved.upper()
            return fmt.ext.upper() if fmt.ext else "—"
        return ""

    def format_at(self, row: int) -> FormatInfo:
        return self._formats[row]

    @property
    def formats(self) -> list[FormatInfo]:
        return self._formats


class FormatFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "video_audio"
        self._has_video_only = False
        self._has_audio_only = False
        self._typed_source: FormatTableModel | None = None

    def setSourceModel(self, model: QAbstractItemModel | None) -> None:
        super().setSourceModel(model)
        if isinstance(model, FormatTableModel):
            self._typed_source = model
            self._has_video_only = any(f.media_type == MediaType.VIDEO_ONLY for f in model.formats)
            self._has_audio_only = any(f.media_type == MediaType.AUDIO_ONLY for f in model.formats)
        else:
            self._typed_source = None
            self._has_video_only = False
            self._has_audio_only = False

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self._typed_source is None:
            return False
        fmt: FormatInfo = self._typed_source.format_at(source_row)
        # mhtml/storyboards are pre-filtered at downloader.py level, kept here as a fallback
        if fmt.ext.lower() == "mhtml":
            return False
        if self._mode == "audio":
            return fmt.media_type == MediaType.AUDIO_ONLY
        if self._mode in ("video", "video_audio"):
            if self._has_video_only:
                return fmt.media_type == MediaType.VIDEO_ONLY
            return fmt.media_type == MediaType.VIDEO
        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.EditRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.EditRole)
        try:
            return left_data < right_data
        except TypeError:
            return str(left_data) < str(right_data)


class FormatSelector(QWidget):
    download_requested = pyqtSignal(object, object, str, str, bool, str, bool, bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_info: Optional[VideoInfo] = None
        self._model: Optional[FormatTableModel] = None
        self._proxy = FormatFilterProxy(self)
        self._proxy.setSortRole(Qt.ItemDataRole.EditRole)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self._info_label = QLabel("No video loaded")
        self._info_label.setObjectName("infoLabel")
        self._info_label.setWordWrap(True)
        self._info_label.setMinimumHeight(24)
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self._info_label)

        self._table = QTableView()
        self._table.setObjectName("formatTable")
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSortingEnabled(True)
        self._table.setModel(self._proxy)
        root.addWidget(self._table, 1)

        mode_group = QGroupBox("Mode")
        mode_group.setObjectName("modeGroup")
        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setContentsMargins(8, 4, 8, 4)
        mode_layout.setSpacing(16)
        self._bg = QButtonGroup(self)
        self._rb_video_audio = QRadioButton("Video + Audio")
        self._rb_video_only = QRadioButton("Video Only")
        self._rb_audio_only = QRadioButton("Audio Only")
        self._rb_video_audio.setChecked(True)
        for rb in (self._rb_video_audio, self._rb_video_only, self._rb_audio_only):
            self._bg.addButton(rb)
            mode_layout.addWidget(rb)
        mode_layout.addStretch()

        self._rb_audio_only.toggled.connect(self._on_mode_changed)
        self._rb_video_audio.toggled.connect(self._on_mode_changed)
        self._rb_video_only.toggled.connect(self._on_mode_changed)
        root.addWidget(mode_group)

        options_layout = QHBoxLayout()
        options_layout.setSpacing(12)
        
        self._embed_thumb_cb = QCheckBox("Embed Thumbnail")
        self._embed_thumb_cb.setChecked(True)
        self._embed_meta_cb = QCheckBox("Embed Metadata")
        self._embed_meta_cb.setChecked(True)
        
        self._subs_cb = QCheckBox("Embed Subtitles")
        self._subs_cb.setObjectName("subsCb")
        self._subs_cb.setChecked(False)
        
        self._subs_lang_cb = QComboBox()
        self._subs_lang_cb.setObjectName("subsLangCb")
        self._subs_lang_cb.setEnabled(False)
        self._subs_lang_cb.currentTextChanged.connect(self._update_subs_combo_width)
        self._subs_cb.toggled.connect(self._subs_lang_cb.setEnabled)
        
        options_layout.addWidget(self._embed_thumb_cb)
        options_layout.addWidget(self._embed_meta_cb)
        options_layout.addWidget(self._subs_cb)
        options_layout.addWidget(self._subs_lang_cb)

        self._audio_fmt_label = QLabel("Convert to:")
        self._audio_fmt_cb = QComboBox()
        self._audio_fmt_cb.setObjectName("audioFmtCb")
        self._audio_fmt_cb.setFixedWidth(90)
        self._audio_fmt_cb.addItem("Native", "")
        for fmt in ("mp3", "m4a", "flac", "opus", "wav", "ogg"):
            self._audio_fmt_cb.addItem(fmt.upper(), fmt)
        self._audio_fmt_label.setVisible(False)
        self._audio_fmt_cb.setVisible(False)
        options_layout.addWidget(self._audio_fmt_label)
        options_layout.addWidget(self._audio_fmt_cb)

        options_layout.addStretch()
        root.addLayout(options_layout)

        folder_layout = QHBoxLayout()
        folder_layout.setSpacing(6)
        self._folder_edit = QLineEdit()
        self._folder_edit.setObjectName("folderEdit")
        self._folder_edit.setPlaceholderText("Save to…")
        self._folder_btn = QPushButton("…")
        self._folder_btn.setObjectName("browseBtn")
        self._folder_btn.setFixedWidth(32)
        self._folder_btn.clicked.connect(self._pick_folder)
        folder_layout.addWidget(QLabel("Folder:"))
        folder_layout.addWidget(self._folder_edit, 1)
        folder_layout.addWidget(self._folder_btn)
        root.addLayout(folder_layout)

        self._download_btn = QPushButton("Add to Queue")
        self._download_btn.setObjectName("downloadBtn")
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._on_download)
        root.addWidget(self._download_btn)

    def load_video(self, video_info: VideoInfo, output_dir: str) -> None:
        self._video_info = video_info
        self._folder_edit.setText(output_dir)

        dur = video_info.display_duration
        ch = video_info.channel or ""
        subtitle_color = get_theme_color_hex("subtitleText")
        self._info_label.setText(
            f"<b>{video_info.title}</b><br>"
            f"<span style='color:{subtitle_color}'>{ch}  •  {dur}</span>"
        )

        if self._model is not None:
            self._model.deleteLater()

        self._model = FormatTableModel(video_info.formats)
        self._proxy.setSourceModel(self._model)
        self._apply_mode_to_proxy()
        
        self._subs_lang_cb.clear()
        self._subs_lang_cb.addItem("All", "all")
        if video_info.subtitles:
            default_index = -1
            for lang_code, lang_name in video_info.subtitles:
                if lang_name == lang_code:
                    display = lang_code
                elif f"({lang_code})" in lang_name:
                    display = lang_name
                else:
                    display = f"{lang_name} ({lang_code})"
                self._subs_lang_cb.addItem(display, lang_code)
                if default_index < 0 and lang_code.lower().startswith("en"):
                    default_index = self._subs_lang_cb.count() - 1
            if default_index >= 0:
                self._subs_lang_cb.setCurrentIndex(default_index)
            elif self._subs_lang_cb.count() > 1:
                self._subs_lang_cb.setCurrentIndex(1)
            self._update_subs_combo_width()
            self._subs_cb.setEnabled(True)
        else:
            self._update_subs_combo_width()
            self._subs_cb.setEnabled(False)
            self._subs_cb.setChecked(False)

    def _update_subs_combo_width(self) -> None:
        text = self._subs_lang_cb.currentText()
        if not text:
            self._subs_lang_cb.setFixedWidth(60)
            return
        text_width = self._subs_lang_cb.fontMetrics().horizontalAdvance(text)
        self._subs_lang_cb.setFixedWidth(max(60, text_width + 42))

    def clear(self) -> None:
        self._video_info = None
        self._proxy.setSourceModel(None)
        if self._model is not None:
            self._model.deleteLater()
            self._model = None
        self._info_label.setText("No video loaded")
        self._download_btn.setEnabled(False)
        self._subs_lang_cb.clear()
        self._update_subs_combo_width()
        self._subs_cb.setEnabled(False)
        self._subs_cb.setChecked(False)

    def set_output_dir(self, path: str) -> None:
        self._folder_edit.setText(path)

    def _on_mode_changed(self, checked: bool) -> None:
        if not checked:
            return
        self._apply_mode_to_proxy()

    def _apply_mode_to_proxy(self) -> None:
        if self._proxy is None or self._model is None:
            return
            
        fps_col = _COL_IDX["FPS"]
        vcodec_col = _COL_IDX["Video Codec"]
        audio_col = _COL_IDX["Audio Codec"]
        type_col = _COL_IDX["Type"]
            
        if self._rb_audio_only.isChecked():
            self._proxy.set_mode("audio")
            self._model.set_ui_mode("audio")
            self._table.setColumnHidden(fps_col, True)
            self._table.setColumnHidden(vcodec_col, True)
            self._table.setColumnHidden(audio_col, False)
            self._table.setColumnHidden(type_col, True)
            self._model.set_res_header_name("Bitrate")
            self._model.set_ext_header_name("Format")
        elif self._rb_video_only.isChecked():
            self._proxy.set_mode("video")
            self._model.set_ui_mode("video")
            self._table.setColumnHidden(fps_col, False)
            self._table.setColumnHidden(vcodec_col, False)
            self._table.setColumnHidden(audio_col, True)
            self._table.setColumnHidden(type_col, True)
            self._model.set_res_header_name("Resolution")
            self._model.set_ext_header_name("Format")
        else:
            self._proxy.set_mode("video_audio")
            self._model.set_ui_mode("video_audio")
            self._table.setColumnHidden(fps_col, False)
            self._table.setColumnHidden(vcodec_col, False)
            self._table.setColumnHidden(audio_col, False)
            self._table.setColumnHidden(type_col, True)
            self._model.set_res_header_name("Resolution")
            self._model.set_ext_header_name("Format")
            
        audio_only = self._rb_audio_only.isChecked()
        self._audio_fmt_label.setVisible(audio_only)
        self._audio_fmt_cb.setVisible(audio_only)

        if self._proxy.rowCount() > 0:
            self._table.selectRow(0)
            self._download_btn.setEnabled(True)
        else:
            self._download_btn.setEnabled(False)

    def _pick_folder(self) -> None:
        current = self._folder_edit.text() or ""
        path = QFileDialog.getExistingDirectory(self, "Select output folder", current)
        if path:
            self._folder_edit.setText(path)

    def _on_download(self) -> None:
        if not self._video_info:
            return

        output_dir = self._folder_edit.text().strip()

        selected_fmt: Optional[FormatInfo] = None
        audio_fmt: Optional[FormatInfo] = None

        sel = self._table.selectionModel()
        if sel and sel.hasSelection() and self._model and self._proxy:
            src_idx = self._proxy.mapToSource(sel.selectedRows()[0])
            selected_fmt = self._model.format_at(src_idx.row())

        if self._rb_audio_only.isChecked():
            mode = "audio"
        elif self._rb_video_only.isChecked():
            mode = "video"
        else:
            mode = "video_audio"
            if selected_fmt and selected_fmt.media_type == MediaType.VIDEO_ONLY:
                audio_fmt = get_best_audio(self._video_info.formats)

        if not selected_fmt and mode != "audio":
            return

        self.download_requested.emit(
            selected_fmt,
            audio_fmt,
            mode,
            output_dir,
            self._subs_cb.isChecked(),
            self._subs_lang_cb.currentData() or "all",
            self._embed_thumb_cb.isChecked(),
            self._embed_meta_cb.isChecked(),
            self._audio_fmt_cb.currentData() if mode == "audio" else "",
        )
