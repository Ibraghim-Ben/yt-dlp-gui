from __future__ import annotations
import os
import re
import socket
import threading
import time
import json
import random
from typing import Optional


def _hex_to_ass_color(hex_str: str) -> str:
    if not hex_str or not hex_str.startswith("#") or len(hex_str) != 7:
        colors = ["&H55E28A&", "&HFFD700&", "&H00D7FF&", "&HFF8080&", "&HB366FF&", "&H4DFFB8&"]
        return random.choice(colors)
    hex_str = hex_str[1:]
    r, g, b = hex_str[0:2], hex_str[2:4], hex_str[4:6]
    return f"&H{b}{g}{r}&"


def _format_ass_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass_subtitles(messages: list[tuple[float, str, str, str]], output_path: str, title: str = "Live Chat") -> bool:
    try:
        lines = [
            "[Script Info]",
            f"Title: {title}",
            "ScriptType: v4.00+",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: None",
            "PlayResX: 1920",
            "PlayResY: 1080",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Chat,Segoe UI,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,1.5,1,3,40,40,40,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        duration = 7.0
        for start_sec, user, color, text in messages:
            end_sec = start_sec + duration
            start_str = _format_ass_time(start_sec)
            end_str = _format_ass_time(end_sec)
            clean_user = re.sub(r'[{}]', '', user).strip()
            clean_text = re.sub(r'[{}]', '', text).strip()
            if not clean_text:
                continue
            color_ass = _hex_to_ass_color(color)
            dialogue = f"Dialogue: 0,{start_str},{end_str},Chat,,0,0,0,,{{\\b1\\c{color_ass}}}{clean_user}:{{\\b0\\c&HFFFFFF&}} {clean_text}"
            lines.append(dialogue)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception:
        return False


def find_live_chat_file(base_stem: str, output_dir: str = "") -> Optional[str]:
    for cand in (base_stem + ".live_chat.json", base_stem + ".live_chat.json.part"):
        if os.path.isfile(cand) and os.path.getsize(cand) > 0:
            return cand
    if output_dir and os.path.isdir(output_dir):
        import glob
        matches = sorted(
            glob.glob(os.path.join(output_dir, "*.live_chat.json*")),
            key=os.path.getmtime,
            reverse=True,
        )
        for m in matches:
            if os.path.isfile(m) and os.path.getsize(m) > 0:
                return m
    return None


def convert_youtube_live_chat_to_ass(json_path: str, output_ass_path: str) -> bool:
    if not os.path.isfile(json_path):
        return False
    messages: list[tuple[float, str, str, str]] = []
    try:
        with open(json_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    action = data.get("replayChatItemAction", {})
                    actions = action.get("actions", [])
                    for act in actions:
                        item = act.get("addChatItemAction", {}).get("item", {})
                        if not item:
                            item = act.get("item", {})
                        renderer = (
                            item.get("liveChatTextMessageRenderer")
                            or item.get("liveChatPaidMessageRenderer")
                            or item.get("liveChatMembershipItemRenderer")
                        )
                        if not renderer:
                            continue
                        author_dict = renderer.get("authorName", {})
                        author = author_dict.get("simpleText") or "".join(r.get("text", "") for r in author_dict.get("runs", []) if "text" in r) or "User"
                        runs = renderer.get("message", {}).get("runs", [])
                        text = "".join(r.get("text", "") for r in runs if "text" in r)
                        if not text and "headerSubtext" in renderer:
                            header_runs = renderer.get("headerSubtext", {}).get("runs", [])
                            text = "".join(r.get("text", "") for r in header_runs if "text" in r)
                        offset_usec = int(data.get("videoOffsetTimeMsec") or 0)
                        offset_sec = max(0.0, offset_usec / 1000.0)
                        if text:
                            messages.append((offset_sec, author, "", text))
                except Exception:
                    continue
        if not messages:
            return False
        messages.sort(key=lambda x: x[0])
        return write_ass_subtitles(messages, output_ass_path, "YouTube Live Chat")
    except Exception:
        return False


class YouTubeChatRecorder(threading.Thread):
    def __init__(self, url: str, ydl_opts: dict):
        super().__init__(daemon=True)
        self._url = url
        self._ydl_opts = ydl_opts
        self._ydl = None
        self._stopped = False

    def start_recording(self) -> None:
        self.start()

    def run(self) -> None:
        import yt_dlp
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": ["live_chat"],
            "outtmpl": self._ydl_opts.get("outtmpl", "%(title)s [%(id)s].%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "ignoreerrors": True,
        }
        for k in ("cookiesfrombrowser", "cookiefile", "proxy", "http_headers", "extractor_args", "nocheckcertificate", "ffmpeg_location"):
            if k in self._ydl_opts:
                opts[k] = self._ydl_opts[k]

        recorder = self

        class _ChatYoutubeDL(yt_dlp.YoutubeDL):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._open_streams = []

            def sanitize_open(self, filename, open_mode="r"):
                stream, name = super().sanitize_open(filename, open_mode)
                if hasattr(stream, "close"):
                    self._open_streams.append(stream)
                return stream, name

            def close_open_streams(self):
                for s in self._open_streams:
                    try:
                        s.close()
                    except Exception:
                        pass
                self._open_streams.clear()

            def urlopen(self, req):
                if recorder._stopped:
                    self.close_open_streams()
                    raise yt_dlp.utils.DownloadCancelled()
                return super().urlopen(req)

        try:
            with _ChatYoutubeDL(opts) as ydl:
                self._ydl = ydl
                ydl.download([self._url])
        except Exception:
            pass
        finally:
            if self._ydl and hasattr(self._ydl, "close_open_streams"):
                self._ydl.close_open_streams()
            self._ydl = None

    def stop(self) -> None:
        self._stopped = True
        ydl = self._ydl
        if ydl and hasattr(ydl, "close_open_streams"):
            ydl.close_open_streams()
        if self.is_alive():
            self.join(timeout=2.0)

    def stop_and_save(self, output_ass_path: str, output_dir: str = "") -> bool:
        self.stop()
        base_stem = output_ass_path.rsplit(".", 1)[0]
        live_chat_json = find_live_chat_file(base_stem, output_dir)
        if live_chat_json and os.path.isfile(live_chat_json):
            if convert_youtube_live_chat_to_ass(live_chat_json, output_ass_path):
                try:
                    os.remove(live_chat_json)
                except OSError:
                    pass
                return True
        return False


class TwitchChatRecorder(threading.Thread):
    def __init__(self, channel: str):
        super().__init__(daemon=True)
        self._channel = channel.lower().strip().lstrip("#")
        self._stopped = False
        self._sock: Optional[socket.socket] = None
        self._start_time: float = 0.0
        self._messages: list[tuple[float, str, str, str]] = []
        self._lock = threading.Lock()

    def start_recording(self) -> None:
        self._start_time = time.monotonic()
        self.start()

    def stop_and_save(self, output_ass_path: str) -> bool:
        self._stopped = True
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
                self._sock.close()
            except Exception:
                pass
        self.join(timeout=3.0)
        with self._lock:
            if not self._messages:
                return False
            return write_ass_subtitles(self._messages, output_ass_path, f"Twitch Chat #{self._channel}")

    def run(self) -> None:
        if not self._channel:
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock = s
            s.settimeout(6.0)
            s.connect(("irc.chat.twitch.tv", 6667))
            s.sendall(b"CAP REQ :twitch.tv/tags\r\n")
            rand_id = random.randint(10000, 99999)
            s.sendall(f"NICK justinfan{rand_id}\r\n".encode("utf-8"))
            s.sendall(f"JOIN #{self._channel}\r\n".encode("utf-8"))

            buf = ""
            while not self._stopped:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\r\n" in buf:
                        line, buf = buf.split("\r\n", 1)
                        self._process_line(line)
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception:
            pass
        finally:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass

    def _process_line(self, line: str) -> None:
        if line.startswith("PING"):
            try:
                if self._sock:
                    self._sock.sendall(b"PONG :tmi.twitch.tv\r\n")
            except Exception:
                pass
            return

        if "PRIVMSG" not in line:
            return

        tags_dict: dict[str, str] = {}
        msg_part = line
        if line.startswith("@"):
            parts = line[1:].split(" ", 1)
            raw_tags = parts[0]
            msg_part = parts[1] if len(parts) > 1 else ""
            for tag in raw_tags.split(";"):
                if "=" in tag:
                    k, v = tag.split("=", 1)
                    tags_dict[k] = v

        m = re.search(r':([^!]+)![^@]+@[^\s]+\s+PRIVMSG\s+#[^\s]+\s+:(.*)', msg_part)
        if not m:
            return

        raw_user = m.group(1)
        text = m.group(2)
        display_name = tags_dict.get("display-name") or raw_user
        color = tags_dict.get("color") or ""

        now = time.monotonic()
        offset = max(0.0, now - self._start_time)
        with self._lock:
            self._messages.append((offset, display_name, color, text))
