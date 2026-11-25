"""Kullanıcı kütüphaneleri: meme (görsel/GIF/video) ve ses efektleri. Dosyalar kullanıcının klasöründe durur;
SQLite yalnızca dizin tutar. Alt klasör adları otomatik etiket olur (ör. memes/komik/kedi.gif -> etiket: komik)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..media.ffmpeg import probe

EXT = {
    "meme": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mkv"},
    "sfx": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"},
}


@dataclass
class Item:
    path: str
    kind: str          # "meme" | "sfx"
    name: str
    tags: str          # boşlukla ayrılmış
    duration: float    # saniye (görsellerde 0)
    is_image: bool


class Library:
    def __init__(self, db_path: str, root: str):
        """root: kullanıcının kütüphane klasörü (içinde memes/ ve sfx/ alt klasörleri oluşturulur)."""
        self.root = Path(root)
        for k in ("memes", "sfx"):
            (self.root / k).mkdir(parents=True, exist_ok=True)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS items(path TEXT PRIMARY KEY, kind TEXT, name TEXT, tags TEXT,
                           duration REAL, is_image INTEGER, added REAL)""")

    def folder(self, kind: str) -> Path:
        return self.root / ("memes" if kind == "meme" else "sfx")

    # ---- dizinleme
    def scan(self, kinds=("meme", "sfx")) -> int:
        """Klasörleri tarar; yeni dosyaları ekler, silinenleri düşürür. Eklenen sayısını döndürür."""
        added = 0
        for kind in kinds:
            base = self.folder(kind)
            seen = set()
            for p in base.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in EXT[kind]:
                    continue
                sp = str(p); seen.add(sp)
                if self.db.execute("SELECT 1 FROM items WHERE path=?", (sp,)).fetchone():
                    continue
                rel = p.relative_to(base).parts[:-1]
                tags = " ".join(x.lower() for x in rel)
                is_img = p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
                try:
                    dur = 0.0 if is_img else probe(sp).duration
                except Exception:
                    continue                                  # bozuk dosyayı atla
                self.db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?)",
                                (sp, kind, p.stem, tags, dur, int(is_img), time.time())); added += 1
            for (sp,) in self.db.execute("SELECT path FROM items WHERE kind=?", (kind,)).fetchall():
                if sp not in seen:
                    self.db.execute("DELETE FROM items WHERE path=?", (sp,))
        self.db.commit()
        return added

    def import_file(self, src: str, kind: str, category: str = "") -> str:
        """Dosyayı kütüphane klasörüne kopyalar (alt klasör = kategori/etiket) ve dizine ekler."""
        dst_dir = self.folder(kind) / category if category else self.folder(kind)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / Path(src).name
        n = 1
        while dst.exists():
            dst = dst_dir / f"{Path(src).stem}_{n}{Path(src).suffix}"; n += 1
        shutil.copy2(src, dst)
        self.scan((kind,))
        return str(dst)

    def set_tags(self, path: str, tags: str) -> None:
        self.db.execute("UPDATE items SET tags=? WHERE path=?", (tags.lower(), path)); self.db.commit()

    def remove(self, path: str, delete_file: bool = False) -> None:
        self.db.execute("DELETE FROM items WHERE path=?", (path,)); self.db.commit()
        if delete_file and os.path.exists(path):
            os.remove(path)

    # ---- arama
    def search(self, query: str = "", kind: str | None = None, limit: int = 500) -> list[Item]:
        sql, args = "SELECT path,kind,name,tags,duration,is_image FROM items WHERE 1=1", []
        if kind:
            sql += " AND kind=?"; args.append(kind)
        for term in query.lower().split():
            sql += " AND (lower(name) LIKE ? OR tags LIKE ?)"; args += [f"%{term}%", f"%{term}%"]
        sql += " ORDER BY name COLLATE NOCASE LIMIT ?"; args.append(limit)
        return [Item(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in self.db.execute(sql, args)]
