from __future__ import annotations
import logging
import pathlib
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication


import sys

def _themes_dir() -> pathlib.Path:
    candidates = [
        pathlib.Path(__file__).parent.parent / "resources" / "themes",
        pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "src" / "resources" / "themes",
        pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "resources" / "themes",
        pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "themes"
    ]
    for p in candidates:
        if p.exists() and (p / "dark.qss").exists():
            return p
    return pathlib.Path(__file__).parent.parent / "resources" / "themes"

_THEME_COLORS: dict[str, str] = {}

_DARK_COLORS: dict[str, str] = {
    "audioRow":    "#a6e3a1",
    "videoRow":    "#89b4fa",
    "mixedRow":    "#cdd6f4",
    "subtitleText":"#a6adc8",
    "logDebug":    "#585b70",
    "logInfo":     "#cdd6f4",
    "logWarning":  "#f9e2af",
    "logError":    "#f38ba8",
}

_LIGHT_COLORS: dict[str, str] = {
    "audioRow":    "#40a02b",
    "videoRow":    "#1e66f5",
    "mixedRow":    "#4c4f69",
    "subtitleText":"#7c7f93",
    "logDebug":    "#acb0be",
    "logInfo":     "#4c4f69",
    "logWarning":  "#df8e1d",
    "logError":    "#d20f39",
}


def get_theme_color(key: str) -> QColor:
    hex_val = _THEME_COLORS.get(key, "#cdd6f4")
    return QColor(hex_val)


def get_theme_color_hex(key: str) -> str:
    return _THEME_COLORS.get(key, "#cdd6f4")


def load_theme(app: QApplication, theme: str) -> None:
    global _THEME_COLORS
    
    tdir = _themes_dir()
    qss_file = tdir / f"{theme}.qss"
    if not qss_file.exists():
        qss_file = tdir / "dark.qss"
        
    try:
        app.setStyleSheet(qss_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logging.warning("Theme file not found: %s", qss_file)
        
    _THEME_COLORS = dict(_LIGHT_COLORS if theme == "light" else _DARK_COLORS)