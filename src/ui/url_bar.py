from __future__ import annotations
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel, QApplication
)
from PyQt6.QtCore import pyqtSignal


def _normalize_url(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    if not (t.startswith("http://") or t.startswith("https://")):
        t = "https://" + t
    try:
        result = urlparse(t)
        if result.scheme in ("http", "https") and bool(result.netloc) and "." in result.netloc:
            return t
    except ValueError:
        pass
    return None


class SelectableLineEdit(QLineEdit):
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.selectAll()


class UrlBar(QWidget):
    analyze_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(6)

        self._label = QLabel("URL:")
        self._label.setObjectName("urlLabel")

        self._edit = SelectableLineEdit()
        self._edit.setObjectName("urlEdit")
        self._edit.setPlaceholderText("Paste video or playlist URL here…")
        self._edit.returnPressed.connect(self._emit)

        self._paste_btn = QPushButton("Paste URL")
        self._paste_btn.setObjectName("pasteLinkBtn")
        self._paste_btn.setFixedWidth(100)
        self._paste_btn.clicked.connect(self._paste_and_analyze)

        self._btn = QPushButton("Analyze")
        self._btn.setObjectName("analyzeBtn")
        self._btn.setFixedWidth(110)
        self._btn.clicked.connect(self._emit)

        layout.addWidget(self._label)
        layout.addWidget(self._edit, 1)
        layout.addWidget(self._paste_btn)
        layout.addWidget(self._btn)

    def _emit(self) -> None:
        if not self._btn.isEnabled():
            return
        url = self._edit.text().strip()
        normalized = _normalize_url(url)
        if normalized:
            if normalized != url:
                self._edit.setText(normalized)
            self.analyze_requested.emit(normalized)

    def _paste_and_analyze(self) -> None:
        if not self._btn.isEnabled():
            return
        text = QApplication.clipboard().text().strip()
        normalized = _normalize_url(text)
        if normalized:
            self._edit.setText(normalized)
            self.analyze_requested.emit(normalized)
        elif text:
            self._edit.setText(text)

    def set_url(self, url: str) -> None:
        self._edit.setText(url)

    def set_busy(self, busy: bool) -> None:
        self._btn.setEnabled(not busy)
        self._paste_btn.setEnabled(not busy)
        self._edit.setEnabled(not busy)
        self._btn.setText("Analyzing…" if busy else "Analyze")

    def clear(self) -> None:
        self._edit.clear()
