from __future__ import annotations
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QFrame, QMessageBox, QWidget,
)
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtCore import Qt, QRectF, QPoint
from ..utils.formatters import format_filesize
from ..utils.theme import get_theme_color, get_theme_color_hex
from ..core.stats_manager import StatsManager


class StatCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setStyleSheet("""
            QFrame#statCard {
                border: 1px solid rgba(128, 128, 128, 0.25);
                border-radius: 8px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self._title_label = QLabel(title)
        sub_color = get_theme_color_hex("subtitleText")
        self._title_label.setStyleSheet(f"color: {sub_color}; font-size: 9pt;")
        layout.addWidget(self._title_label)

        self._value_label = QLabel("—")
        self._value_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(self._value_label)

    def set_value(self, val: str) -> None:
        self._value_label.setText(val)


class StatBarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self._data: list[dict] = []
        self._hovered_idx: int = -1
        self._bars: list[tuple[QRectF, dict]] = []

    def set_data(self, data: list[dict]) -> None:
        self._data = data
        self._hovered_idx = -1
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        old_idx = self._hovered_idx
        self._hovered_idx = -1
        for i, (rect, item) in enumerate(self._bars):
            if rect.contains(pos.x(), pos.y()) or (
                rect.x() <= pos.x() <= rect.x() + rect.width()
                and 0 <= pos.y() <= self.height()
            ):
                self._hovered_idx = i
                break

        if self._hovered_idx != old_idx:
            self.update()

        if 0 <= self._hovered_idx < len(self._data):
            d = self._data[self._hovered_idx]
            tip = f"{d['label']} ({d['date']})\n{format_filesize(d['bytes'])}\n{d['count']} {self.tr('files')}"
            self.setToolTip(tip)
        else:
            self.setToolTip("")

        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered_idx = -1
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        margin_left = 70
        margin_right = 20
        margin_top = 30
        margin_bottom = 35

        plot_x = margin_left
        plot_y = margin_top
        plot_w = max(10, w - margin_left - margin_right)
        plot_h = max(10, h - margin_top - margin_bottom)

        sub_color = get_theme_color("subtitleText")
        bar_color = get_theme_color("videoRow")
        grid_pen = QPen(QColor(128, 128, 128, 50), 1, Qt.PenStyle.DashLine)

        max_bytes = max((int(d.get("bytes", 0)) for d in self._data), default=0)
        chart_max = max(max_bytes * 1.15, 1024 * 1024)

        ticks = 4
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        for i in range(ticks + 1):
            fraction = i / ticks
            y = plot_y + plot_h - (fraction * plot_h)
            val = chart_max * fraction

            painter.setPen(grid_pen)
            painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))

            painter.setPen(sub_color)
            val_str = format_filesize(val) if val > 0 else "0"
            painter.drawText(
                QRectF(0, y - 9, margin_left - 8, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                val_str,
            )

        self._bars = []
        n = len(self._data)
        if n == 0 or max_bytes == 0:
            painter.setPen(sub_color)
            font_msg = painter.font()
            font_msg.setPointSize(11)
            painter.setFont(font_msg)
            painter.drawText(
                QRectF(plot_x, plot_y, plot_w, plot_h),
                Qt.AlignmentFlag.AlignCenter,
                self.tr("No download activity"),
            )
            return

        slot_w = plot_w / n
        bar_w = max(4.0, min(slot_w * 0.62, 34.0))

        step = 1
        if n > 14:
            step = 3 if n <= 21 else 5

        for i, item in enumerate(self._data):
            b = int(item.get("bytes", 0))
            bar_h = (b / chart_max) * plot_h if chart_max > 0 else 0
            bar_x = plot_x + (i * slot_w) + ((slot_w - bar_w) / 2)
            bar_y = plot_y + plot_h - bar_h

            rect = QRectF(bar_x, bar_y, bar_w, max(2.0, bar_h))
            self._bars.append((rect, item))

            is_hovered = (i == self._hovered_idx)
            current_bar_color = bar_color.lighter(125) if is_hovered else bar_color

            if bar_h > 0:
                painter.setBrush(QBrush(current_bar_color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(rect, 3.0, 3.0)

            if i % step == 0 or i == n - 1:
                painter.setPen(sub_color)
                painter.drawText(
                    QRectF(plot_x + (i * slot_w) - 10, plot_y + plot_h + 8, slot_w + 20, 20),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    item.get("label", ""),
                )


class StatsDialog(QDialog):
    def __init__(self, stats_manager: StatsManager, parent=None):
        super().__init__(parent)
        self._stats = stats_manager
        self.setWindowTitle(self.tr("Download Statistics"))
        self.setMinimumSize(680, 520)
        self.resize(720, 540)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        period_label = QLabel(self.tr("Period:"))
        top_bar.addWidget(period_label)

        self._period_combo = QComboBox()
        self._period_combo.addItem(self.tr("Last 7 days"), 7)
        self._period_combo.addItem(self.tr("Last 30 days"), 30)
        self._period_combo.addItem(self.tr("All time"), 0)
        self._period_combo.currentIndexChanged.connect(self._refresh)
        top_bar.addWidget(self._period_combo)

        top_bar.addStretch()

        self._clear_btn = QPushButton(self.tr("Clear statistics"))
        self._clear_btn.clicked.connect(self._on_clear)
        top_bar.addWidget(self._clear_btn)

        layout.addLayout(top_bar)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self._card_total = StatCard(self.tr("Total downloaded"))
        cards_layout.addWidget(self._card_total)

        self._card_files = StatCard(self.tr("Downloaded files"))
        cards_layout.addWidget(self._card_files)

        self._card_avg = StatCard(self.tr("Daily average"))
        cards_layout.addWidget(self._card_avg)

        layout.addLayout(cards_layout)

        chart_header = QLabel(self.tr("Daily Activity"))
        chart_header.setStyleSheet("font-weight: 600; font-size: 11pt;")
        layout.addWidget(chart_header)

        self._chart = StatBarChart()
        layout.addWidget(self._chart, 1)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()

        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)

        layout.addLayout(bottom_layout)

    def _refresh(self) -> None:
        data = self._period_combo.currentData()
        days = 7 if data is None else data
        summary = self._stats.get_summary(days=days if days > 0 else None)
        daily = self._stats.get_daily(days=days)

        self._card_total.set_value(format_filesize(summary["total_bytes"]))
        self._card_files.set_value(str(summary["total_count"]))

        num_days = days if days > 0 else max(1, len(daily))
        avg = summary["total_bytes"] / max(1, num_days)
        self._card_avg.set_value(f"{format_filesize(avg)} / {self.tr('day')}")

        self._chart.set_data(daily)

    def _on_clear(self) -> None:
        ret = QMessageBox.question(
            self,
            self.tr("Clear statistics"),
            self.tr("Are you sure you want to clear all download statistics?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self._stats.clear()
            self._refresh()
