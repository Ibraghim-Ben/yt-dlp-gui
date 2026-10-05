from __future__ import annotations
import os
import shutil
import subprocess
import sys


def find_ffmpeg() -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bundled = os.path.join(base_dir, "resources", "bin", exe_name)
    if os.path.isfile(bundled):
        return bundled

    meipass_bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "bin", exe_name)
    if os.path.isfile(meipass_bundled):
        return meipass_bundled

    custom = os.environ.get("FFMPEG_PATH", "")
    if custom and os.path.isfile(custom):
        return custom

    found = shutil.which("ffmpeg")
    if found:
        return found

    if sys.platform == "win32":
        candidates = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path

    if sys.platform == "darwin":
        for path in ["/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"]:
            if os.path.isfile(path):
                return path

    return ""


def find_deno() -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))
    exe_name = "deno.exe" if sys.platform == "win32" else "deno"
    bundled = os.path.join(base_dir, "resources", "bin", exe_name)
    if os.path.isfile(bundled):
        return bundled

    meipass_bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "bin", exe_name)
    if os.path.isfile(meipass_bundled):
        return meipass_bundled

    custom = os.environ.get("DENO_PATH", "")
    if custom and os.path.isfile(custom):
        return custom

    found = shutil.which("deno")
    if found:
        return found

    if sys.platform == "win32":
        candidates = [
            os.path.join(os.path.expanduser("~"), ".deno", "bin", "deno.exe"),
            r"C:\Program Files\deno\deno.exe",
            os.path.join(os.path.dirname(sys.executable), "deno.exe"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path

    return ""


def setup_bundled_binaries() -> dict[str, str]:
    """Ensures bundled external binaries (ffmpeg, ffprobe, deno) are on PATH and detectable."""
    base_dir = os.path.dirname(os.path.dirname(__file__))
    candidates = [
        os.path.join(base_dir, "resources", "bin"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "bin"),
        os.path.dirname(sys.executable),
    ]

    current_path = os.environ.get("PATH", "")
    path_dirs = [os.path.abspath(p) for p in current_path.split(os.pathsep) if p]
    new_dirs: list[str] = []

    for d in candidates:
        if d and os.path.isdir(d):
            abs_d = os.path.abspath(d)
            if abs_d not in path_dirs and abs_d not in new_dirs:
                new_dirs.append(abs_d)

    if new_dirs:
        os.environ["PATH"] = os.pathsep.join(new_dirs + [current_path])

    deno = find_deno()
    if deno:
        os.environ["DENO_PATH"] = deno

    ffmpeg = find_ffmpeg()
    if ffmpeg and "FFMPEG_PATH" not in os.environ:
        os.environ["FFMPEG_PATH"] = ffmpeg

    return {"deno": deno, "ffmpeg": ffmpeg}


def validate_ffmpeg(path: str) -> tuple[bool, str]:
    if not path:
        return False, "FFmpeg path is empty"
    if not os.path.isfile(path):
        return False, f"File not found: {path}"
    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": 5,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            
        result = subprocess.run([path, "-version"], **kwargs)
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0] if result.stdout else ""
            return True, first_line
        return False, "ffmpeg returned non-zero exit code"
    except Exception as e:
        return False, str(e)
