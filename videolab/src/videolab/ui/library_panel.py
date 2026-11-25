"""Meme ve ses efekti kütüphanesi paneli. Çift tıklama: oynatma çubuğunun olduğu yere ekler.
NOT: Henüz gerçek bir masaüstünde denenmedi; arkasındaki Library sınıfı testlidir."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..core.library import Item, Library


class LibraryPanel(QWidget):
    insert_requested = Signal(object)        # Item

    def __init__(self, library: Library):
        super().__init__()
        self.lib = library
        lay = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText("Ara… (ad veya etiket)"); self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)
        self.tabs = QTabWidget(); lay.addWidget(self.tabs)
        self.lists = {}
        for kind, title in (("meme", "Memeler"), ("sfx", "Ses efektleri")):
            lw = QListWidget(); lw.setIconSize(lw.iconSize() * 2)
            lw.itemDoubleClicked.connect(lambda it: self.insert_requested.emit(it.data(Qt.UserRole)))
            self.tabs.addTab(lw, title); self.lists[kind] = lw
        row = QHBoxLayout()
        for text, slot in (("Ekle…", self.add_files), ("Klasörü aç", self.open_folder), ("Yenile", self.rescan), ("Sil", self.remove_selected)):
            b = QPushButton(text); b.clicked.connect(slot); row.addWidget(b)
        lay.addLayout(row)
        self.rescan()

    def _kind(self) -> str: return "meme" if self.tabs.currentIndex() == 0 else "sfx"

    def rescan(self):
        self.lib.scan(); self.refresh()

    def refresh(self, *_):
        for kind, lw in self.lists.items():
            lw.clear()
            for it in self.lib.search(self.search.text(), kind):
                w = QListWidgetItem(f"{it.name}" + (f"  ({it.duration:.1f} sn)" if it.duration else "") + (f"  #{it.tags}" if it.tags else ""))
                w.setData(Qt.UserRole, it)
                if kind == "meme" and it.is_image:
                    pm = QPixmap(it.path)
                    if not pm.isNull(): w.setIcon(QIcon(pm.scaledToHeight(48)))
                lw.addItem(w)

    def add_files(self):
        kind = self._kind()
        flt = "Görsel/Video (*.png *.jpg *.jpeg *.webp *.gif *.mp4 *.webm *.mov)" if kind == "meme" else "Ses (*.mp3 *.wav *.ogg *.m4a *.flac)"
        files, _ = QFileDialog.getOpenFileNames(self, "Kütüphaneye ekle", "", flt)
        if not files: return
        cat, _ = QInputDialog.getText(self, "Kategori", "Kategori / etiket (boş bırakabilirsiniz):")
        for f in files: self.lib.import_file(f, kind, cat.strip())
        self.refresh()

    def open_folder(self): QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.lib.folder(self._kind()))))

    def remove_selected(self):
        for it in self.lists[self._kind()].selectedItems(): self.lib.remove(it.data(Qt.UserRole).path)
        self.refresh()
