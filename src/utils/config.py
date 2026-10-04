from __future__ import annotations
import json
import pathlib
from dataclasses import dataclass, asdict, field
from platformdirs import user_config_dir, user_data_dir


_CONFIG_DIR = pathlib.Path(user_config_dir("ytdlp-gui", appauthor=False))
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_DATA_DIR = pathlib.Path(user_data_dir("ytdlp-gui", appauthor=False))


@dataclass
class Config:
    output_dir: str = str(pathlib.Path.home() / "Downloads")
    output_template: str = "%(title)s - %(uploader)s.%(ext)s"
    max_parallel: int = 2
    theme: str = "dark"
    ffmpeg_path: str = ""
    rate_limit: str = ""
    cookies_browser: str = ""
    download_archive: str = ""
    window_geometry: str = ""
    corrupted_backup_path: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            self.max_parallel = max(1, min(10, int(self.max_parallel)))
        except (TypeError, ValueError):
            self.max_parallel = 2
        if not isinstance(self.window_geometry, str):
            self.window_geometry = ""

    @staticmethod
    def load() -> "Config":
        if _CONFIG_FILE.exists():
            try:
                data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
                valid = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
                return Config(**{**asdict(Config()), **valid})
            except Exception:
                try:
                    corrupted_path = _CONFIG_FILE.with_suffix(".json.corrupted")
                    if _CONFIG_FILE.exists():
                        if corrupted_path.exists():
                            corrupted_path.unlink()
                        _CONFIG_FILE.rename(corrupted_path)
                        cfg = Config()
                        cfg.corrupted_backup_path = str(corrupted_path)
                        return cfg
                except Exception:
                    pass
        return Config()

    def save(self) -> None:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = _CONFIG_FILE.with_suffix(".tmp")
        try:
            d = asdict(self)
            d.pop("corrupted_backup_path", None)
            temp_file.write_text(
                json.dumps(d, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_file.replace(_CONFIG_FILE)
        except Exception:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            raise

    @property
    def data_dir(self) -> pathlib.Path:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        return _DATA_DIR
