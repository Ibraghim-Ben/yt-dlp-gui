from __future__ import annotations
import json
import os
import pathlib
import time
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import DownloadTask


class StatsManager:
    def __init__(self, data_dir: pathlib.Path | str):
        self._dir = pathlib.Path(data_dir)
        self._file = self._dir / "stats.json"
        self._records: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._records = data
        except Exception:
            self._records = []

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        temp_file = self._file.with_suffix(".tmp")
        try:
            temp_file.write_text(
                json.dumps(self._records, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_file.replace(self._file)
        except Exception:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def record(self, task: "DownloadTask") -> None:
        size = 0
        if task.file_path and os.path.isfile(task.file_path):
            try:
                size = os.path.getsize(task.file_path)
            except OSError:
                size = 0

        now = datetime.now()
        entry = {
            "timestamp": time.time(),
            "date": now.strftime("%Y-%m-%d"),
            "bytes": size,
            "title": task.title or "",
            "url": task.url or "",
        }
        self._records.append(entry)
        self._save()

    def get_summary(self, days: Optional[int] = None) -> dict:
        records = self._filter_records(days)
        total_bytes = sum(int(r.get("bytes", 0)) for r in records)
        total_count = len(records)
        return {
            "total_bytes": total_bytes,
            "total_count": total_count,
        }

    def _filter_records(self, days: Optional[int]) -> list[dict]:
        if not days or days <= 0:
            return self._records
        cutoff = time.time() - (days * 86400)
        return [r for r in self._records if float(r.get("timestamp", 0)) >= cutoff]

    def get_daily(self, days: int = 7) -> list[dict]:
        today = datetime.now().date()
        if days <= 0:
            if not self._records:
                num_days = 7
            else:
                first_date_str = min(r.get("date", today.strftime("%Y-%m-%d")) for r in self._records)
                try:
                    first_date = datetime.strptime(first_date_str, "%Y-%m-%d").date()
                    delta = (today - first_date).days + 1
                    num_days = max(7, min(delta, 90))
                except Exception:
                    num_days = 30
        else:
            num_days = days

        date_map: dict[str, dict] = {}
        for i in range(num_days):
            d = today - timedelta(days=num_days - 1 - i)
            ds = d.strftime("%Y-%m-%d")
            label = d.strftime("%d %b")
            date_map[ds] = {"date": ds, "label": label, "bytes": 0, "count": 0}

        for r in self._records:
            ds = r.get("date")
            if ds in date_map:
                date_map[ds]["bytes"] += int(r.get("bytes", 0))
                date_map[ds]["count"] += 1

        return list(date_map.values())

    def clear(self) -> None:
        self._records.clear()
        self._save()
