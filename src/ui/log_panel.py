from __future__ import annotations
from collections import deque
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QComboBox,
)
from PyQt6.QtGui import QTextCharFormat, QTextCursor, QFont
from ..utils.theme import get_theme_color


_LEVEL_COLOR_KEYS: dict[str, str] = {
    "debug":   "logDebug",
    "info":    "logInfo",
    "warning": "logWarning",
    "error":   "logError",
}

_LEVEL_ORDER = {"debug": 0, "info": 1, "warning": 2, "error": 3}


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logs: deque[tuple[str, str]] = deque(maxlen=300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Log"))

        self._level_combo = QComboBox()
        self._level_combo.setObjectName("logLevelCombo")
        self._level_combo.addItems(["All", "INFO", "WARNING", "ERROR"])
        self._level_combo.setFixedWidth(120)
        top.addWidget(self._level_combo)
        top.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("logClearBtn")
        self._clear_btn.setFixedWidth(60)
        top.addWidget(self._clear_btn)
        layout.addLayout(top)

        self._text = QTextEdit()
        self._text.setObjectName("logText")
        self._text.setReadOnly(True)
        mono_font = QFont()
        mono_font.setFamilies(["Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono", "monospace"])
        mono_font.setPointSize(9)
        self._text.setFont(mono_font)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.document().setMaximumBlockCount(300)
        layout.addWidget(self._text)

        self._clear_btn.clicked.connect(self.clear)

        self._min_level = "all"
        self._level_combo.currentTextChanged.connect(self._on_level_change)

    def _on_level_change(self, text: str) -> None:
        self._min_level = text.lower()
        self._refresh_logs()

    def _refresh_logs(self) -> None:
        self._text.clear()
        for level, message in self._logs:
            self._append_to_ui(level, message)

    def append(self, level: str, message: str) -> None:
        level = level.lower()
        self._logs.append((level, message))
        self._append_to_ui(level, message)

    def _append_to_ui(self, level: str, message: str) -> None:
        if self._min_level != "all":
            if _LEVEL_ORDER.get(level, 1) < _LEVEL_ORDER.get(self._min_level, 1):
                return

        color_key = _LEVEL_COLOR_KEYS.get(level, "logInfo")
        color = get_theme_color(color_key)
        prefix = f"[{level.upper():7s}] "

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.setCharFormat(fmt)
        cursor.insertText(prefix + message + "\n")

        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()

    def clear(self) -> None:
        self._logs.clear()
        self._text.clear()
