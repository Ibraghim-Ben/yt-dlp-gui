from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QComboBox,
    QSpinBox, QDialogButtonBox,
    QFormLayout, QMessageBox, QApplication, QPushButton, QFileDialog,
)
from PyQt6.QtGui import QDoubleValidator
from ..utils.config import Config
from ..utils.theme import load_theme
from ..core.ffmpeg_utils import validate_ffmpeg


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Settings")
        self.setMinimumSize(580, 460)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._network_tab(), "Network")
        tabs.addTab(self._ffmpeg_tab(), "FFmpeg")

        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _general_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self._template = QLineEdit()
        self._template.setPlaceholderText("[title] - [uploader].[ext]")
        form.addRow("Filename template:", self._template)

        hint = QLabel("Available: [title]  [uploader]  [id]  [ext]  [resolution]")
        hint.setObjectName("hintLabel")
        form.addRow("", hint)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        form.addRow("Theme:", self._theme_combo)

        self._parallel_spin = QSpinBox()
        self._parallel_spin.setMinimum(1)
        self._parallel_spin.setMaximum(10)
        form.addRow("Parallel downloads:", self._parallel_spin)

        parallel_hint = QLabel("Maximum 10 concurrent downloads")
        parallel_hint.setObjectName("hintLabel")
        form.addRow("", parallel_hint)

        return w

    def _network_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self._rate_val = QLineEdit()
        self._rate_val.setPlaceholderText("Unlimited")
        val_validator = QDoubleValidator(0.0, 999999.0, 2, self)
        val_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._rate_val.setValidator(val_validator)
        self._rate_unit = QComboBox()
        self._rate_unit.addItems(["KB/s", "MB/s"])
        self._rate_unit.setFixedWidth(80)

        row = QHBoxLayout()
        row.addWidget(self._rate_val, 1)
        row.addWidget(self._rate_unit)
        form.addRow("Rate limit:", row)

        self._cookies_browser = QComboBox()
        self._cookies_browser.addItems(["", "chrome", "firefox", "edge", "safari", "opera", "brave", "vivaldi", "yandex", "tor", "duckduckgo", "whale"])
        form.addRow("Cookies from browser:", self._cookies_browser)

        hint = QLabel("Used for age-restricted or login-required content.")
        hint.setObjectName("hintLabel")
        form.addRow("", hint)

        return w

    def _ffmpeg_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        path_row = QHBoxLayout()
        self._ffmpeg_path = QLineEdit()
        self._ffmpeg_path.setPlaceholderText("Auto-detected")
        
        check_btn = QPushButton("Check")
        check_btn.setFixedWidth(70)
        check_btn.clicked.connect(self._on_ffmpeg_path_changed)
        
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_ffmpeg)
        path_row.addWidget(self._ffmpeg_path, 1)
        path_row.addWidget(check_btn)
        path_row.addWidget(browse_btn)
        form.addRow("FFmpeg path:", path_row)

        self._ffmpeg_status = QLabel("")
        self._ffmpeg_status.setObjectName("hintLabel")
        self._ffmpeg_status.setWordWrap(True)
        form.addRow("", self._ffmpeg_status)

        hint = QLabel("Leave empty to use auto-detected FFmpeg.")
        hint.setObjectName("hintLabel")
        form.addRow("", hint)

        return w

    def _browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FFmpeg executable", "",
            "FFmpeg (ffmpeg ffmpeg.exe);;All Files (*)"
        )
        if path:
            self._ffmpeg_path.setText(path)

    def _on_ffmpeg_path_changed(self) -> None:
        text = self._ffmpeg_path.text().strip()
        if not text:
            self._ffmpeg_status.setText("")
            return
        ok, msg = validate_ffmpeg(text)
        if ok:
            self._ffmpeg_status.setStyleSheet("color: #4caf50;")
            self._ffmpeg_status.setText(f"✓ {msg}")
        else:
            self._ffmpeg_status.setStyleSheet("color: #f44336;")
            self._ffmpeg_status.setText(f"✗ {msg}")
    def _load(self) -> None:
        cfg = self._config
        def to_ui_format(tmpl: str) -> str:
            return tmpl.replace("%(title)s", "[title]").replace("%(uploader)s", "[uploader]").replace("%(id)s", "[id]").replace("%(ext)s", "[ext]").replace("%(resolution)s", "[resolution]")
        self._template.setText(to_ui_format(cfg.output_template))
        idx = self._theme_combo.findText(cfg.theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._parallel_spin.setValue(cfg.max_parallel)
        
        limit = cfg.rate_limit
        if limit:
            val_part = "".join(c for c in limit if c.isdigit() or c == ".")
            unit_part = "".join(c for c in limit if c.isalpha())
            self._rate_val.setText(val_part)
            unit_map = {"k": "KB/s", "m": "MB/s", "kb": "KB/s", "mb": "MB/s"}
            matched_unit = unit_map.get(unit_part.lower(), "KB/s")
            idx_unit = self._rate_unit.findText(matched_unit)
            if idx_unit >= 0:
                self._rate_unit.setCurrentIndex(idx_unit)
        else:
            self._rate_val.setText("")

        idx = self._cookies_browser.findText(cfg.cookies_browser)
        if idx >= 0:
            self._cookies_browser.setCurrentIndex(idx)

        self._ffmpeg_path.setText(cfg.ffmpeg_path or "")

    def _save_and_accept(self) -> None:
        cfg = self._config
        def to_ytdlp_format(tmpl: str) -> str:
            return tmpl.replace("[title]", "%(title)s").replace("[uploader]", "%(uploader)s").replace("[id]", "%(id)s").replace("[ext]", "%(ext)s").replace("[resolution]", "%(resolution)s")
        new_template = to_ytdlp_format(self._template.text().strip())
        cfg.output_template = new_template or cfg.output_template
        cfg.theme = self._theme_combo.currentText()
        cfg.max_parallel = self._parallel_spin.value()
        
        rate_v = self._rate_val.text().strip()
        if rate_v:
            unit = "K" if self._rate_unit.currentText() == "KB/s" else "M"
            cfg.rate_limit = f"{rate_v}{unit}"
        else:
            cfg.rate_limit = ""

        cfg.cookies_browser = self._cookies_browser.currentText()

        ffmpeg_val = self._ffmpeg_path.text().strip()
        if ffmpeg_val:
            ok, msg = validate_ffmpeg(ffmpeg_val)
            if ok:
                cfg.ffmpeg_path = ffmpeg_val
            else:
                QMessageBox.warning(self, "Invalid FFmpeg", f"The specified FFmpeg path is not valid:\n{ffmpeg_val}\n\nReason: {msg}")
                return
        else:
            cfg.ffmpeg_path = ""
        try:
            cfg.save()
        except Exception as e:
            QMessageBox.warning(self, "Save Settings Failed", f"Could not save configuration:\n{e}")
        load_theme(QApplication.instance(), cfg.theme)
        self.accept()
