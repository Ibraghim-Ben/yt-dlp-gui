# yt-dlp-gui

[![Downloads](https://img.shields.io/github/downloads/Ibraghim-Ben/yt-dlp-gui/total?color=blue)](https://github.com/Ibraghim-Ben/yt-dlp-gui/releases)

A graphical interface for yt-dlp — download videos from YouTube and 1000+ other sites.

## Features

- Download video + audio, video only, or audio only
- Parallel downloads (up to 10 simultaneous)
- Playlist support with entry selection
- Format selector with resolution, FPS, codec, size info
- Embed thumbnail, metadata, subtitles
- Dark and light themes
- Configurable output directory and filename template
- Rate limiting and browser cookie support
- Download queue persisted across restarts

## Requirements

- Python 3.11+
- FFmpeg (auto-detected or set manually in Settings)

## Installation

```bash
pip install -e .
```

## Usage

```bash
python run_gui.py
```

Or after install:

```bash
yt-dlp-gui
```

## Build (Windows exe)

```bash
pyinstaller yt-dlp-gui.spec
```

## Dependencies

- PyQt6
- yt-dlp
- platformdirs
- curl-cffi
