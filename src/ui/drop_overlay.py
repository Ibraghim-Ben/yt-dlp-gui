from __future__ import annotations
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPaintEvent


class DropOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        is_dark = self.palette().window().color().lightness() < 128

        if is_dark:
            dim_color = QColor(10, 15, 28, 225)
            card_bg = QColor(17, 24, 39, 210)
            border_color = QColor(59, 130, 246, 240)
            icon_color = QColor(96, 165, 250)
            title_color = QColor(255, 255, 255)
            subtitle_color = QColor(148, 163, 184)
        else:
            dim_color = QColor(241, 245, 249, 225)
            card_bg = QColor(255, 255, 255, 220)
            border_color = QColor(37, 99, 235, 240)
            icon_color = QColor(37, 99, 235)
            title_color = QColor(15, 23, 42)
            subtitle_color = QColor(71, 85, 105)

        painter.fillRect(self.rect(), dim_color)

        card_w = min(float(self.width()) - 48, 520.0)
        card_h = min(float(self.height()) - 48, 220.0)
        card_x = (self.width() - card_w) / 2.0
        card_y = (self.height() - card_h) / 2.0
        card_rect = QRectF(card_x, card_y, card_w, card_h)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(card_bg))
        painter.drawRoundedRect(card_rect, 16, 16)

        border_pen = QPen(border_color, 2.5, Qt.PenStyle.DashLine)
        border_pen.setDashPattern([6, 5])
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card_rect, 16, 16)

        icon_font = QFont(self.font())
        icon_font.setPointSize(34)
        icon_font.setBold(True)
        painter.setFont(icon_font)
        painter.setPen(icon_color)
        painter.drawText(QRectF(card_rect.x(), card_rect.y() + 20, card_rect.width(), 48), Qt.AlignmentFlag.AlignCenter, "📥")

        title_font = QFont(self.font())
        title_font.setPointSize(14)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(QRectF(card_rect.x(), card_rect.y() + 80, card_rect.width(), 32), Qt.AlignmentFlag.AlignCenter, "Drop link here to download")

        sub_font = QFont(self.font())
        sub_font.setPointSize(10)
        painter.setFont(sub_font)
        painter.setPen(subtitle_color)
        painter.drawText(QRectF(card_rect.x(), card_rect.y() + 116, card_rect.width(), 26), Qt.AlignmentFlag.AlignCenter, "Release to paste URL and start auto-analysis")
