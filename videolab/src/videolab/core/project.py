"""Proje: JSON olarak kaydedilir/açılır; son projeler ve ayarlar SQLite'ta tutulur."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .model import Timeline

FORMAT_VERSION = 1


@dataclass
class Project:
    name: str = "Adsız Proje"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    media: list[str] = field(default_factory=list)
    timeline: Timeline = field(default_factory=Timeline)
    path: str | None = None

    def __post_init__(self):
        self.timeline.fps = self.fps

    def to_dict(self) -> dict:
        return {"version": FORMAT_VERSION, "name": self.name, "width": self.width,
                "height": self.height, "fps": self.fps, "media": self.media,
                "timeline": self.timeline.to_dict()}

    def save(self, path: str | None = None) -> str:
        path = path or self.path
        if not path:
            raise ValueError("Kayıt yolu belirtilmedi")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)          # atomik: yarım yazılmış dosya bırakmaz
        self.path = path
        return path

    @staticmethod
    def load(path: str) -> "Project":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("version", 0) > FORMAT_VERSION:
            raise ValueError("Bu proje daha yeni bir VideoLab sürümüyle kaydedilmiş")
        tl = Timeline.from_dict(d["timeline"])
        return Project(d["name"], d["width"], d["height"], d["fps"], d["media"], tl, path)

    def autosave(self) -> str | None:
        if not self.path:
            return None
        p = self.path + ".autosave"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False)
        return p


class RecentProjects:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute("CREATE TABLE IF NOT EXISTS recent(path TEXT PRIMARY KEY, name TEXT, opened REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")

    def add(self, path: str, name: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO recent VALUES(?,?,?)", (path, name, time.time()))
        self.db.commit()

    def list(self, limit: int = 10) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT path,name FROM recent ORDER BY opened DESC LIMIT ?", (limit,))
        return [(p, n) for p, n in rows if os.path.exists(p)]

    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))
        self.db.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default
